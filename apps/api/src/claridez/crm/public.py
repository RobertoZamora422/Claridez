"""Puerto público estrecho para interacciones semánticas aprobadas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db import IntegrityError, transaction

from claridez.commercial.public import client_event_request
from claridez.people.public import canonical_person_id

from .analytics import fetch_analytics_metrics
from .models import Interaction

APPROVED_COMMUNICATION_PURPOSES = frozenset({"capture_acknowledgement"})


class CrmPortError(Exception):
    pass


def record_communication_interaction(
    organization_id: UUID,
    *,
    person_id: UUID,
    event_request_id: UUID,
    channel: str,
    purpose: str,
    occurred_at: datetime,
    logical_message_reference: UUID,
) -> UUID:
    """Registra solo el significado comercial, nunca entrega, proveedor o cuerpo."""
    if purpose not in APPROVED_COMMUNICATION_PURPOSES:
        raise CrmPortError("El propósito no está aprobado como interacción comercial.")
    if channel not in {Interaction.Channel.EMAIL, Interaction.Channel.WHATSAPP}:
        raise CrmPortError("El canal no es válido para la interacción aprobada.")
    event = client_event_request(organization_id, event_request_id)
    canonical = canonical_person_id(organization_id, person_id)
    if canonical_person_id(organization_id, event.person_id) != canonical:
        raise CrmPortError("La solicitud no pertenece a la persona canónica.")
    try:
        with transaction.atomic():
            row = Interaction.objects.create(
                organization_id=organization_id,
                person_id=canonical,
                event_request_id=event_request_id,
                channel=channel,
                direction=Interaction.Direction.OUTBOUND,
                occurred_at=occurred_at,
                responsible_membership=None,
                summary="Acuse de recepción de la solicitud emitido.",
                recorded_by_membership=None,
                recorder_kind=Interaction.RecorderKind.COMMUNICATIONS,
                communication_purpose=purpose,
                communication_reference=logical_message_reference,
            )
            return row.pk
    except IntegrityError:
        existing = Interaction.objects.filter(
            organization_id=organization_id,
            recorder_kind=Interaction.RecorderKind.COMMUNICATIONS,
            communication_reference=logical_message_reference,
        ).first()
        if (
            existing
            and existing.person_id == canonical
            and existing.event_request_id == event_request_id
            and existing.channel == channel
            and existing.communication_purpose == purpose
        ):
            return existing.pk
        raise CrmPortError("La referencia semántica ya fue usada con otros datos.") from None


__all__ = ("CrmPortError", "fetch_analytics_metrics", "record_communication_interaction")
