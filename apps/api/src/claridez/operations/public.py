"""Puerto público de coordinación operativa; no expone instancias ORM."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from claridez.organizations.models import Membership
from claridez.organizations.tenant_scope import TenantAuthorization

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
    def quotation_version_id(self) -> UUID: ...

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


@dataclass(frozen=True, slots=True)
class ExecutionEvidenceProjection:
    organization_id: UUID
    root_reservation_id: UUID
    reservation_id: UUID
    execution_started_transition_id: UUID | None
    execution_started_at: datetime | None
    execution_completed_transition_id: UUID | None
    execution_completed_at: datetime | None


def _execution_projection(row: EventPreparation) -> ExecutionEvidenceProjection:
    transitions = {
        item.cause: item
        for item in PreparationTransition.objects.filter(
            organization_id=row.organization_id,
            preparation_id=row.reservation_id,
            cause__in=[
                PreparationTransition.Cause.EXECUTION_STARTED,
                PreparationTransition.Cause.EXECUTION_COMPLETED,
            ],
        )
    }
    started = transitions.get(PreparationTransition.Cause.EXECUTION_STARTED)
    completed = transitions.get(PreparationTransition.Cause.EXECUTION_COMPLETED)
    return ExecutionEvidenceProjection(
        organization_id=row.organization_id,
        root_reservation_id=row.reservation.root_id,
        reservation_id=row.reservation_id,
        execution_started_transition_id=None if started is None else started.pk,
        execution_started_at=None if started is None else started.occurred_at,
        execution_completed_transition_id=None if completed is None else completed.pk,
        execution_completed_at=None if completed is None else completed.occurred_at,
    )


def execution_evidence_for_finance(
    authorization: TenantAuthorization,
    root_reservation_id: UUID,
    *,
    lock: bool = False,
) -> ExecutionEvidenceProjection | None:
    rows = EventPreparation.objects.select_related("reservation")
    if lock:
        rows = rows.select_for_update()
    row = (
        rows.filter(
            organization_id=authorization.organization_id,
            reservation__root_id=root_reservation_id,
        )
        .order_by("-reservation__created_at", "-reservation_id")
        .first()
    )
    return None if row is None else _execution_projection(row)


def execution_evidences_for_finance(
    authorization: TenantAuthorization,
) -> tuple[ExecutionEvidenceProjection, ...]:
    latest: dict[UUID, EventPreparation] = {}
    for row in (
        EventPreparation.objects.select_related("reservation")
        .filter(organization_id=authorization.organization_id)
        .order_by("reservation__root_id", "reservation__created_at", "reservation_id")
    ):
        latest[row.reservation.root_id] = row
    return tuple(_execution_projection(row) for row in latest.values())


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


def has_document_relationship(organization_id: UUID, root_reservation_id: UUID) -> bool:
    return EventPreparation.objects.filter(
        organization_id=organization_id,
        reservation__root_id=root_reservation_id,
    ).exists()


def initialize_from_accepted_snapshot(
    reservation: ReservationValue,
    *,
    actor_membership_id: UUID,
    occurred_at: datetime,
    responsible_membership_id: UUID | None = None,
    plan_source_snapshot: object | None = None,
    materialize_plan: bool = True,
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
                source_kind=PreparationItem.SourceKind.BASELINE_5_2,
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
    from .advanced import materialize_operational_plan
    from .advanced_models import OperationalPlanSnapshot

    if materialize_plan:
        materialize_operational_plan(
            preparation,
            quotation_version_id=reservation.quotation_version_id,
            starts_at=reservation.starts_at,
            timezone_name=reservation.timezone_name,
            occurred_at=occurred_at,
            source_snapshot=(
                plan_source_snapshot
                if isinstance(plan_source_snapshot, OperationalPlanSnapshot)
                else None
            ),
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
    free_items = [
        item
        for item in items
        if item.pk in requested and item.source_kind == PreparationItem.SourceKind.MANUAL
    ]
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

    plan_source_snapshot = getattr(preparation, "operational_snapshot", None)
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
        plan_source_snapshot=plan_source_snapshot,
        materialize_plan=False,
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
            source_kind=PreparationItem.SourceKind.MANUAL,
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


def materialize_rescheduled_plan(
    previous_reservation_id: UUID,
    successor: ReservationValue,
    *,
    occurred_at: datetime,
) -> None:
    from .advanced import materialize_operational_plan
    from .advanced_models import OperationalPlanSnapshot

    preparation = EventPreparation.objects.select_for_update().get(
        organization_id=successor.organization_id,
        reservation_id=successor.id,
    )
    if OperationalPlanSnapshot.objects.filter(preparation=preparation).exists():
        return
    source = OperationalPlanSnapshot.objects.get(
        organization_id=successor.organization_id,
        preparation_id=previous_reservation_id,
    )
    materialize_operational_plan(
        preparation,
        quotation_version_id=successor.quotation_version_id,
        starts_at=successor.starts_at,
        timezone_name=successor.timezone_name,
        occurred_at=occurred_at,
        source_snapshot=source,
    )


__all__ = (
    "OperationsError",
    "PreparationProjection",
    "ExecutionEvidenceProjection",
    "cancel_for_schedule",
    "initialize_from_accepted_snapshot",
    "has_document_relationship",
    "execution_evidence_for_finance",
    "execution_evidences_for_finance",
    "preparation_for_schedule",
    "reschedule_preparation",
    "materialize_rescheduled_plan",
    "OperationalWindowProjection",
    "operational_window_for_resources",
)


@dataclass(frozen=True, slots=True)
class OperationalWindowProjection:
    id: UUID
    organization_id: UUID
    preparation_id: UUID
    root_reservation_id: UUID
    reservation_id: UUID
    resource_id: UUID
    quantity: Decimal
    starts_at: datetime
    ends_at: datetime
    window_revision: int
    source_kind: str
    source_version: str
    schedule_allocation_id: UUID
    schedule_event_id: UUID
    schedule_reservation_revision: int
    schedule_source_revision: int
    payload_sha256: str


def operational_window_for_resources(
    organization_id: UUID, window_id: UUID, *, lock: bool = False
) -> OperationalWindowProjection | None:
    from .advanced import operational_window_for_resources_projection

    value = operational_window_for_resources_projection(organization_id, window_id, lock=lock)
    if value is None:
        return None
    return OperationalWindowProjection(
        id=value.id,
        organization_id=value.organization_id,
        preparation_id=value.preparation_id,
        root_reservation_id=value.root_reservation_id,
        reservation_id=value.reservation_id,
        resource_id=value.resource_id,
        quantity=value.quantity,
        starts_at=value.starts_at,
        ends_at=value.ends_at,
        window_revision=value.window_revision,
        source_kind=value.source_kind,
        source_version=value.source_version,
        schedule_allocation_id=value.schedule_allocation_id,
        schedule_event_id=value.schedule_event_id,
        schedule_reservation_revision=value.schedule_reservation_revision,
        schedule_source_revision=value.schedule_source_revision,
        payload_sha256=value.payload_sha256,
    )
