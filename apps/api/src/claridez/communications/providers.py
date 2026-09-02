from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings


@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    channel: str
    recipient: str
    subject: str
    body: str
    sender: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    accepted: bool
    provider: str
    external_id: str
    error_category: str = ""
    response_code: str = ""
    retry_after_seconds: int | None = None
    terminal: bool = False


class DeliveryProvider(Protocol):
    name: str

    def send(self, request: DeliveryRequest) -> DeliveryResult: ...


class DeterministicProvider:
    name = "deterministic"

    def send(self, request: DeliveryRequest) -> DeliveryResult:
        if request.recipient.endswith("@provider-outage.test"):
            return DeliveryResult(
                accepted=False,
                provider=self.name,
                external_id="",
                error_category="provider_unavailable",
                response_code="503",
            )
        return DeliveryResult(
            accepted=True,
            provider=self.name,
            external_id=f"test-{request.idempotency_key}",
            response_code="202",
        )


class ResendProvider:
    name = "resend"

    def send(self, request: DeliveryRequest) -> DeliveryResult:
        api_key = settings.COMMUNICATIONS_RESEND_API_KEY
        if not api_key:
            return DeliveryResult(
                accepted=False,
                provider=self.name,
                external_id="",
                error_category="provider_not_configured",
                terminal=True,
            )
        payload = json.dumps(
            {
                "from": request.sender,
                "to": [request.recipient],
                "subject": request.subject,
                "text": request.body,
            }
        ).encode()
        http_request = urllib.request.Request(
            settings.COMMUNICATIONS_RESEND_API_URL,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": request.idempotency_key,
            },
        )
        try:
            with urllib.request.urlopen(http_request, timeout=10) as response:  # noqa: S310
                data = json.loads(response.read())
                external_id = str(data.get("id", ""))
                if not external_id:
                    return DeliveryResult(
                        accepted=False,
                        provider=self.name,
                        external_id="",
                        error_category="provider_invalid_response",
                        response_code=str(response.status),
                    )
                return DeliveryResult(
                    accepted=True,
                    provider=self.name,
                    external_id=external_id,
                    response_code=str(response.status),
                )
        except urllib.error.HTTPError as error:
            retry_after = error.headers.get("Retry-After")
            return DeliveryResult(
                accepted=False,
                provider=self.name,
                external_id="",
                error_category="provider_rate_limit" if error.code == 429 else "provider_rejected",
                response_code=str(error.code),
                retry_after_seconds=int(retry_after)
                if retry_after and retry_after.isdigit()
                else None,
                terminal=400 <= error.code < 500 and error.code != 429,
            )
        except (OSError, ValueError):
            return DeliveryResult(
                accepted=False,
                provider=self.name,
                external_id="",
                error_category="provider_unavailable",
            )


class DisabledWhatsAppProvider:
    name = "whatsapp_disabled"

    def send(self, request: DeliveryRequest) -> DeliveryResult:
        del request
        return DeliveryResult(
            accepted=False,
            provider=self.name,
            external_id="",
            error_category="provider_not_configured",
            terminal=True,
        )


def provider_for(channel: str) -> DeliveryProvider:
    configured = settings.COMMUNICATIONS_PROVIDER
    if channel == "whatsapp" and configured != "deterministic":
        return DisabledWhatsAppProvider()
    if configured == "resend" and channel == "email":
        return ResendProvider()
    return DeterministicProvider()
