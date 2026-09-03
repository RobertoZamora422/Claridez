"""Puerto técnico estrecho para coordinadores externos y de aplicación."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.utils import timezone

from claridez.people.public import contact_for_external_control

from .errors import unavailable
from .models import PortalChallenge, PortalPrincipal
from .security import digest
from .services import resolve_communications_webhook_locator


@dataclass(frozen=True, slots=True)
class PortalAuthenticationRetryDecision:
    challenge_id: UUID
    person_id: UUID
    source_version: int


def portal_authentication_retry_decision(
    organization_id: UUID, challenge_id: UUID
) -> PortalAuthenticationRetryDecision:
    """Confirma que un challenge y su contacto siguen siendo aptos para entrega."""
    row = (
        PortalChallenge.objects.select_related("principal")
        .filter(
            organization_id=organization_id,
            pk=challenge_id,
            principal__state=PortalPrincipal.State.ACTIVE,
            consumed_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if row is None:
        raise unavailable()
    contact = contact_for_external_control(
        organization_id,
        person_id=row.principal.person_reference,
        channel=row.channel,
    )
    if (
        contact is None
        or contact.person_revision != row.contact_revision
        or digest(contact.value, purpose="contact") != row.contact_fingerprint
    ):
        raise unavailable()
    return PortalAuthenticationRetryDecision(
        challenge_id=row.pk,
        person_id=contact.canonical_person_id,
        source_version=1,
    )


__all__ = (
    "PortalAuthenticationRetryDecision",
    "portal_authentication_retry_decision",
    "resolve_communications_webhook_locator",
)
