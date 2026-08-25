"""Puerto público estrecho e inmutable de agenda."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from claridez.organizations.tenant_scope import TenantAuthorization

from .errors import SchedulingError


@dataclass(frozen=True, slots=True)
class ReservationProjection:
    id: UUID
    organization_id: UUID
    event_request_id: UUID
    quotation_version_id: UUID
    root_id: UUID
    predecessor_id: UUID | None
    space_id: UUID
    starts_at: datetime
    ends_at: datetime
    timezone_name: str
    status: str
    revision: int
    hold_expires_at: datetime
    confirmed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ResourceScheduleProjection:
    reservation_id: UUID
    root_id: UUID
    starts_at: datetime
    ends_at: datetime
    status: str


@dataclass(frozen=True, slots=True)
class ResourceAvailabilityContextProjection:
    event_request_id: UUID
    reservation_id: UUID
    root_id: UUID
    starts_at: datetime
    ends_at: datetime
    status: str


@dataclass(frozen=True, slots=True)
class OperationsScheduleAuthorityProjection:
    organization_id: UUID
    reservation_id: UUID
    root_reservation_id: UUID
    space_id: UUID
    status: str
    reservation_revision: int
    event_starts_at: datetime
    event_ends_at: datetime
    occupied_starts_at: datetime
    occupied_ends_at: datetime
    allocation_id: UUID
    allocation_source_revision: int
    source_event_id: UUID
    source_event_kind: str
    source_event_aggregate_revision: int
    source_event_reservation_id: UUID | None
    source_event_predecessor_id: UUID | None
    source_event_successor_id: UUID | None


def schedule_authority_for_operations(
    organization_id: UUID, reservation_id: UUID, *, lock: bool = False
) -> OperationsScheduleAuthorityProjection | None:
    from .models import Reservation, ScheduleAllocation

    reservation_rows = Reservation.objects.all()
    if lock:
        reservation_rows = reservation_rows.select_for_update()
    row = reservation_rows.filter(organization_id=organization_id, pk=reservation_id).first()
    if row is None:
        return None
    allocation_rows = ScheduleAllocation.objects.select_related("source_event")
    if lock:
        allocation_rows = allocation_rows.select_for_update()
    allocation = allocation_rows.filter(
        organization_id=organization_id, reservation_id=row.pk
    ).first()
    if allocation is None:
        return None
    event = allocation.source_event
    structurally_current = (
        allocation.organization_id == row.organization_id
        and allocation.reservation_id == row.pk
        and allocation.space_id == row.space_id
        and allocation.source_revision == row.revision
        and event.organization_id == row.organization_id
        and event.event_request_id == row.event_request_id
        and event.root_reservation_id == row.root_id
    )
    ordinary_kind = {
        "provisional": "reservation_hold_created",
        "confirmed": "reservation_confirmed",
        "expired": "reservation_expired",
        "cancelled": "reservation_cancelled",
    }.get(row.status)
    ordinary_current = (
        ordinary_kind is not None
        and event.kind == ordinary_kind
        and event.reservation_id == row.pk
        and event.aggregate_revision == row.revision
    )
    predecessor = (
        None
        if row.predecessor_id is None
        else Reservation.objects.filter(
            organization_id=row.organization_id,
            pk=row.predecessor_id,
            root_id=row.root_id,
            event_request_id=row.event_request_id,
            status="rescheduled",
        ).first()
    )
    rescheduled_current = (
        event.kind == "reservation_rescheduled"
        and event.reservation_id == row.pk
        and event.successor_id == row.pk
        and event.predecessor_id == row.predecessor_id
        and predecessor is not None
        and event.aggregate_revision == predecessor.revision
        and event.new_snapshot.get("revision") == row.revision
    )
    cutover_current = (
        event.kind == "cutover_snapshot"
        and event.reservation_id == row.pk
        and event.aggregate_revision == row.revision
    )
    if not structurally_current or not (ordinary_current or rescheduled_current or cutover_current):
        return None
    return OperationsScheduleAuthorityProjection(
        organization_id=row.organization_id,
        reservation_id=row.pk,
        root_reservation_id=row.root_id,
        space_id=row.space_id,
        status=row.status,
        reservation_revision=row.revision,
        event_starts_at=row.event_interval.lower,
        event_ends_at=row.event_interval.upper,
        occupied_starts_at=allocation.occupied_interval.lower,
        occupied_ends_at=allocation.occupied_interval.upper,
        allocation_id=allocation.pk,
        allocation_source_revision=allocation.source_revision,
        source_event_id=event.pk,
        source_event_kind=event.kind,
        source_event_aggregate_revision=event.aggregate_revision,
        source_event_reservation_id=event.reservation_id,
        source_event_predecessor_id=event.predecessor_id,
        source_event_successor_id=event.successor_id,
    )


def resource_availability_context(
    authorization: TenantAuthorization, event_request_id: UUID
) -> ResourceAvailabilityContextProjection | None:
    from django.utils import timezone

    from .models import Reservation

    row = (
        Reservation.objects.filter(
            organization_id=authorization.organization_id,
            event_request_id=event_request_id,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if row is None or row.status not in (
        Reservation.Status.PROVISIONAL,
        Reservation.Status.CONFIRMED,
    ):
        return None
    if row.status == Reservation.Status.PROVISIONAL and row.hold_expires_at <= timezone.now():
        return None
    return ResourceAvailabilityContextProjection(
        event_request_id=row.event_request_id,
        reservation_id=row.pk,
        root_id=row.root_id,
        starts_at=row.event_interval.lower,
        ends_at=row.event_interval.upper,
        status=row.status,
    )


def resource_schedule(
    authorization: TenantAuthorization, reservation_id: UUID
) -> ResourceScheduleProjection | None:
    from .models import Reservation

    row = Reservation.objects.filter(
        organization_id=authorization.organization_id,
        pk=reservation_id,
    ).first()
    if row is None:
        return None
    return ResourceScheduleProjection(
        reservation_id=row.pk,
        root_id=row.root_id,
        starts_at=row.event_interval.lower,
        ends_at=row.event_interval.upper,
        status=row.status,
    )


@dataclass(frozen=True, slots=True)
class ConfirmationReadiness:
    state: str
    reservation: ReservationProjection


@dataclass(frozen=True, slots=True)
class ConfirmedReservationProjection:
    reservation: ReservationProjection
    confirmation_event_id: UUID
    confirmation_source_id: UUID
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ScheduleChangeProjection:
    event_request_id: UUID
    event_id: UUID
    kind: str
    occurred_at: datetime
    root_id: UUID
    current_reservation_id: UUID
    previous_snapshot: dict[str, Any]
    new_snapshot: dict[str, Any]
    cutover: bool


@dataclass(frozen=True, slots=True)
class ContractualScheduleProjection:
    organization_id: UUID
    event_request_id: UUID
    root_reservation_id: UUID
    current_reservation_id: UUID
    quotation_version_id: UUID
    venue_id: UUID
    space_id: UUID
    starts_at: datetime
    ends_at: datetime
    timezone_name: str
    status: str
    revision: int
    cancelled_at: datetime | None
    chain_reservation_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ReservationVenueProjection:
    reservation_id: UUID
    venue_id: UUID
    space_id: UUID
    starts_at: datetime
    ends_at: datetime
    status: str


@dataclass(frozen=True, slots=True)
class RootScheduleHistoryProjection:
    organization_id: UUID
    root_reservation_id: UUID
    reservations: tuple[ReservationVenueProjection, ...]


def root_schedule_history_for_finance(
    authorization: TenantAuthorization, root_reservation_id: UUID
) -> RootScheduleHistoryProjection:
    from .models import Reservation

    rows = tuple(
        Reservation.objects.select_related("space")
        .filter(
            organization_id=authorization.organization_id,
            root_id=root_reservation_id,
        )
        .order_by("created_at", "id")
    )
    if not rows or rows[0].root_id != root_reservation_id:
        raise SchedulingError("not_found", "La raíz de reserva no está disponible.", status=404)
    return RootScheduleHistoryProjection(
        organization_id=authorization.organization_id,
        root_reservation_id=root_reservation_id,
        reservations=tuple(
            ReservationVenueProjection(
                reservation_id=row.pk,
                venue_id=row.space.venue_id,
                space_id=row.space_id,
                starts_at=row.event_interval.lower,
                ends_at=row.event_interval.upper,
                status=row.status,
            )
            for row in rows
        ),
    )


def contractual_schedule(
    authorization: TenantAuthorization, root_reservation_id: UUID
) -> ContractualScheduleProjection:
    return contractual_schedules(authorization, (root_reservation_id,))[root_reservation_id]


def contractual_schedules(
    authorization: TenantAuthorization, root_reservation_ids: tuple[UUID, ...]
) -> dict[UUID, ContractualScheduleProjection]:
    """Proyecta varias raices con una sola consulta tenant-aware."""
    from .models import Reservation

    requested = tuple(dict.fromkeys(root_reservation_ids))
    if not requested:
        return {}
    chains: dict[UUID, list[Reservation]] = {root_id: [] for root_id in requested}
    for row in (
        Reservation.objects.select_related("space")
        .filter(
            organization_id=authorization.organization_id,
            root_id__in=requested,
        )
        .order_by("root_id", "created_at", "id")
    ):
        chains[row.root_id].append(row)
    projections: dict[UUID, ContractualScheduleProjection] = {}
    for root_id in requested:
        chain = chains[root_id]
        if not chain or chain[0].root_id != root_id:
            raise SchedulingError("not_found", "La raíz de reserva no está disponible.", status=404)
        current = chain[-1]
        projections[root_id] = ContractualScheduleProjection(
            organization_id=current.organization_id,
            event_request_id=current.event_request_id,
            root_reservation_id=current.root_id,
            current_reservation_id=current.pk,
            quotation_version_id=current.quotation_version_id,
            venue_id=current.space.venue_id,
            space_id=current.space_id,
            starts_at=current.event_interval.lower,
            ends_at=current.event_interval.upper,
            timezone_name=current.event_timezone,
            status=current.status,
            revision=current.revision,
            cancelled_at=current.cancelled_at,
            chain_reservation_ids=tuple(row.pk for row in chain),
        )
    return projections


def expire_overdue_for_organization(authorization: TenantAuthorization) -> int:
    from .services import expire_overdue_for_organization as implementation

    return implementation(authorization)


def confirmed_event_request_ids(
    authorization: TenantAuthorization, request_ids: tuple[UUID, ...]
) -> frozenset[UUID]:
    from .services import confirmed_event_request_ids as implementation

    return implementation(authorization, request_ids)


def latest_schedule_changes(
    authorization: TenantAuthorization, request_ids: tuple[UUID, ...]
) -> dict[UUID, ScheduleChangeProjection]:
    from .services import latest_schedule_changes as implementation

    return implementation(authorization, request_ids)


def schedule_changes(
    authorization: TenantAuthorization, request_ids: tuple[UUID, ...]
) -> tuple[ScheduleChangeProjection, ...]:
    from .services import schedule_changes as implementation

    return implementation(authorization, request_ids)


def create_hold_from_accepted(authorization: TenantAuthorization, evidence: Any) -> dict[str, Any]:
    from .services import create_hold_from_accepted as implementation

    return implementation(authorization, evidence)


def lock_command_spaces(authorization: TenantAuthorization, space_ids: tuple[UUID, ...]) -> None:
    """Adquiere el primer nivel del orden global antes de bloquear agregados externos."""
    from .locks import lock_spaces

    lock_spaces(authorization.organization_id, space_ids)


def reservation_for_commercial(
    authorization: TenantAuthorization, reservation_id: UUID
) -> dict[str, Any]:
    from .services import _get_reservation, reservation_data

    return reservation_data(_get_reservation(authorization.organization_id, reservation_id))


def current_reservation_for_request(
    authorization: TenantAuthorization, event_request_id: UUID
) -> dict[str, Any] | None:
    from .models import Reservation
    from .services import reservation_data

    row = (
        Reservation.objects.filter(
            organization_id=authorization.organization_id,
            event_request_id=event_request_id,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    return None if row is None else reservation_data(row)


def reservation_for_quotation(
    authorization: TenantAuthorization, quotation_version_id: UUID
) -> dict[str, Any] | None:
    from .models import Reservation
    from .services import reservation_data

    row = (
        Reservation.objects.filter(
            organization_id=authorization.organization_id,
            quotation_version_id=quotation_version_id,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    return None if row is None else reservation_data(row)


def provisional_reservation_ids(
    authorization: TenantAuthorization, event_request_id: UUID
) -> tuple[UUID, ...]:
    from .models import Reservation

    return tuple(
        Reservation.objects.filter(
            organization_id=authorization.organization_id,
            event_request_id=event_request_id,
            status=Reservation.Status.PROVISIONAL,
        ).values_list("id", flat=True)
    )


def close_provisional_hold(
    authorization: TenantAuthorization, reservation_id: UUID, *, reason: str
) -> dict[str, Any]:
    from .services import close_provisional_hold as implementation

    return implementation(authorization, reservation_id, reason=reason)


def materialize_venue_blocks_for_space(authorization: TenantAuthorization, space_id: UUID) -> int:
    from .services import materialize_venue_blocks_for_space as implementation

    return implementation(authorization, space_id)


def prepare_confirmation(
    authorization: TenantAuthorization, reservation_id: UUID
) -> ConfirmationReadiness:
    from .services import prepare_confirmation as implementation

    return implementation(authorization, reservation_id)


def confirm_prepared(
    authorization: TenantAuthorization,
    reservation_id: UUID,
    *,
    kind: str,
    recognized_amount: Any = None,
    reported_at: datetime | None = None,
    reference: str = "",
    waiver_reason: str = "",
) -> ConfirmedReservationProjection:
    from .services import confirm_prepared as implementation

    return implementation(
        authorization,
        reservation_id,
        kind=kind,
        recognized_amount=recognized_amount,
        reported_at=reported_at,
        reference=reference,
        waiver_reason=waiver_reason,
    )


def cancel_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .services import cancel_reservation

    return cancel_reservation(*args, **kwargs)


def read_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .services import read_reservation

    return read_reservation(*args, **kwargs)


def legacy_availability_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .services import legacy_availability

    return legacy_availability(*args, **kwargs)


def reschedule_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .services import reschedule_reservation

    return reschedule_reservation(*args, **kwargs)


__all__ = (
    "ReservationProjection",
    "ResourceScheduleProjection",
    "ResourceAvailabilityContextProjection",
    "OperationsScheduleAuthorityProjection",
    "ConfirmationReadiness",
    "ConfirmedReservationProjection",
    "ContractualScheduleProjection",
    "ReservationVenueProjection",
    "RootScheduleHistoryProjection",
    "ScheduleChangeProjection",
    "SchedulingError",
    "confirmed_event_request_ids",
    "contractual_schedule",
    "root_schedule_history_for_finance",
    "close_provisional_hold",
    "cancel_command",
    "confirm_prepared",
    "prepare_confirmation",
    "create_hold_from_accepted",
    "current_reservation_for_request",
    "expire_overdue_for_organization",
    "latest_schedule_changes",
    "materialize_venue_blocks_for_space",
    "legacy_availability_command",
    "provisional_reservation_ids",
    "read_command",
    "reservation_for_commercial",
    "reservation_for_quotation",
    "resource_schedule",
    "resource_availability_context",
    "schedule_authority_for_operations",
    "reschedule_command",
    "schedule_changes",
)
