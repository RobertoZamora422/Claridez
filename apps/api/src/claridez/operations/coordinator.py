from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import IntegrityError

from claridez.commercial.errors import CommercialError
from claridez.commercial.errors import conflict as commercial_conflict
from claridez.commercial.models import Reservation
from claridez.commercial.services.reservations import (
    _cancel_reservation_commercial,
    _confirm_reservation_commercial,
    _evaluate_expiration,
    _get_reservation,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope

from .errors import OperationsError
from .models import EventPreparation
from .services import cancel_preparation, initialize_preparation, validate_initialized_preparation


def _as_commercial_error(error: OperationsError) -> CommercialError:
    return CommercialError(error.code, error.message, status=error.status)


def confirm_reservation_with_operations(
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
    try:
        with authorized_tenant_scope(
            actor, organization_reference, Capability.RESERVATION_CONFIRM
        ) as authorization:
            before = _get_reservation(authorization.organization_id, reservation_id, lock=True)
            already_confirmed = before.status == Reservation.Status.CONFIRMED
            result = _confirm_reservation_commercial(
                actor,
                organization_reference,
                reservation_id=reservation_id,
                kind=kind,
                recognized_amount=recognized_amount,
                reported_at=reported_at,
                reference=reference,
                waiver_reason=waiver_reason,
            )
            reservation = _get_reservation(authorization.organization_id, reservation_id, lock=True)
            if already_confirmed:
                validate_initialized_preparation(reservation)
            else:
                if reservation.confirmed_at is None:
                    raise commercial_conflict(
                        "operation_integrity_conflict",
                        "La confirmación no produjo una preparación operativa íntegra.",
                    )
                initialize_preparation(
                    reservation,
                    actor_membership_id=authorization.membership_id,
                    occurred_at=reservation.confirmed_at,
                )
                validate_initialized_preparation(reservation)
            return result
    except OperationsError as error:
        raise _as_commercial_error(error) from error
    except IntegrityError as error:
        raise commercial_conflict(
            "operation_integrity_conflict",
            "No fue posible conservar la integridad entre la reserva y su preparación.",
        ) from error


def cancel_reservation_with_operations(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    reason: str,
) -> dict[str, Any]:
    _evaluate_expiration(actor, organization_reference, Capability.RESERVATION_CANCEL)
    try:
        with authorized_tenant_scope(
            actor, organization_reference, Capability.RESERVATION_CANCEL
        ) as authorization:
            reservation = _get_reservation(authorization.organization_id, reservation_id, lock=True)
            was_confirmed = reservation.confirmed_at is not None
            preparation: EventPreparation | None = None
            if was_confirmed:
                try:
                    preparation = EventPreparation.objects.select_for_update().get(
                        organization_id=authorization.organization_id,
                        reservation_id=reservation.pk,
                    )
                except EventPreparation.DoesNotExist:
                    raise commercial_conflict(
                        "operation_integrity_conflict",
                        "La reserva no tiene una preparación operativa íntegra.",
                    ) from None
                if reservation.status != Reservation.Status.CANCELLED:
                    if preparation.status == EventPreparation.Status.IN_PROGRESS:
                        raise commercial_conflict(
                            "operation_already_started", "El evento ya está en ejecución."
                        )
                    if preparation.status == EventPreparation.Status.COMPLETED:
                        raise commercial_conflict(
                            "operation_already_completed", "El evento ya fue completado."
                        )
            result = _cancel_reservation_commercial(
                actor,
                organization_reference,
                reservation_id=reservation_id,
                reason=reason,
            )
            if preparation is not None:
                reservation.refresh_from_db()
                if reservation.cancelled_at is None:
                    raise commercial_conflict(
                        "operation_integrity_conflict",
                        "La cancelación no produjo evidencia comercial íntegra.",
                    )
                cancel_preparation(
                    preparation,
                    actor_membership_id=authorization.membership_id,
                    occurred_at=reservation.cancelled_at,
                )
            return result
    except OperationsError as error:
        raise _as_commercial_error(error) from error
    except IntegrityError as error:
        raise commercial_conflict(
            "operation_integrity_conflict",
            "No fue posible conservar la integridad entre la reserva y su preparación.",
        ) from error
