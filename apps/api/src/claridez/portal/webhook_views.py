from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from svix.webhooks import Webhook, WebhookVerificationError

from claridez.communications.public import (
    CommunicationsError,
    reconcile_provider_event,
    sender_identity_for_webhook,
)
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.tenant_scope import external_tenant_scope

from .errors import PortalError
from .services import resolve_communications_webhook_locator


def _error(status: int = 400) -> Response:
    return Response(
        {"error": {"code": "invalid_webhook", "message": "El webhook no es válido."}},
        status=status,
    )


def _provider_headers(request: Request, provider: str) -> tuple[str, str, str]:
    if provider == "deterministic":
        return (
            request.headers.get("X-Webhook-ID", ""),
            request.headers.get("X-Webhook-Timestamp", ""),
            request.headers.get("X-Webhook-Signature", ""),
        )
    if provider == "resend":
        return (
            request.headers.get("Svix-ID", ""),
            request.headers.get("Svix-Timestamp", ""),
            request.headers.get("Svix-Signature", ""),
        )
    return "", "", ""


def _signature_valid(
    payload: bytes,
    *,
    provider: str,
    event_id: str,
    timestamp: str,
    signature: str,
) -> bool:
    if provider == "deterministic":
        secret = settings.COMMUNICATIONS_WEBHOOK_SECRET
        if not secret:
            return False
        expected = hmac.new(
            secret.encode(),
            f"{event_id}.{timestamp}.".encode() + payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, expected)
    if provider != "resend" or not settings.COMMUNICATIONS_WEBHOOK_SECRET:
        return False
    try:
        Webhook(settings.COMMUNICATIONS_WEBHOOK_SECRET).verify(
            payload,
            {
                "svix-id": event_id,
                "svix-timestamp": timestamp,
                "svix-signature": signature,
            },
        )
    except (ValueError, WebhookVerificationError):
        return False
    return True


def _provider_event(data: object, provider: str) -> tuple[str, str, datetime]:
    if not isinstance(data, dict):
        raise ValueError
    occurred_at = datetime.fromisoformat(str(data["created_at"]).replace("Z", "+00:00"))
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError
    event_type = str(data["type"])
    if provider == "resend":
        provider_data = data["data"]
        if not isinstance(provider_data, dict):
            raise ValueError
        external_message_id = str(provider_data["email_id"])
    else:
        external_message_id = str(data.get("message_id", ""))
    return event_type, external_message_id, occurred_at


@method_decorator(csrf_exempt, name="dispatch")
class CommunicationsWebhookView(APIView):
    authentication_classes: list[type[Any]] = []
    permission_classes: list[type[Any]] = []

    @extend_schema(
        request=None,
        responses={202: OpenApiResponse(description="Evento de proveedor aceptado.")},
        tags=["Webhooks Communications"],
    )
    def post(self, request: Request, locator: str) -> Response:
        payload = request.body
        try:
            data = json.loads(payload)
            authorization, sender_id = resolve_communications_webhook_locator(locator)
            with external_tenant_scope(authorization):
                sender = sender_identity_for_webhook(authorization.organization_id, sender_id)
                if sender is None:
                    return _error(404)
                provider, account = sender
                event_id, timestamp_text, signature = _provider_headers(request, provider)
                timestamp_value = int(timestamp_text)
                signature_at = datetime.fromtimestamp(timestamp_value, tz=UTC)
                if (
                    abs((timezone.now() - signature_at).total_seconds())
                    > settings.COMMUNICATIONS_WEBHOOK_REPLAY_SECONDS
                    or not event_id
                    or not _signature_valid(
                        payload,
                        provider=provider,
                        event_id=event_id,
                        timestamp=timestamp_text,
                        signature=signature,
                    )
                ):
                    return _error()
                event_type, external_message_id, occurred_at = _provider_event(data, provider)
                reconcile_provider_event(
                    authorization.organization_id,
                    provider=provider,
                    account=account,
                    event_id=event_id,
                    event_type=event_type,
                    external_message_id=external_message_id,
                    occurred_at=occurred_at,
                    signature_timestamp=signature_at,
                    payload_sha256=hashlib.sha256(payload).hexdigest(),
                )
        except (
            ValueError,
            KeyError,
            TypeError,
            OSError,
            OverflowError,
            json.JSONDecodeError,
            PortalError,
            CommunicationsError,
            AuthorizationDenied,
        ):
            return _error()
        return Response({"status": "accepted"}, status=202)
