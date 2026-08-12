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


def confirm_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .services import confirm_reservation

    return confirm_reservation(*args, **kwargs)


def cancel_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .services import cancel_reservation

    return cancel_reservation(*args, **kwargs)


def read_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .services import read_reservation

    return read_reservation(*args, **kwargs)


def legacy_availability_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .services import legacy_availability

    return legacy_availability(*args, **kwargs)


__all__ = (
    "ReservationProjection",
    "ScheduleChangeProjection",
    "SchedulingError",
    "confirmed_event_request_ids",
    "close_provisional_hold",
    "cancel_command",
    "confirm_command",
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
    "schedule_changes",
)
