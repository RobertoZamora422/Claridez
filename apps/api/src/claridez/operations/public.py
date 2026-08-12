"""Puerto público de coordinación operativa; no expone instancias ORM."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from claridez.organizations.models import Membership

from .baseline import (
    BASELINE,
    BASELINE_VERSION,
    baseline_item_id,
    baseline_request_id,
    due_date,
    transition_id,
)
from .errors import OperationsError, conflict
from .models import EventPreparation, PreparationItem, PreparationTransition
from .services.lifecycle import cancel_preparation
from .services.shared import append_transition, eligible_membership


class ReservationValue(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def organization_id(self) -> UUID: ...

    @property
    def starts_at(self) -> datetime: ...

    @property
    def timezone_name(self) -> str: ...

    @property
    def status(self) -> str: ...


@dataclass(frozen=True, slots=True)
class PreparationProjection:
    reservation_id: UUID
    status: str
    revision: int
    responsible_membership_id: UUID | None


def _projection(row: EventPreparation) -> PreparationProjection:
    return PreparationProjection(
        reservation_id=row.reservation_id,
        status=row.status,
        revision=row.revision,
        responsible_membership_id=row.responsible_membership_id,
    )


def preparation_for_schedule(
    organization_id: UUID, reservation_id: UUID, *, lock: bool = False
) -> PreparationProjection | None:
    rows = EventPreparation.objects.all()
    if lock:
        rows = rows.select_for_update()
    row = rows.filter(organization_id=organization_id, reservation_id=reservation_id).first()
    return None if row is None else _projection(row)


def initialize_from_accepted_snapshot(
    reservation: ReservationValue,
    *,
    actor_membership_id: UUID,
    occurred_at: datetime,
    responsible_membership_id: UUID | None = None,
) -> PreparationProjection:
    preparation = EventPreparation.objects.create(
        reservation_id=reservation.id,
        organization_id=reservation.organization_id,
        status=EventPreparation.Status.PREPARING,
        baseline_version=BASELINE_VERSION,
        responsible_membership_id=responsible_membership_id,
        revision=1,
    )
    PreparationItem.objects.bulk_create(
        [
            PreparationItem(
                id=baseline_item_id(reservation.id, definition.key),
                organization_id=reservation.organization_id,
                preparation=preparation,
                client_request_id=baseline_request_id(reservation.id, definition.key),
                baseline_key=definition.key,
                section=definition.section,
                position=position,
                title=definition.title,
                is_required=True,
                due_on=due_date(
                    starts_at=reservation.starts_at,
                    timezone_name=reservation.timezone_name,
                    confirmed_at=occurred_at,
                    days_before=definition.days_before,
                ),
            )
            for position, definition in enumerate(BASELINE, start=1)
        ]
    )
    append_transition(
        preparation,
        from_status=None,
        to_status=EventPreparation.Status.PREPARING,
        cause=PreparationTransition.Cause.INITIALIZED,
        actor_membership_id=actor_membership_id,
        occurred_at=occurred_at,
        identifier=transition_id(reservation.id, PreparationTransition.Cause.INITIALIZED),
    )
    return _projection(preparation)


def cancel_for_schedule(
    organization_id: UUID,
    reservation_id: UUID,
    *,
    actor_membership_id: UUID,
    occurred_at: datetime,
) -> PreparationProjection | None:
    row = (
        EventPreparation.objects.select_for_update()
        .filter(organization_id=organization_id, reservation_id=reservation_id)
        .first()
    )
    if row is None:
        return None
    cancel_preparation(
        row,
        actor_membership_id=actor_membership_id,
        occurred_at=occurred_at,
    )
    row.refresh_from_db()
    return _projection(row)


def reschedule_preparation(
    previous: ReservationValue,
    successor: ReservationValue,
    *,
    actor_membership_id: UUID,
    occurred_at: datetime,
    carry_free_item_ids: tuple[UUID, ...],
) -> tuple[PreparationProjection, PreparationProjection, tuple[UUID, ...]]:
    preparation = EventPreparation.objects.select_for_update().get(
        organization_id=previous.organization_id,
        reservation_id=previous.id,
    )
    if preparation.status == EventPreparation.Status.IN_PROGRESS:
        raise conflict("operation_already_started", "El evento ya está en ejecución.")
    if preparation.status == EventPreparation.Status.COMPLETED:
        raise conflict("operation_already_completed", "El evento ya fue completado.")
    if preparation.status not in {
        EventPreparation.Status.PREPARING,
        EventPreparation.Status.READY,
    }:
        raise conflict("invalid_transition", "La preparación no puede reprogramarse.")

    items = list(
        PreparationItem.objects.select_for_update()
        .filter(organization_id=previous.organization_id, preparation=preparation)
        .order_by("position", "id")
    )
    requested = set(carry_free_item_ids)
    free_items = [item for item in items if item.pk in requested and item.baseline_key is None]
    if {item.pk for item in free_items} != requested:
        raise conflict(
            "invalid_transition", "Solo pueden trasladarse ítems libres de esta preparación."
        )

    responsible_id = preparation.responsible_membership_id
    if responsible_id is not None:
        try:
            eligible_membership(previous.organization_id, responsible_id)
        except OperationsError:
            responsible_id = None

    previous_status = preparation.status
    preparation.status = EventPreparation.Status.RESCHEDULED
    preparation.rescheduled_to_reservation_id = successor.id
    preparation.revision += 1
    preparation.save(
        update_fields=["status", "rescheduled_to_reservation", "revision", "updated_at"]
    )
    append_transition(
        preparation,
        from_status=previous_status,
        to_status=EventPreparation.Status.RESCHEDULED,
        cause=PreparationTransition.Cause.SCHEDULE_RESCHEDULE,
        actor_membership_id=actor_membership_id,
        occurred_at=occurred_at,
    )

    new_projection = initialize_from_accepted_snapshot(
        successor,
        actor_membership_id=actor_membership_id,
        occurred_at=occurred_at,
        responsible_membership_id=responsible_id,
    )
    new_preparation = EventPreparation.objects.get(pk=successor.id)
    start_position = len(BASELINE) + 1
    carried_ids: list[UUID] = []
    for offset, item in enumerate(free_items):
        new_id = uuid4()
        PreparationItem.objects.create(
            id=new_id,
            organization_id=previous.organization_id,
            preparation=new_preparation,
            client_request_id=uuid4(),
            baseline_key=None,
            section=item.section,
            position=start_position + offset,
            title=item.title,
            is_required=item.is_required,
            responsible_membership_id=(
                item.responsible_membership_id
                if item.responsible_membership_id is not None
                and Membership.objects.filter(
                    pk=item.responsible_membership_id,
                    organization_id=previous.organization_id,
                    status=Membership.Status.ACTIVE,
                    role__in=[
                        Membership.Role.OWNER,
                        Membership.Role.ADMINISTRATOR,
                        Membership.Role.OPERATIONS,
                    ],
                ).exists()
                else None
            ),
            due_on=None,
            status=PreparationItem.Status.PENDING,
            notes=item.notes,
            status_note="",
            resolved_at=None,
            resolved_by_membership_id=None,
            carried_from_item=item,
            revision=1,
        )
        carried_ids.append(new_id)
    preparation.refresh_from_db()
    return _projection(preparation), new_projection, tuple(carried_ids)


__all__ = (
    "OperationsError",
    "PreparationProjection",
    "cancel_for_schedule",
    "initialize_from_accepted_snapshot",
    "preparation_for_schedule",
    "reschedule_preparation",
)
