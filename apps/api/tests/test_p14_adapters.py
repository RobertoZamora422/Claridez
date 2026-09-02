from __future__ import annotations

import json
import urllib.error
import urllib.request
from email.message import Message
from typing import Any, cast

from django.test import override_settings

from claridez.communications.providers import (
    DeliveryRequest,
    DeterministicProvider,
    DisabledWhatsAppProvider,
    ResendProvider,
    provider_for,
)
from claridez.portal.security import TurnstileAntiAbuse


class _Response:
    def __init__(self, body: object, *, status: int = 200) -> None:
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _delivery(recipient: str = "client@example.com") -> DeliveryRequest:
    return DeliveryRequest(
        channel="email",
        recipient=recipient,
        subject="Actualización",
        body="Contenido transaccional",
        sender="Organización vía Claridez <notificaciones@tx.claridez.example>",
        idempotency_key="logical-message-id",
    )


@override_settings(
    COMMUNICATIONS_RESEND_API_KEY="test-key",
    COMMUNICATIONS_RESEND_API_URL="https://api.resend.test/emails",
)
def test_resend_adapter_uses_provider_idempotency_and_requires_external_id(
    monkeypatch: Any,
) -> None:
    captured: dict[str, object] = {}

    def accepted(request: Any, *, timeout: int) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response({"id": "provider-message"}, status=202)

    monkeypatch.setattr("urllib.request.urlopen", accepted)
    result = ResendProvider().send(_delivery())
    request = cast(urllib.request.Request, captured["request"])
    assert result.accepted is True
    assert result.external_id == "provider-message"
    assert captured["timeout"] == 10
    assert request.get_header("Idempotency-key") == "logical-message-id"
    assert request.get_header("Authorization") == "Bearer test-key"

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_args, **_kwargs: _Response({}, status=202)
    )
    invalid = ResendProvider().send(_delivery())
    assert invalid.accepted is False
    assert invalid.error_category == "provider_invalid_response"
    assert invalid.terminal is False

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_args, **_kwargs: _Response(b"not-json", status=502)
    )
    malformed = ResendProvider().send(_delivery())
    assert malformed.accepted is False
    assert malformed.error_category == "provider_unavailable"
    assert malformed.terminal is False


@override_settings(COMMUNICATIONS_RESEND_API_KEY="test-key")
def test_resend_adapter_normalizes_retry_after_and_outage(monkeypatch: Any) -> None:
    headers = Message()
    headers["Retry-After"] = "90"

    def rate_limited(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.HTTPError(
            "https://api.resend.test/emails", 429, "limited", headers, None
        )

    monkeypatch.setattr("urllib.request.urlopen", rate_limited)
    retry = ResendProvider().send(_delivery())
    assert retry.accepted is False
    assert retry.error_category == "provider_rate_limit"
    assert retry.retry_after_seconds == 90
    assert retry.terminal is False

    def outage(*_args: object, **_kwargs: object) -> None:
        raise OSError("provider unavailable")

    monkeypatch.setattr("urllib.request.urlopen", outage)
    unavailable = ResendProvider().send(_delivery())
    assert unavailable.error_category == "provider_unavailable"
    assert unavailable.terminal is False


@override_settings(
    PORTAL_TURNSTILE_SECRET_KEY="test-secret",
)
def test_turnstile_adapter_validates_server_side_result(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def verify(request: Any, *, timeout: int) -> _Response:
        captured["data"] = request.data
        captured["timeout"] = timeout
        return _Response(
            {"success": True, "hostname": "forms.example", "action": "public_form_submit"}
        )

    monkeypatch.setattr("urllib.request.urlopen", verify)
    result = TurnstileAntiAbuse().verify(
        "single-use-token",
        action="public_form_submit",
        hostname="forms.example",
        remote_ip="192.0.2.10",
    )
    assert result.valid is True
    assert result.hostname == "forms.example"
    assert result.action == "public_form_submit"
    assert captured["timeout"] == 5
    request_data = cast(bytes, captured["data"])
    assert b"secret=test-secret" in request_data
    assert b"response=single-use-token" in request_data
    assert b"remoteip=192.0.2.10" in request_data

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response(b"not-json"))
    malformed = TurnstileAntiAbuse().verify(
        "single-use-token",
        action="public_form_submit",
        hostname="forms.example",
        remote_ip="192.0.2.10",
    )
    assert malformed.valid is False


@override_settings(COMMUNICATIONS_PROVIDER="resend")
def test_development_adapters_keep_whatsapp_disabled_without_tenant_sender_onboarding() -> None:
    assert isinstance(provider_for("whatsapp"), DisabledWhatsAppProvider)
    assert DeterministicProvider().send(_delivery("client@provider-outage.test")).accepted is False
