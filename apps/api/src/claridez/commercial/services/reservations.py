from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import connection
from django.utils import timezone

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from ..errors import conflict, invalid, unavailable
from ..models import EventRequest, Reservation
from ..normalization import canonical_text, money
from .representations import _reservation_summary
from .shared import _aware, _uuid

HOLD_DURATION = timedelta(hours=48)


def _expire_overdue(authorization: TenantAuthorization, *, now: datetime | None = None) -> int:
    effective_now = timezone.now() if now is None else now
    rows = list(
        Reservation.objects.select_for_update()
        .filter(
            organization_id=authorization.organization_id,
            status=Reservation.Status.PROVISIONAL,
            hold_expires_at__lte=effective_now,
        )
        .order_by("created_at", "id")
    )
    transitioned = 0
    for reservation in rows:
        reservation.status = Reservation.Status.EXPIRED
        reservation.save(update_fields=["status", "updated_at"])
        event_request = EventRequest.objects.select_for_update().get(
            organization_id=authorization.organization_id, pk=reservation.event_request_id
        )
        has_active = Reservation.objects.filter(
            organization_id=authorization.organization_id,
            event_request=event_request,
            status__in=[Reservation.Status.PROVISIONAL, Reservation.Status.CONFIRMED],
        ).exists()
        if event_request.status == EventRequest.Status.ACCEPTED and not has_active:
            event_request.status = EventRequest.Status.QUOTED
            event_request.save(update_fields=["status", "updated_at"])
        transitioned += 1
    return transitioned


def _evaluate_expiration(
    actor: User,
    organization_reference: UUID | str,
    capability: Capability,
) -> int:
    """Persistir vencimientos antes de ejecutar un comando que todavía puede fallar."""
    with authorized_tenant_scope(actor, organization_reference, capability) as authorization:
        return _expire_overdue(authorization)


def _lock_organization_schedule(organization_id: UUID) -> None:
    """Serializar aceptaciones del único espacio sin bloquear otros comandos comerciales."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (str(organization_id),),
        )


def _get_reservation(
    organization_id: UUID, reservation_id: UUID | str, *, lock: bool = False
) -> Reservation:
    rows = Reservation.objects.select_related("quotation_version", "event_request")
    if lock:
        rows = rows.select_for_update()
    try:
        return rows.get(
            organization_id=organization_id,
            pk=_uuid(reservation_id, "La reserva"),
        )
    except Reservation.DoesNotExist:
        raise unavailable("La reserva") from None


def read_reservation(
    actor: User, organization_reference: UUID | str, *, reservation_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_READ
    ) as authorization:
        _expire_overdue(authorization)
        return _reservation_summary(_get_reservation(authorization.organization_id, reservation_id))


def confirm_reservation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    kind: str,
    recognized_amount: Decimal | None = None,
    reported_at: datetime | None = None,
    reference: str = "",
    waiver_reason: str = "",
) -> dict[str, Any]:
    _evaluate_expiration(actor, organization_reference, Capability.RESERVATION_CONFIRM)
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESERVATION_CONFIRM
    ) as authorization:
        row = _get_reservation(authorization.organization_id, reservation_id, lock=True)
        if row.status == Reservation.Status.CONFIRMED:
            return _reservation_summary(row)
        if row.status != Reservation.Status.PROVISIONAL:
            raise conflict("invalid_transition", "La reserva ya no puede confirmarse.")
        now = timezone.now()
        if row.hold_expires_at <= now:
            _expire_overdue(authorization, now=now)
            raise conflict("expired_reservation", "La reserva provisional venció.")
        if kind == Reservation.ConfirmationKind.EXTERNAL_DEPOSIT:
            if recognized_amount is None or reported_at is None:
                raise invalid("El monto y la fecha informada son obligatorios.")
            amount = money(recognized_amount)
            quote_total = row.quotation_version.total
            if amount <= 0 or amount > quote_total:
                raise invalid("El monto reconocido debe ser mayor que cero y no superar el total.")
            reported = _aware(reported_at, "La fecha informada")
            try:
                canonical_reference = canonical_text(
                    reference, field="La referencia", max_length=300
                )
            except ValueError as error:
                raise invalid(str(error)) from error
            row.recognized_deposit_amount = amount
            row.deposit_reported_at = reported
            row.deposit_reference = canonical_reference
        elif kind == Reservation.ConfirmationKind.WAIVER:
            authorization.require(Capability.RESERVATION_WAIVE_DEPOSIT)
            try:
                row.waiver_reason = canonical_text(
                    waiver_reason, field="La razón de excepción", max_length=500
                )
            except ValueError as error:
                raise invalid(str(error)) from error
            row.waiver_authorized_at = now
            row.waiver_authorized_by_membership_id = authorization.membership_id
        else:
            raise invalid("El tipo de confirmación no es válido.")
        row.confirmation_kind = kind
        row.status = Reservation.Status.CONFIRMED
        row.confirmed_at = now
        row.confirmed_by_membership_id = authorization.membership_id
        row.save()
        event_request = EventRequest.objects.select_for_update().get(
            organization_id=authorization.organization_id, pk=row.event_request_id
        )
        if event_request.status != EventRequest.Status.ACCEPTED:
            raise conflict("invalid_transition", "La solicitud no puede confirmarse.")
        event_request.status = EventRequest.Status.CONFIRMED
        event_request.save(update_fields=["status", "updated_at"])
        return _reservation_summary(row)


def cancel_reservation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    reason: str,
) -> dict[str, Any]:
    _evaluate_expiration(actor, organization_reference, Capability.RESERVATION_CANCEL)
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESERVATION_CANCEL
    ) as authorization:
        row = _get_reservation(authorization.organization_id, reservation_id, lock=True)
        if row.status == Reservation.Status.CANCELLED:
            return _reservation_summary(row)
        if row.status == Reservation.Status.EXPIRED:
            raise conflict("invalid_transition", "La reserva provisional ya venció.")
        try:
            canonical_reason = canonical_text(
                reason, field="La razón de cancelación", max_length=500
            )
        except ValueError as error:
            raise invalid(str(error)) from error
        was_confirmed = row.confirmed_at is not None
        now = timezone.now()
        row.status = Reservation.Status.CANCELLED
        row.cancelled_at = now
        row.cancelled_by_membership_id = authorization.membership_id
        row.cancellation_reason = canonical_reason
        row.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancelled_by_membership",
                "cancellation_reason",
                "updated_at",
            ]
        )
        event_request = EventRequest.objects.select_for_update().get(
            organization_id=authorization.organization_id, pk=row.event_request_id
        )
        event_request.status = (
            EventRequest.Status.CANCELLED if was_confirmed else EventRequest.Status.CLOSED_LOST
        )
        event_request.closed_at = now
        event_request.closed_reason = canonical_reason
        event_request.save(update_fields=["status", "closed_at", "closed_reason", "updated_at"])
        return _reservation_summary(row)
