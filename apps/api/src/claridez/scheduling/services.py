from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

from django.db import IntegrityError, connection
from django.utils import timezone
from psycopg.types.range import Range

import claridez.commercial.public as commercial_port
import claridez.operations.public as operations_port
from claridez.commercial.normalization import canonical_text, money
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.models import OrganizationSettings, Space, Venue
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from .errors import conflict, invalid, unavailable
from .locks import lock_spaces
from .models import (
    Reservation,
    ScheduleAllocation,
    ScheduleBlock,
    ScheduleBlockTarget,
    ScheduleEvent,
    SpaceSchedulePolicy,
)
from .public import (
    ConfirmationReadiness,
    ConfirmedReservationProjection,
    ReservationProjection,
    ScheduleChangeProjection,
)
from .temporal import (
    LocalInterval,
    calendar_bounds,
    canonical_range,
    local_interval,
    occupied_range,
)

HOLD_DURATION_HOURS = 48
EVENT_NAMESPACE = UUID("70f3dd5a-4684-5ef4-995f-c4fe749df32b")
APPLICABLE_CRM_EVENTS = (
    ScheduleEvent.Kind.RESERVATION_HOLD_CREATED,
    ScheduleEvent.Kind.RESERVATION_CONFIRMED,
    ScheduleEvent.Kind.RESERVATION_EXPIRED,
    ScheduleEvent.Kind.RESERVATION_RESCHEDULED,
    ScheduleEvent.Kind.RESERVATION_CANCELLED,
)


def _uuid(value: UUID | str, resource: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise unavailable(resource) from None


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _event_id(identifier: UUID, kind: str) -> UUID:
    return uuid5(EVENT_NAMESPACE, f"{identifier}:{kind}")


def _transaction_now() -> datetime:
    with connection.cursor() as cursor:
        cursor.execute("SELECT transaction_timestamp()")
        return cast(datetime, cursor.fetchone()[0])


def _snapshot(row: Reservation) -> dict[str, Any]:
    return {
        "reservation_id": str(row.pk),
        "root_id": str(row.root_id),
        "space_id": str(row.space_id),
        "starts_at": row.event_interval.lower.isoformat(),
        "ends_at": row.event_interval.upper.isoformat(),
        "timezone": row.event_timezone,
        "status": row.status,
        "revision": row.revision,
        "setup_minutes": row.setup_minutes,
        "teardown_minutes": row.teardown_minutes,
        "buffer_before_minutes": row.buffer_before_minutes,
        "buffer_after_minutes": row.buffer_after_minutes,
    }


def _range_data(value: Range[datetime] | None) -> dict[str, datetime] | None:
    if value is None:
        return None
    return {
        "starts_at": cast(datetime, value.lower),
        "ends_at": cast(datetime, value.upper),
    }


def _block_snapshot(row: ScheduleBlock) -> dict[str, Any]:
    return {
        "block_id": str(row.pk),
        "venue_id": str(row.venue_id),
        "scope": row.scope,
        "space_ids": [
            str(value)
            for value in row.targets.order_by("space_id").values_list("space_id", flat=True)
        ],
        "starts_at": row.blocked_interval.lower.isoformat(),
        "ends_at": row.blocked_interval.upper.isoformat(),
        "timezone": row.event_timezone,
        "reason": row.reason,
        "status": row.status,
        "revision": row.revision,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "termination_reason": row.termination_reason,
    }


def reservation_projection(row: Reservation) -> ReservationProjection:
    source = cast(Reservation, row.confirmation_source) if row.confirmation_source_id else row
    return ReservationProjection(
        id=row.pk,
        organization_id=row.organization_id,
        event_request_id=row.event_request_id,
        quotation_version_id=row.quotation_version_id,
        root_id=row.root_id,
        predecessor_id=row.predecessor_id,
        space_id=row.space_id,
        starts_at=row.event_interval.lower,
        ends_at=row.event_interval.upper,
        timezone_name=row.event_timezone,
        status=row.status,
        revision=row.revision,
        hold_expires_at=row.hold_expires_at,
        confirmed_at=source.confirmed_at,
    )


def reservation_data(row: Reservation) -> dict[str, Any]:
    source = cast(Reservation, row.confirmation_source) if row.confirmation_source_id else row
    return {
        "id": row.pk,
        "root_id": row.root_id,
        "predecessor_id": row.predecessor_id,
        "space_id": row.space_id,
        "status": row.status,
        "revision": row.revision,
        "starts_at": row.event_interval.lower,
        "ends_at": row.event_interval.upper,
        "event_timezone": row.event_timezone,
        "occupied_interval": (
            _range_data(row.allocation.occupied_interval) if hasattr(row, "allocation") else None
        ),
        "setup_minutes": row.setup_minutes,
        "teardown_minutes": row.teardown_minutes,
        "buffer_before_minutes": row.buffer_before_minutes,
        "buffer_after_minutes": row.buffer_after_minutes,
        "hold_expires_at": row.hold_expires_at,
        "confirmation_kind": source.confirmation_kind or None,
        "recognized_deposit_amount": source.recognized_deposit_amount,
        "deposit_reported_at": source.deposit_reported_at,
        "deposit_reference": source.deposit_reference or None,
        "confirmed_at": source.confirmed_at,
        "waiver_reason": source.waiver_reason or None,
        "waiver_authorized_at": source.waiver_authorized_at,
        "cancelled_at": row.cancelled_at,
        "cancellation_reason": row.cancellation_reason or None,
    }


def _get_reservation(
    organization_id: UUID, reservation_id: UUID | str, *, lock: bool = False
) -> Reservation:
    rows = Reservation.objects.select_related("confirmation_source", "space", "space__venue")
    if lock:
        rows = rows.select_for_update(of=("self",))
    try:
        return rows.get(organization_id=organization_id, pk=_uuid(reservation_id, "La reserva"))
    except Reservation.DoesNotExist:
        raise unavailable("La reserva") from None


def _policy(
    organization_id: UUID, space_id: UUID, *, lock: bool = False
) -> SpaceSchedulePolicy | None:
    rows = SpaceSchedulePolicy.objects.all()
    if lock:
        rows = rows.select_for_update()
    return rows.filter(organization_id=organization_id, space_id=space_id).first()


def _policy_values(row: SpaceSchedulePolicy | None) -> tuple[int, int, int, int]:
    if row is None:
        return 0, 0, 0, 0
    return (
        row.setup_minutes,
        row.teardown_minutes,
        row.buffer_before_minutes,
        row.buffer_after_minutes,
    )


def expire_for_space(authorization: TenantAuthorization, space_id: UUID) -> int:
    lock_spaces(authorization.organization_id, (space_id,))
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.claridez_scheduling_expire_for_space(%s, %s)",
            (authorization.organization_id, space_id),
        )
        return int(cursor.fetchone()[0])


def expire_overdue_for_organization(authorization: TenantAuthorization) -> int:
    spaces = tuple(
        Reservation.objects.filter(
            organization_id=authorization.organization_id,
            status=Reservation.Status.PROVISIONAL,
            hold_expires_at__lte=timezone.now(),
        )
        .order_by("space_id")
        .values_list("space_id", flat=True)
        .distinct()
    )
    return sum(expire_for_space(authorization, space_id) for space_id in spaces)


def confirmed_event_request_ids(
    authorization: TenantAuthorization, request_ids: tuple[UUID, ...]
) -> frozenset[UUID]:
    if not request_ids:
        return frozenset()
    return frozenset(
        Reservation.objects.filter(
            organization_id=authorization.organization_id,
            event_request_id__in=request_ids,
            confirmation_source_id__isnull=False,
        ).values_list("event_request_id", flat=True)
    )


def latest_schedule_changes(
    authorization: TenantAuthorization, request_ids: tuple[UUID, ...]
) -> dict[UUID, ScheduleChangeProjection]:
    if not request_ids:
        return {}
    rows = (
        ScheduleEvent.objects.filter(
            organization_id=authorization.organization_id,
            event_request_id__in=request_ids,
            kind__in=APPLICABLE_CRM_EVENTS,
        )
        .order_by("event_request_id", "-occurred_at", "-recorded_at", "-id")
        .distinct("event_request_id")
    )
    projections: dict[UUID, ScheduleChangeProjection] = {}
    for row in rows:
        if row.event_request_id is None or row.root_reservation_id is None:
            raise conflict(
                "schedule_integrity_conflict",
                "La historia de agenda no identifica su solicitud o raíz.",
            )
        current_id = row.successor_id or row.reservation_id
        if current_id is None:
            raise conflict(
                "schedule_integrity_conflict",
                "La historia de agenda no identifica la reserva vigente.",
            )
        projections[row.event_request_id] = ScheduleChangeProjection(
            event_request_id=row.event_request_id,
            event_id=row.pk,
            kind=row.kind,
            occurred_at=row.occurred_at,
            root_id=row.root_reservation_id,
            current_reservation_id=current_id,
            previous_snapshot=dict(row.previous_snapshot),
            new_snapshot=dict(row.new_snapshot),
            cutover=row.source == ScheduleEvent.Source.CUTOVER,
        )
    return projections


def schedule_changes(
    authorization: TenantAuthorization, request_ids: tuple[UUID, ...]
) -> tuple[ScheduleChangeProjection, ...]:
    if not request_ids:
        return ()
    projections = []
    rows = ScheduleEvent.objects.filter(
        organization_id=authorization.organization_id,
        event_request_id__in=request_ids,
        kind__in=APPLICABLE_CRM_EVENTS,
    ).order_by("occurred_at", "recorded_at", "id")
    for row in rows:
        if row.event_request_id is None or row.root_reservation_id is None:
            raise conflict(
                "schedule_integrity_conflict",
                "La historia de agenda no identifica su solicitud o raíz.",
            )
        current_id = row.successor_id or row.reservation_id
        if current_id is None:
            raise conflict(
                "schedule_integrity_conflict",
                "La historia de agenda no identifica la reserva vigente.",
            )
        projections.append(
            ScheduleChangeProjection(
                event_request_id=row.event_request_id,
                event_id=row.pk,
                kind=row.kind,
                occurred_at=row.occurred_at,
                root_id=row.root_reservation_id,
                current_reservation_id=current_id,
                previous_snapshot=dict(row.previous_snapshot),
                new_snapshot=dict(row.new_snapshot),
                cutover=row.source == ScheduleEvent.Source.CUTOVER,
            )
        )
    return tuple(projections)


def create_hold_from_accepted(
    authorization: TenantAuthorization,
    evidence: commercial_port.AcceptedScheduleEvidence,
) -> dict[str, Any]:
    lock_spaces(authorization.organization_id, (evidence.space_id,))
    expire_for_space(authorization, evidence.space_id)
    existing = Reservation.objects.filter(
        organization_id=authorization.organization_id,
        quotation_version_id=evidence.quotation_version_id,
        predecessor_id__isnull=True,
    ).first()
    if existing is not None:
        return reservation_data(existing)
    space = (
        Space.objects.select_for_update()
        .filter(
            organization_id=authorization.organization_id,
            pk=evidence.space_id,
            is_active=True,
            venue__is_active=True,
        )
        .first()
    )
    if space is None:
        raise unavailable("El espacio")
    policy = _policy(authorization.organization_id, space.pk, lock=True)
    setup, teardown, before, after = _policy_values(policy)
    now = _transaction_now()
    reservation_id = uuid4()
    event_id = _event_id(reservation_id, ScheduleEvent.Kind.RESERVATION_HOLD_CREATED)
    try:
        reservation = Reservation.objects.create(
            id=reservation_id,
            organization_id=authorization.organization_id,
            event_request_id=evidence.event_request_id,
            quotation_version_id=evidence.quotation_version_id,
            space=space,
            root_id=reservation_id,
            predecessor_id=None,
            confirmation_source_id=None,
            event_interval=canonical_range(evidence.starts_at, evidence.ends_at),
            event_timezone=evidence.timezone_name,
            setup_minutes=setup,
            teardown_minutes=teardown,
            buffer_before_minutes=before,
            buffer_after_minutes=after,
            status=Reservation.Status.PROVISIONAL,
            revision=1,
            hold_expires_at=now + timedelta(hours=HOLD_DURATION_HOURS),
        )
        snapshot = _snapshot(reservation)
        event = ScheduleEvent.objects.create(
            id=event_id,
            organization_id=authorization.organization_id,
            kind=ScheduleEvent.Kind.RESERVATION_HOLD_CREATED,
            source=ScheduleEvent.Source.USER,
            actor_membership_id=authorization.membership_id,
            event_request_id=reservation.event_request_id,
            root_reservation_id=reservation.pk,
            reservation_id=reservation.pk,
            aggregate_revision=1,
            previous_snapshot={},
            new_snapshot=snapshot,
            idempotency_key=event_id,
            payload_hash=_hash(snapshot),
            occurred_at=now,
        )
        ScheduleAllocation.objects.create(
            organization_id=authorization.organization_id,
            space=space,
            reservation_id=reservation.pk,
            occupied_interval=occupied_range(
                evidence.starts_at,
                evidence.ends_at,
                setup_minutes=setup,
                teardown_minutes=teardown,
                buffer_before_minutes=before,
                buffer_after_minutes=after,
            ),
            source_revision=1,
            source_event=event,
            is_blocking=True,
        )
    except IntegrityError as error:
        raise conflict("availability_conflict", "El espacio ya no está disponible.") from error
    return reservation_data(reservation)


def read_reservation(
    actor: User, organization_reference: UUID | str, *, reservation_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(actor, organization_reference, Capability.SALES_READ) as auth:
        expire_overdue_for_organization(auth)
        return reservation_data(_get_reservation(auth.organization_id, reservation_id))


def _confirm_locked(
    auth: TenantAuthorization,
    row: Reservation,
    *,
    kind: str,
    recognized_amount: Decimal | None = None,
    reported_at: datetime | None = None,
    reference: str = "",
    waiver_reason: str = "",
) -> dict[str, Any]:
    now = _transaction_now()
    if kind == Reservation.ConfirmationKind.EXTERNAL_DEPOSIT:
        if recognized_amount is None or reported_at is None:
            raise invalid("El monto y la fecha informada son obligatorios.")
        amount = money(recognized_amount)
        if amount <= 0:
            raise invalid("El monto reconocido debe ser mayor que cero.")
        if reported_at.tzinfo is None:
            raise invalid("La fecha informada debe incluir zona horaria.")
        row.recognized_deposit_amount = amount
        row.deposit_reported_at = reported_at
        row.deposit_reference = canonical_text(reference, field="La referencia", max_length=300)
    elif kind == Reservation.ConfirmationKind.WAIVER:
        auth.require(Capability.RESERVATION_WAIVE_DEPOSIT)
        row.waiver_reason = canonical_text(
            waiver_reason, field="La razón de excepción", max_length=500
        )
        row.waiver_authorized_at = now
        row.waiver_authorized_by_membership_id = auth.membership_id
    else:
        raise invalid("El tipo de confirmación no es válido.")
    previous = _snapshot(row)
    row.status = Reservation.Status.CONFIRMED
    row.confirmation_kind = kind
    row.confirmed_at = now
    row.confirmed_by_membership_id = auth.membership_id
    row.confirmation_source_id = row.pk
    row.revision += 1
    row.save()
    event_id = _event_id(row.pk, ScheduleEvent.Kind.RESERVATION_CONFIRMED)
    event = ScheduleEvent.objects.create(
        id=event_id,
        organization_id=auth.organization_id,
        kind=ScheduleEvent.Kind.RESERVATION_CONFIRMED,
        source=ScheduleEvent.Source.USER,
        actor_membership_id=auth.membership_id,
        event_request_id=row.event_request_id,
        root_reservation_id=row.root_id,
        reservation_id=row.pk,
        aggregate_revision=row.revision,
        previous_snapshot=previous,
        new_snapshot=_snapshot(row),
        idempotency_key=event_id,
        payload_hash=_hash({"kind": kind}),
        occurred_at=now,
    )
    allocation = ScheduleAllocation.objects.select_for_update().get(
        organization_id=auth.organization_id, reservation_id=row.pk
    )
    allocation.source_revision = row.revision
    allocation.source_event = event
    allocation.save(update_fields=["source_revision", "source_event", "updated_at"])
    row.refresh_from_db()
    return reservation_data(row)


def prepare_confirmation(
    auth: TenantAuthorization, reservation_id: UUID | str
) -> ConfirmationReadiness:
    candidate = _get_reservation(auth.organization_id, reservation_id)
    lock_spaces(auth.organization_id, (candidate.space_id,))
    expire_for_space(auth, candidate.space_id)
    row = _get_reservation(auth.organization_id, reservation_id, lock=True)
    if row.status == Reservation.Status.CONFIRMED:
        return ConfirmationReadiness("already_confirmed", reservation_projection(row))
    if row.status == Reservation.Status.EXPIRED or row.hold_expires_at <= _transaction_now():
        expire_for_space(auth, row.space_id)
        row.refresh_from_db()
        return ConfirmationReadiness("expired", reservation_projection(row))
    if row.status != Reservation.Status.PROVISIONAL:
        raise conflict("invalid_transition", "La reserva ya no puede confirmarse.")
    return ConfirmationReadiness("ready", reservation_projection(row))


def confirm_prepared(
    auth: TenantAuthorization,
    reservation_id: UUID | str,
    *,
    kind: str,
    recognized_amount: Decimal | None = None,
    reported_at: datetime | None = None,
    reference: str = "",
    waiver_reason: str = "",
) -> ConfirmedReservationProjection:
    row = _get_reservation(auth.organization_id, reservation_id, lock=True)
    if row.status != Reservation.Status.PROVISIONAL:
        raise conflict("invalid_transition", "La reserva ya no puede confirmarse.")
    data = _confirm_locked(
        auth,
        row,
        kind=kind,
        recognized_amount=recognized_amount,
        reported_at=reported_at,
        reference=reference,
        waiver_reason=waiver_reason,
    )
    event_id = _event_id(row.pk, ScheduleEvent.Kind.RESERVATION_CONFIRMED)
    return ConfirmedReservationProjection(
        reservation=reservation_projection(row),
        confirmation_event_id=event_id,
        confirmation_source_id=row.pk,
        data=data,
    )


def cancel_reservation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    reason: str,
) -> dict[str, Any]:
    expired = False
    result: dict[str, Any] | None = None
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESERVATION_CANCEL
    ) as auth:
        candidate = _get_reservation(auth.organization_id, reservation_id)
        lock_spaces(auth.organization_id, (candidate.space_id,))
        expire_for_space(auth, candidate.space_id)
        row = _get_reservation(auth.organization_id, reservation_id, lock=True)
        if row.status == Reservation.Status.CANCELLED:
            return reservation_data(row)
        if row.status == Reservation.Status.EXPIRED:
            expired = True
        elif row.status not in {Reservation.Status.PROVISIONAL, Reservation.Status.CONFIRMED}:
            raise conflict("invalid_transition", "La reserva ya no puede cancelarse.")
        elif row.status == Reservation.Status.PROVISIONAL and (
            row.hold_expires_at <= _transaction_now()
        ):
            expire_for_space(auth, row.space_id)
            expired = True
        else:
            canonical_reason = canonical_text(
                reason, field="La razón de cancelación", max_length=500
            )
            previous = _snapshot(row)
            was_confirmed = row.status == Reservation.Status.CONFIRMED
            now = _transaction_now()
            row.status = Reservation.Status.CANCELLED
            row.cancelled_at = now
            row.cancelled_by_membership_id = auth.membership_id
            row.cancellation_reason = canonical_reason
            row.revision += 1
            row.save()
            if was_confirmed:
                try:
                    operations_port.cancel_for_schedule(
                        auth.organization_id,
                        row.pk,
                        actor_membership_id=auth.membership_id,
                        occurred_at=now,
                    )
                except operations_port.OperationsError as error:
                    raise conflict(error.code, error.message) from error
            event_id = _event_id(row.pk, ScheduleEvent.Kind.RESERVATION_CANCELLED)
            event = ScheduleEvent.objects.create(
                id=event_id,
                organization_id=auth.organization_id,
                kind=ScheduleEvent.Kind.RESERVATION_CANCELLED,
                source=ScheduleEvent.Source.USER,
                actor_membership_id=auth.membership_id,
                reason=canonical_reason,
                event_request_id=row.event_request_id,
                root_reservation_id=row.root_id,
                reservation_id=row.pk,
                aggregate_revision=row.revision,
                previous_snapshot=previous,
                new_snapshot=_snapshot(row),
                idempotency_key=event_id,
                payload_hash=_hash({"reason": canonical_reason}),
                occurred_at=now,
            )
            allocation = ScheduleAllocation.objects.select_for_update().get(reservation_id=row.pk)
            allocation.is_blocking = False
            allocation.source_revision = row.revision
            allocation.source_event = event
            allocation.save(
                update_fields=["is_blocking", "source_revision", "source_event", "updated_at"]
            )
            commercial_port.set_request_schedule_status(
                auth,
                row.event_request_id,
                status="cancelled" if was_confirmed else "closed_lost",
                closed_at=now,
                closed_reason=canonical_reason,
            )
            result = reservation_data(row)
    if expired:
        raise conflict("hold_expired", "La reserva provisional venció.")
    if result is None:
        raise conflict("schedule_integrity_conflict", "La cancelación no produjo un resultado.")
    return result


def close_provisional_hold(
    authorization: TenantAuthorization,
    reservation_id: UUID,
    *,
    reason: str,
) -> dict[str, Any]:
    candidate = _get_reservation(authorization.organization_id, reservation_id)
    lock_spaces(authorization.organization_id, (candidate.space_id,))
    expire_for_space(authorization, candidate.space_id)
    row = _get_reservation(authorization.organization_id, reservation_id, lock=True)
    if row.status == Reservation.Status.CANCELLED:
        return reservation_data(row)
    if row.status != Reservation.Status.PROVISIONAL:
        raise conflict("invalid_transition", "El hold no puede cerrarse desde la solicitud.")
    canonical_reason = canonical_text(reason, field="La razón", max_length=500)
    previous = _snapshot(row)
    now = _transaction_now()
    row.status = Reservation.Status.CANCELLED
    row.cancelled_at = now
    row.cancelled_by_membership_id = authorization.membership_id
    row.cancellation_reason = canonical_reason
    row.revision += 1
    row.save()
    event_id = _event_id(row.pk, ScheduleEvent.Kind.RESERVATION_CANCELLED)
    event = ScheduleEvent.objects.create(
        id=event_id,
        organization_id=authorization.organization_id,
        kind=ScheduleEvent.Kind.RESERVATION_CANCELLED,
        source=ScheduleEvent.Source.USER,
        actor_membership_id=authorization.membership_id,
        reason=canonical_reason,
        event_request_id=row.event_request_id,
        root_reservation_id=row.root_id,
        reservation_id=row.pk,
        aggregate_revision=row.revision,
        previous_snapshot=previous,
        new_snapshot=_snapshot(row),
        idempotency_key=event_id,
        payload_hash=_hash({"reason": canonical_reason}),
        occurred_at=now,
    )
    allocation = ScheduleAllocation.objects.select_for_update().get(reservation_id=row.pk)
    allocation.is_blocking = False
    allocation.source_revision = row.revision
    allocation.source_event = event
    allocation.save()
    return reservation_data(row)


def update_policy(
    actor: User,
    organization_reference: UUID | str,
    *,
    space_id: UUID | str,
    revision: int,
    setup_minutes: int,
    teardown_minutes: int,
    buffer_before_minutes: int,
    buffer_after_minutes: int,
) -> dict[str, Any]:
    with authorized_tenant_scope(actor, organization_reference, Capability.VENUE_MANAGE) as auth:
        auth.require(Capability.SCHEDULE_BLOCK)
        identifier = _uuid(space_id, "El espacio")
        lock_spaces(auth.organization_id, (identifier,))
        space = (
            Space.objects.select_for_update()
            .filter(organization_id=auth.organization_id, pk=identifier)
            .first()
        )
        if space is None:
            raise unavailable("El espacio")
        values = (setup_minutes, teardown_minutes, buffer_before_minutes, buffer_after_minutes)
        if any(value < 0 for value in values):
            raise invalid("Las duraciones no pueden ser negativas.")
        row = _policy(auth.organization_id, identifier, lock=True)
        if row is None:
            if revision not in {0, 1}:
                raise conflict("stale_revision", "La política cambió; vuelve a cargarla.")
            row = SpaceSchedulePolicy.objects.create(
                organization_id=auth.organization_id,
                space=space,
                setup_minutes=setup_minutes,
                teardown_minutes=teardown_minutes,
                buffer_before_minutes=buffer_before_minutes,
                buffer_after_minutes=buffer_after_minutes,
                revision=1,
            )
        else:
            if row.revision != revision:
                raise conflict("stale_revision", "La política cambió; vuelve a cargarla.")
            row.setup_minutes = setup_minutes
            row.teardown_minutes = teardown_minutes
            row.buffer_before_minutes = buffer_before_minutes
            row.buffer_after_minutes = buffer_after_minutes
            row.revision += 1
            row.save()
        return policy_data(row)


def policy_data(row: SpaceSchedulePolicy | None, *, space_id: UUID | None = None) -> dict[str, Any]:
    if row is None:
        return {
            "space_id": space_id,
            "setup_minutes": 0,
            "teardown_minutes": 0,
            "buffer_before_minutes": 0,
            "buffer_after_minutes": 0,
            "revision": 0,
        }
    return {
        "space_id": row.space_id,
        "setup_minutes": row.setup_minutes,
        "teardown_minutes": row.teardown_minutes,
        "buffer_before_minutes": row.buffer_before_minutes,
        "buffer_after_minutes": row.buffer_after_minutes,
        "revision": row.revision,
    }


def read_policy(
    actor: User, organization_reference: UUID | str, *, space_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.AVAILABILITY_READ
    ) as auth:
        identifier = _uuid(space_id, "El espacio")
        if not Space.objects.filter(organization_id=auth.organization_id, pk=identifier).exists():
            raise unavailable("El espacio")
        return policy_data(_policy(auth.organization_id, identifier), space_id=identifier)


def availability(
    actor: User,
    organization_reference: UUID | str,
    *,
    starts_at_local: datetime,
    ends_at_local: datetime,
    timezone_name: str,
    space_ids: tuple[UUID, ...],
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.AVAILABILITY_READ
    ) as auth:
        settings = OrganizationSettings.objects.get(organization_id=auth.organization_id)
        if settings.timezone != timezone_name:
            raise conflict(
                "organization_timezone_changed", "La zona horaria de la organización cambió."
            )
        interval = local_interval(starts_at_local, ends_at_local, timezone_name)
        canonical_ids = tuple(sorted(set(space_ids), key=str))
        if not canonical_ids:
            raise invalid("Debe seleccionar al menos un espacio.")
        spaces = {
            row.pk: row
            for row in Space.objects.select_related("venue").filter(
                organization_id=auth.organization_id,
                pk__in=canonical_ids,
                is_active=True,
                venue__is_active=True,
            )
        }
        if len(spaces) != len(canonical_ids):
            raise unavailable("El espacio")
        results = []
        for identifier in canonical_ids:
            expire_for_space(auth, identifier)
            policy = _policy(auth.organization_id, identifier)
            setup, teardown, before, after = _policy_values(policy)
            candidate = occupied_range(
                interval.starts_at,
                interval.ends_at,
                setup_minutes=setup,
                teardown_minutes=teardown,
                buffer_before_minutes=before,
                buffer_after_minutes=after,
            )
            conflicts = ScheduleAllocation.objects.filter(
                organization_id=auth.organization_id,
                space_id=identifier,
                is_blocking=True,
                occupied_interval__overlap=candidate,
            ).values("occupied_interval", "reservation_id", "block_target_id")
            minimal = tuple(
                {
                    "type": "block" if item["block_target_id"] else "reservation",
                    "occupied_interval": _range_data(item["occupied_interval"]),
                }
                for item in conflicts
            )
            results.append(
                {
                    "space_id": identifier,
                    "available": not minimal,
                    "occupied_interval": _range_data(candidate),
                    "policy": policy_data(policy, space_id=identifier),
                    "conflicts": minimal,
                }
            )
        return {
            "starts_at": interval.starts_at,
            "ends_at": interval.ends_at,
            "timezone": timezone_name,
            "spaces": tuple(results),
        }


def legacy_availability(
    actor: User,
    organization_reference: UUID | str,
    *,
    space_id: UUID | str,
    starts_at: datetime,
    ends_at: datetime,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.AVAILABILITY_READ
    ) as auth:
        identifier = _uuid(space_id, "El espacio")
        if starts_at.tzinfo is None or ends_at.tzinfo is None or starts_at >= ends_at:
            raise invalid("El intervalo no es válido.")
        space = (
            Space.objects.select_related("venue")
            .filter(
                organization_id=auth.organization_id,
                pk=identifier,
                is_active=True,
                venue__is_active=True,
            )
            .first()
        )
        if space is None:
            raise unavailable("El espacio")
        expire_for_space(auth, identifier)
        candidate = canonical_range(starts_at, ends_at)
        allocations = ScheduleAllocation.objects.filter(
            organization_id=auth.organization_id,
            space_id=identifier,
            is_blocking=True,
            occupied_interval__overlap=candidate,
        ).select_related("reservation", "block_target__block")
        blocks = []
        for allocation in allocations.order_by("occupied_interval", "id"):
            if allocation.reservation_id:
                reservation = cast(Reservation, allocation.reservation)
                item = reservation_data(reservation)
                item["event_request_id"] = reservation.event_request_id
                item["event_type"] = "reservation"
            else:
                target = cast(ScheduleBlockTarget, allocation.block_target)
                item = {
                    "id": target.block_id,
                    "status": target.block.status,
                    "starts_at": allocation.occupied_interval.lower,
                    "ends_at": allocation.occupied_interval.upper,
                    "event_type": "block",
                }
            blocks.append(item)
        return {
            "space": {
                "id": space.pk,
                "name": space.name,
                "venue_id": space.venue_id,
                "venue_name": space.venue.name,
            },
            "from": starts_at,
            "to": ends_at,
            "available": not blocks,
            "blocks": tuple(blocks),
        }


def create_block(
    actor: User,
    organization_reference: UUID | str,
    *,
    idempotency_key: UUID,
    scope: str,
    venue_id: UUID,
    space_ids: tuple[UUID, ...],
    starts_at_local: datetime,
    ends_at_local: datetime,
    timezone_name: str,
    reason: str,
) -> tuple[dict[str, Any], bool]:
    with authorized_tenant_scope(actor, organization_reference, Capability.SCHEDULE_BLOCK) as auth:
        auth.require(Capability.AVAILABILITY_READ)
        canonical_reason = canonical_text(reason, field="La razón", max_length=500)
        settings = OrganizationSettings.objects.get(organization_id=auth.organization_id)
        if settings.timezone != timezone_name:
            raise conflict(
                "organization_timezone_changed", "La zona horaria de la organización cambió."
            )
        interval = local_interval(starts_at_local, ends_at_local, timezone_name)
        venue = (
            Venue.objects.select_for_update()
            .filter(organization_id=auth.organization_id, pk=venue_id, is_active=True)
            .first()
        )
        if venue is None:
            raise unavailable("La sede")
        if scope == ScheduleBlock.Scope.VENUE:
            identifiers = tuple(
                Space.objects.filter(
                    organization_id=auth.organization_id, venue=venue, is_active=True
                )
                .order_by("id")
                .values_list("id", flat=True)
            )
        elif scope == ScheduleBlock.Scope.SPACES:
            identifiers = tuple(sorted(set(space_ids), key=str))
        else:
            raise invalid("El alcance del bloqueo no es válido.")
        if not identifiers:
            raise invalid("El bloqueo debe afectar al menos un espacio.")
        if Space.objects.filter(
            organization_id=auth.organization_id, venue=venue, pk__in=identifiers, is_active=True
        ).count() != len(identifiers):
            raise unavailable("El espacio")
        payload = {
            "scope": scope,
            "venue_id": str(venue_id),
            "space_ids": [str(value) for value in identifiers],
            "starts_at": interval.starts_at.isoformat(),
            "ends_at": interval.ends_at.isoformat(),
            "timezone": timezone_name,
            "reason": canonical_reason,
        }
        payload_hash = _hash(payload)
        replay = (
            ScheduleEvent.objects.filter(
                organization_id=auth.organization_id,
                kind=ScheduleEvent.Kind.BLOCK_CREATED,
                idempotency_key=idempotency_key,
            )
            .select_related("block")
            .first()
        )
        if replay is not None:
            if replay.payload_hash != payload_hash:
                raise conflict("idempotency_conflict", "La clave ya fue usada con otro contenido.")
            return block_data(cast(ScheduleBlock, replay.block)), False
        lock_spaces(auth.organization_id, identifiers)
        for identifier in identifiers:
            expire_for_space(auth, identifier)
        now = _transaction_now()
        block = ScheduleBlock.objects.create(
            organization_id=auth.organization_id,
            venue=venue,
            scope=scope,
            blocked_interval=canonical_range(interval.starts_at, interval.ends_at),
            event_timezone=timezone_name,
            reason=canonical_reason,
            status=ScheduleBlock.Status.ACTIVE,
            revision=1,
            created_by_membership_id=auth.membership_id,
        )
        event = ScheduleEvent.objects.create(
            organization_id=auth.organization_id,
            kind=ScheduleEvent.Kind.BLOCK_CREATED,
            source=ScheduleEvent.Source.USER,
            actor_membership_id=auth.membership_id,
            reason=canonical_reason,
            block=block,
            aggregate_revision=1,
            previous_snapshot={},
            new_snapshot=payload,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            occurred_at=now,
        )
        try:
            for identifier in identifiers:
                target = ScheduleBlockTarget.objects.create(
                    organization_id=auth.organization_id,
                    block=block,
                    space_id=identifier,
                )
                ScheduleAllocation.objects.create(
                    organization_id=auth.organization_id,
                    space_id=identifier,
                    block_target=target,
                    occupied_interval=block.blocked_interval,
                    source_revision=1,
                    source_event=event,
                    is_blocking=True,
                )
        except IntegrityError as error:
            raise conflict(
                "availability_conflict", "El bloqueo se superpone con otra ocupación."
            ) from error
        return block_data(block), True


def materialize_venue_blocks_for_space(authorization: TenantAuthorization, space_id: UUID) -> int:
    space = Space.objects.select_related("venue").get(
        organization_id=authorization.organization_id, pk=space_id, is_active=True
    )
    lock_spaces(authorization.organization_id, (space.pk,))
    blocks = list(
        ScheduleBlock.objects.select_for_update()
        .filter(
            organization_id=authorization.organization_id,
            venue_id=space.venue_id,
            scope=ScheduleBlock.Scope.VENUE,
            status=ScheduleBlock.Status.ACTIVE,
        )
        .order_by("id")
    )
    created = 0
    for block in blocks:
        if ScheduleBlockTarget.objects.filter(
            organization_id=authorization.organization_id, block=block, space=space
        ).exists():
            continue
        source_event = ScheduleEvent.objects.get(
            organization_id=authorization.organization_id,
            block=block,
            kind=ScheduleEvent.Kind.BLOCK_CREATED,
        )
        try:
            target = ScheduleBlockTarget.objects.create(
                organization_id=authorization.organization_id,
                block=block,
                space=space,
            )
            ScheduleAllocation.objects.create(
                organization_id=authorization.organization_id,
                space=space,
                block_target=target,
                occupied_interval=block.blocked_interval,
                source_revision=block.revision,
                source_event=source_event,
                is_blocking=True,
            )
        except IntegrityError as error:
            raise conflict(
                "availability_conflict",
                "El espacio nuevo entra en conflicto con un cierre vigente de la sede.",
            ) from error
        created += 1
    return created


def block_data(row: ScheduleBlock) -> dict[str, Any]:
    return {
        "id": row.pk,
        "venue_id": row.venue_id,
        "scope": row.scope,
        "space_ids": tuple(row.targets.order_by("space_id").values_list("space_id", flat=True)),
        "starts_at": row.blocked_interval.lower,
        "ends_at": row.blocked_interval.upper,
        "event_timezone": row.event_timezone,
        "reason": row.reason,
        "status": row.status,
        "revision": row.revision,
        "ended_at": row.ended_at,
        "termination_reason": row.termination_reason or None,
    }


def terminate_block(
    actor: User,
    organization_reference: UUID | str,
    *,
    block_id: UUID | str,
    revision: int,
    reason: str,
    action: str,
) -> dict[str, Any]:
    with authorized_tenant_scope(actor, organization_reference, Capability.SCHEDULE_BLOCK) as auth:
        auth.require(Capability.AVAILABILITY_READ)
        row = ScheduleBlock.objects.filter(
            organization_id=auth.organization_id, pk=_uuid(block_id, "El bloqueo")
        ).first()
        if row is None:
            raise unavailable("El bloqueo")
        identifiers = tuple(row.targets.order_by("space_id").values_list("space_id", flat=True))
        lock_spaces(auth.organization_id, identifiers)
        row = ScheduleBlock.objects.select_for_update().get(pk=row.pk)
        target_status = (
            ScheduleBlock.Status.RELEASED if action == "release" else ScheduleBlock.Status.CANCELLED
        )
        if row.status == target_status:
            return block_data(row)
        if row.status != ScheduleBlock.Status.ACTIVE:
            raise conflict("invalid_transition", "El bloqueo ya terminó con otra acción.")
        if row.revision != revision:
            raise conflict("stale_revision", "El bloqueo cambió; vuelve a cargarlo.")
        now = _transaction_now()
        if target_status == ScheduleBlock.Status.CANCELLED and row.blocked_interval.lower <= now:
            raise conflict("invalid_transition", "Un bloqueo iniciado solo puede liberarse.")
        canonical_reason = canonical_text(reason, field="La razón", max_length=500)
        previous = _block_snapshot(row)
        row.status = target_status
        row.ended_at = now
        row.ended_by_membership_id = auth.membership_id
        row.termination_reason = canonical_reason
        row.revision += 1
        row.save()
        kind = (
            ScheduleEvent.Kind.BLOCK_RELEASED
            if target_status == ScheduleBlock.Status.RELEASED
            else ScheduleEvent.Kind.BLOCK_CANCELLED
        )
        event_id = _event_id(row.pk, kind)
        event = ScheduleEvent.objects.create(
            id=event_id,
            organization_id=auth.organization_id,
            kind=kind,
            source=ScheduleEvent.Source.USER,
            actor_membership_id=auth.membership_id,
            reason=canonical_reason,
            block=row,
            aggregate_revision=row.revision,
            previous_snapshot=previous,
            new_snapshot=_block_snapshot(row),
            idempotency_key=event_id,
            payload_hash=_hash({"reason": canonical_reason}),
            occurred_at=now,
        )
        ScheduleAllocation.objects.filter(
            organization_id=auth.organization_id, block_target__block=row
        ).update(
            is_blocking=False,
            source_revision=row.revision,
            source_event=event,
            updated_at=now,
        )
        return block_data(row)


def _perform_reschedule_locked(
    auth: TenantAuthorization,
    row: Reservation,
    root: Reservation,
    destination: Space,
    interval: LocalInterval,
    *,
    timezone_name: str,
    canonical_reason: str,
    idempotency_key: UUID,
    payload_hash: str,
    carry_free_item_ids: tuple[UUID, ...],
    carry_resource_assignment_ids: tuple[UUID, ...],
) -> dict[str, Any]:
    policy = _policy(auth.organization_id, destination.pk, lock=True)
    setup, teardown, before, after = _policy_values(policy)
    occupied = occupied_range(
        interval.starts_at,
        interval.ends_at,
        setup_minutes=setup,
        teardown_minutes=teardown,
        buffer_before_minutes=before,
        buffer_after_minutes=after,
    )
    existing_conflict = (
        ScheduleAllocation.objects.filter(
            organization_id=auth.organization_id,
            space=destination,
            is_blocking=True,
            occupied_interval__overlap=occupied,
        )
        .exclude(reservation_id=row.pk)
        .exists()
    )
    if existing_conflict:
        raise conflict("availability_conflict", "El destino ya no está disponible.")
    previous_snapshot = _snapshot(row)
    now = _transaction_now()
    successor_id = uuid4()
    successor_status = row.status
    confirmation_source_id = (
        row.confirmation_source_id or row.pk
        if successor_status == Reservation.Status.CONFIRMED
        else None
    )
    row.status = Reservation.Status.RESCHEDULED
    row.revision += 1
    row.save(update_fields=["status", "revision", "updated_at"])
    successor = Reservation.objects.create(
        id=successor_id,
        organization_id=auth.organization_id,
        event_request_id=row.event_request_id,
        quotation_version_id=row.quotation_version_id,
        space=destination,
        root=root,
        predecessor=row,
        confirmation_source_id=confirmation_source_id,
        event_interval=canonical_range(interval.starts_at, interval.ends_at),
        event_timezone=timezone_name,
        setup_minutes=setup,
        teardown_minutes=teardown,
        buffer_before_minutes=before,
        buffer_after_minutes=after,
        status=successor_status,
        revision=1,
        hold_expires_at=row.hold_expires_at,
    )
    successor_snapshot = _snapshot(successor)
    carried_ids: tuple[UUID, ...] = ()
    if successor.status == Reservation.Status.CONFIRMED:
        try:
            _, _, carried_ids = operations_port.reschedule_preparation(
                reservation_projection(row),
                reservation_projection(successor),
                actor_membership_id=auth.membership_id,
                occurred_at=now,
                carry_free_item_ids=carry_free_item_ids,
            )
        except operations_port.OperationsError as error:
            raise conflict(error.code, error.message) from error
    event_snapshot = {
        **successor_snapshot,
        "carried_item_ids": [str(value) for value in carried_ids],
        "requested_resource_assignment_ids": [
            str(value) for value in carry_resource_assignment_ids
        ],
    }
    event = ScheduleEvent.objects.create(
        organization_id=auth.organization_id,
        kind=ScheduleEvent.Kind.RESERVATION_RESCHEDULED,
        source=ScheduleEvent.Source.USER,
        actor_membership_id=auth.membership_id,
        reason=canonical_reason,
        event_request_id=row.event_request_id,
        root_reservation_id=root.pk,
        reservation_id=successor.pk,
        predecessor_id=row.pk,
        successor_id=successor.pk,
        aggregate_revision=row.revision,
        previous_snapshot=previous_snapshot,
        new_snapshot=event_snapshot,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        occurred_at=now,
    )
    previous_allocation = ScheduleAllocation.objects.select_for_update().get(reservation_id=row.pk)
    previous_allocation.is_blocking = False
    previous_allocation.source_revision = row.revision
    previous_allocation.source_event = event
    previous_allocation.save()
    ScheduleAllocation.objects.create(
        organization_id=auth.organization_id,
        space=destination,
        reservation=successor,
        occupied_interval=occupied,
        source_revision=successor.revision,
        source_event=event,
        is_blocking=True,
    )
    return {
        "previous": previous_snapshot,
        "reservation": reservation_data(successor),
        "carried_item_ids": carried_ids,
        "carried_resource_assignment_ids": (),
    }


def reschedule_reservation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    revision: int,
    idempotency_key: UUID,
    space_id: UUID,
    starts_at_local: datetime,
    ends_at_local: datetime,
    timezone_name: str,
    reason: str,
    commercial_terms_unchanged: bool,
    carry_free_item_ids: tuple[UUID, ...] = (),
    carry_resource_assignment_ids: tuple[UUID, ...] = (),
) -> dict[str, Any]:
    expired = False
    result: dict[str, Any] | None = None
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESERVATION_RESCHEDULE
    ) as auth:
        auth.require(Capability.SALES_MANAGE)
        if not commercial_terms_unchanged:
            raise invalid("Debe confirmar que las condiciones comerciales no cambian.")
        canonical_reason = canonical_text(reason, field="La razón", max_length=500)
        settings = OrganizationSettings.objects.get(organization_id=auth.organization_id)
        if settings.timezone != timezone_name:
            raise conflict(
                "organization_timezone_changed", "La zona horaria de la organización cambió."
            )
        interval = local_interval(starts_at_local, ends_at_local, timezone_name)
        candidate = _get_reservation(auth.organization_id, reservation_id)
        payload = {
            "reservation_id": str(candidate.pk),
            "revision": revision,
            "space_id": str(space_id),
            "starts_at": interval.starts_at.isoformat(),
            "ends_at": interval.ends_at.isoformat(),
            "timezone": timezone_name,
            "reason": canonical_reason,
            "commercial_terms_unchanged": True,
            "carry_free_item_ids": sorted(str(value) for value in carry_free_item_ids),
            "carry_resource_assignment_ids": sorted(
                str(value) for value in carry_resource_assignment_ids
            ),
        }
        payload_hash = _hash(payload)
        replay = (
            ScheduleEvent.objects.filter(
                organization_id=auth.organization_id,
                kind=ScheduleEvent.Kind.RESERVATION_RESCHEDULED,
                idempotency_key=idempotency_key,
            )
            .select_related("successor")
            .first()
        )
        if replay is not None:
            if replay.payload_hash != payload_hash:
                raise conflict("idempotency_conflict", "La clave ya fue usada con otro contenido.")
            successor = cast(Reservation, replay.successor)
            return {
                "previous": replay.previous_snapshot,
                "reservation": reservation_data(successor),
                "carried_item_ids": tuple(replay.new_snapshot.get("carried_item_ids", ())),
                "carried_resource_assignment_ids": (),
            }
        destination = Space.objects.filter(
            organization_id=auth.organization_id,
            pk=space_id,
            is_active=True,
            venue__is_active=True,
        ).first()
        if destination is None:
            raise unavailable("El espacio")
        lock_spaces(auth.organization_id, (candidate.space_id, destination.pk))
        expire_for_space(auth, candidate.space_id)
        if destination.pk != candidate.space_id:
            expire_for_space(auth, destination.pk)
        replay = (
            ScheduleEvent.objects.filter(
                organization_id=auth.organization_id,
                kind=ScheduleEvent.Kind.RESERVATION_RESCHEDULED,
                idempotency_key=idempotency_key,
            )
            .select_related("successor")
            .first()
        )
        if replay is not None:
            if replay.payload_hash != payload_hash:
                raise conflict("idempotency_conflict", "La clave ya fue usada con otro contenido.")
            successor = cast(Reservation, replay.successor)
            return {
                "previous": replay.previous_snapshot,
                "reservation": reservation_data(successor),
                "carried_item_ids": tuple(replay.new_snapshot.get("carried_item_ids", ())),
                "carried_resource_assignment_ids": (),
            }
        root = Reservation.objects.select_for_update().get(
            organization_id=auth.organization_id, pk=candidate.root_id
        )
        row = _get_reservation(auth.organization_id, candidate.pk, lock=True)
        if row.status == Reservation.Status.EXPIRED:
            expired = True
        elif row.revision != revision:
            raise conflict("stale_revision", "La reserva cambió; vuelve a cargarla.")
        elif row.status == Reservation.Status.RESCHEDULED:
            raise conflict("already_rescheduled", "La reserva ya fue reprogramada.")
        elif row.status not in {Reservation.Status.PROVISIONAL, Reservation.Status.CONFIRMED}:
            raise conflict("invalid_transition", "La reserva no puede reprogramarse.")
        elif (
            row.status == Reservation.Status.PROVISIONAL
            and row.hold_expires_at <= _transaction_now()
        ):
            expire_for_space(auth, row.space_id)
            expired = True
        if not expired:
            result = _perform_reschedule_locked(
                auth,
                row,
                root,
                destination,
                interval,
                timezone_name=timezone_name,
                canonical_reason=canonical_reason,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                carry_free_item_ids=carry_free_item_ids,
                carry_resource_assignment_ids=carry_resource_assignment_ids,
            )
    if expired:
        raise conflict("hold_expired", "La reserva provisional venció.")
    if result is None:
        raise conflict("schedule_integrity_conflict", "La reprogramación no produjo un resultado.")
    return result


def calendar_entries(
    actor: User,
    organization_reference: UUID | str,
    *,
    view: str,
    anchor_date: date,
    venue_id: UUID | None = None,
    space_id: UUID | None = None,
    types: tuple[str, ...] = (),
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.AVAILABILITY_READ
    ) as auth:
        settings = OrganizationSettings.objects.get(organization_id=auth.organization_id)
        start, end = calendar_bounds(view, anchor_date, settings.timezone)
        expire_overdue_for_organization(auth)
        query = ScheduleAllocation.objects.select_related(
            "space", "space__venue", "reservation", "block_target__block"
        ).filter(
            organization_id=auth.organization_id,
            occupied_interval__overlap=Range(start, end, bounds="[)"),
        )
        if venue_id:
            query = query.filter(space__venue_id=venue_id)
        if space_id:
            query = query.filter(space_id=space_id)
        entries = []
        for allocation in query.order_by("space__venue__name", "space__name", "occupied_interval"):
            if allocation.reservation_id:
                reservation = cast(Reservation, allocation.reservation)
                entry_type = (
                    "hold"
                    if reservation.status == Reservation.Status.PROVISIONAL
                    else "reservation"
                )
                if types and entry_type not in types:
                    continue
                entries.append(
                    {
                        "id": reservation.pk,
                        "type": entry_type,
                        "status": reservation.status,
                        "revision": reservation.revision,
                        "root_id": reservation.root_id,
                        "space_id": allocation.space_id,
                        "space_name": allocation.space.name,
                        "venue_id": allocation.space.venue_id,
                        "venue_name": allocation.space.venue.name,
                        "starts_at": reservation.event_interval.lower,
                        "ends_at": reservation.event_interval.upper,
                        "occupied_interval": _range_data(allocation.occupied_interval),
                        "event_timezone": reservation.event_timezone,
                        "setup_minutes": reservation.setup_minutes,
                        "teardown_minutes": reservation.teardown_minutes,
                        "buffer_before_minutes": reservation.buffer_before_minutes,
                        "buffer_after_minutes": reservation.buffer_after_minutes,
                        "is_blocking": allocation.is_blocking,
                    }
                )
            else:
                target = cast(ScheduleBlockTarget, allocation.block_target)
                block = target.block
                if types and "block" not in types:
                    continue
                entries.append(
                    {
                        "id": block.pk,
                        "type": "block",
                        "status": block.status,
                        "revision": block.revision,
                        "space_id": allocation.space_id,
                        "space_name": allocation.space.name,
                        "venue_id": allocation.space.venue_id,
                        "venue_name": allocation.space.venue.name,
                        "starts_at": block.blocked_interval.lower,
                        "ends_at": block.blocked_interval.upper,
                        "occupied_interval": _range_data(allocation.occupied_interval),
                        "event_timezone": block.event_timezone,
                        "reason": block.reason,
                        "is_blocking": allocation.is_blocking,
                    }
                )
        return {
            "view": view,
            "anchor_date": anchor_date,
            "timezone": settings.timezone,
            "from": start,
            "to": end,
            "entries": tuple(entries),
        }


def list_blocks(
    actor: User,
    organization_reference: UUID | str,
    *,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    venue_id: UUID | None = None,
    space_id: UUID | None = None,
    status: str = "",
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.AVAILABILITY_READ
    ) as auth:
        rows = ScheduleBlock.objects.filter(organization_id=auth.organization_id)
        if starts_at and ends_at:
            rows = rows.filter(blocked_interval__overlap=canonical_range(starts_at, ends_at))
        if venue_id:
            rows = rows.filter(venue_id=venue_id)
        if space_id:
            rows = rows.filter(targets__space_id=space_id)
        if status:
            rows = rows.filter(status=status)
        return tuple(block_data(row) for row in rows.distinct().order_by("blocked_interval", "id"))


def schedule_history(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.AVAILABILITY_READ
    ) as auth:
        row = _get_reservation(auth.organization_id, reservation_id)
        return tuple(
            {
                "id": event.pk,
                "kind": event.kind,
                "source": event.source,
                "reason": event.reason or None,
                "actor_membership_id": event.actor_membership_id,
                "reservation_id": event.reservation_id,
                "predecessor_id": event.predecessor_id,
                "successor_id": event.successor_id,
                "aggregate_revision": event.aggregate_revision,
                "previous_snapshot": event.previous_snapshot,
                "new_snapshot": event.new_snapshot,
                "occurred_at": event.occurred_at,
                "recorded_at": event.recorded_at,
            }
            for event in ScheduleEvent.objects.filter(
                organization_id=auth.organization_id, root_reservation_id=row.root_id
            ).order_by("occurred_at", "recorded_at", "id")
        )


def scheduling_capabilities(actor: User, organization_reference: UUID | str) -> tuple[str, ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.ORGANIZATION_ACCESS
    ) as auth:
        allowed = capabilities_for_role(auth.role)
        relevant = (
            Capability.AVAILABILITY_READ,
            Capability.SCHEDULE_BLOCK,
            Capability.RESERVATION_RESCHEDULE,
            Capability.SCHEDULE_EXPORT,
            Capability.RESERVATION_CONFIRM,
            Capability.RESERVATION_CANCEL,
            Capability.RESERVATION_WAIVE_DEPOSIT,
            Capability.VENUE_MANAGE,
            Capability.OPERATION_MANAGE,
        )
        return tuple(item.value for item in relevant if item in allowed)


def export_icalendar(
    actor: User,
    organization_reference: UUID | str,
    *,
    view: str,
    anchor_date: date,
    venue_id: UUID | None = None,
    space_id: UUID | None = None,
) -> str:
    with authorized_tenant_scope(actor, organization_reference, Capability.SCHEDULE_EXPORT) as auth:
        auth.require(Capability.AVAILABILITY_READ)
    payload = calendar_entries(
        actor,
        organization_reference,
        view=view,
        anchor_date=anchor_date,
        venue_id=venue_id,
        space_id=space_id,
    )
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Claridez//Agenda P8//ES"]
    for entry in payload["entries"]:
        if not entry["is_blocking"]:
            continue
        start = entry["starts_at"].astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        end = entry["ends_at"].astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        summary = "Bloqueo interno" if entry["type"] == "block" else "Reserva"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{entry['id']}@claridez.local",
            f"DTSTART:{start}",
            f"DTEND:{end}",
            f"SUMMARY:{summary} - {entry['space_name']}",
            f"LOCATION:{entry['venue_name']} / {entry['space_name']}",
            f"STATUS:{'CONFIRMED' if entry['is_blocking'] else 'CANCELLED'}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
