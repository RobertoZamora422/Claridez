from __future__ import annotations

from datetime import datetime
from uuid import UUID

from claridez.commercial.models import Reservation

from ..baseline import (
    BASELINE,
    BASELINE_KEYS,
    BASELINE_VERSION,
    baseline_item_id,
    baseline_request_id,
    due_date,
    transition_id,
)
from ..errors import conflict
from ..models import EventPreparation, PreparationItem, PreparationTransition
from .shared import EDITABLE_PREPARATION_STATES, append_transition, increment_preparation


def initialize_preparation(
    reservation: Reservation, *, actor_membership_id: UUID, occurred_at: datetime
) -> EventPreparation:
    """Crear el agregado base; solo lo invoca el coordinador de confirmación."""
    preparation = EventPreparation.objects.create(
        reservation=reservation,
        organization_id=reservation.organization_id,
        status=EventPreparation.Status.PREPARING,
        baseline_version=BASELINE_VERSION,
        revision=1,
    )
    starts_at = reservation.quotation_version.event_starts_at_snapshot
    items = [
        PreparationItem(
            id=baseline_item_id(reservation.pk, definition.key),
            organization_id=reservation.organization_id,
            preparation=preparation,
            client_request_id=baseline_request_id(reservation.pk, definition.key),
            baseline_key=definition.key,
            section=definition.section,
            position=position,
            title=definition.title,
            is_required=True,
            due_on=due_date(
                starts_at=starts_at,
                timezone_name=reservation.event_timezone,
                confirmed_at=occurred_at,
                days_before=definition.days_before,
            ),
        )
        for position, definition in enumerate(BASELINE, start=1)
    ]
    PreparationItem.objects.bulk_create(items)
    append_transition(
        preparation,
        from_status=None,
        to_status=EventPreparation.Status.PREPARING,
        cause=PreparationTransition.Cause.INITIALIZED,
        actor_membership_id=actor_membership_id,
        occurred_at=occurred_at,
        identifier=transition_id(reservation.pk, PreparationTransition.Cause.INITIALIZED),
    )
    return preparation


def validate_initialized_preparation(reservation: Reservation) -> EventPreparation:
    try:
        preparation = EventPreparation.objects.select_for_update().get(
            organization_id=reservation.organization_id, reservation_id=reservation.pk
        )
    except EventPreparation.DoesNotExist:
        raise conflict(
            "operation_integrity_conflict", "La reserva no tiene una preparación operativa íntegra."
        ) from None
    keys = list(
        PreparationItem.objects.filter(
            organization_id=reservation.organization_id, preparation_id=reservation.pk
        ).values_list("baseline_key", flat=True)
    )
    initialized_count = PreparationTransition.objects.filter(
        organization_id=reservation.organization_id,
        preparation_id=reservation.pk,
        cause=PreparationTransition.Cause.INITIALIZED,
    ).count()
    if set(filter(None, keys)) != BASELINE_KEYS or len(keys) < 7 or initialized_count != 1:
        raise conflict(
            "operation_integrity_conflict", "La reserva no tiene una preparación operativa íntegra."
        )
    return preparation


def cancel_preparation(
    preparation: EventPreparation, *, actor_membership_id: UUID, occurred_at: datetime
) -> None:
    if preparation.status == EventPreparation.Status.CANCELLED:
        return
    if preparation.status == EventPreparation.Status.IN_PROGRESS:
        raise conflict("operation_already_started", "El evento ya está en ejecución.")
    if preparation.status == EventPreparation.Status.COMPLETED:
        raise conflict("operation_already_completed", "El evento ya fue completado.")
    if preparation.status not in EDITABLE_PREPARATION_STATES:
        raise conflict("invalid_transition", "La preparación no puede cancelarse.")
    previous = preparation.status
    preparation.status = EventPreparation.Status.CANCELLED
    increment_preparation(preparation, fields=["status"])
    append_transition(
        preparation,
        from_status=previous,
        to_status=EventPreparation.Status.CANCELLED,
        cause=PreparationTransition.Cause.COMMERCIAL_CANCELLATION,
        actor_membership_id=actor_membership_id,
        occurred_at=occurred_at,
    )
