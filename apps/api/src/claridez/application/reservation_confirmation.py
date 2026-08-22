"""Coordinación neutral de confirmación, cuentas por cobrar y operación."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope

CONFIRMATION_NAMESPACE = UUID("4a50764d-0e97-5f68-b060-101572103532")


def _key(value: UUID | str | None, *, organization_id: UUID, reservation_id: UUID) -> UUID:
    if value is None:
        return uuid5(CONFIRMATION_NAMESPACE, f"{organization_id}:{reservation_id}:compatibility")
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("invalid_idempotency_key") from None


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
    payment_method: str = "legacy_unspecified",
    observation: str = "",
    idempotency_key: UUID | str | None = None,
) -> dict[str, Any]:
    # Imports locales: el coordinador compone puertos públicos sin convertirlos
    # en dependencias de carga entre los dominios propietarios.
    import claridez.commercial.public as commercial_port
    import claridez.operations.public as operations_port
    import claridez.receivables.public as receivables_port
    import claridez.scheduling.public as scheduling_port

    try:
        canonical_reservation_id = UUID(str(reservation_id))
    except (TypeError, ValueError, AttributeError):
        raise scheduling_port.SchedulingError(
            "resource_not_available", "La reserva no está disponible.", status=404
        ) from None
    expired = False
    result: dict[str, Any] | None = None
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESERVATION_CONFIRM
    ) as authorization:
        try:
            key = _key(
                idempotency_key,
                organization_id=authorization.organization_id,
                reservation_id=canonical_reservation_id,
            )
        except ValueError:
            raise receivables_port.invalid_confirmation_idempotency_key() from None
        payload = (
            {"reservation_id": canonical_reservation_id, "compatibility": True}
            if idempotency_key is None
            else {
                "reservation_id": canonical_reservation_id,
                "kind": kind,
                "recognized_amount": recognized_amount,
                "reported_at": reported_at,
                "reference": reference.strip(),
                "waiver_reason": waiver_reason.strip(),
                "payment_method": payment_method,
                "observation": observation.strip(),
            }
        )
        replay = receivables_port.replay_reservation_confirmation_command(
            authorization,
            idempotency_key=key,
            payload=payload,
        )
        if replay is not None:
            return scheduling_port.reservation_for_commercial(authorization, replay)
        readiness = scheduling_port.prepare_confirmation(authorization, canonical_reservation_id)
        if readiness.state == "expired":
            expired = True
        elif readiness.state == "already_confirmed":
            result = scheduling_port.reservation_for_commercial(
                authorization, canonical_reservation_id
            )
            receivables_port.complete_reservation_confirmation_command(
                authorization,
                idempotency_key=key,
                payload=payload,
                reservation_id=readiness.reservation.id,
            )
        else:
            quotation = commercial_port.accepted_quotation_snapshot(
                authorization, readiness.reservation.quotation_version_id
            )
            payment = None
            if kind == "external_deposit":
                authorization.require(Capability.RECEIVABLES_RECORD_PAYMENT)
                authorization.require(Capability.RECEIVABLES_APPLY_PAYMENT)
                recognized = receivables_port.validate_confirmation_deposit(
                    recognized_amount,
                    reported_at,
                    accepted_total=quotation.total,
                )
                assert reported_at is not None
                payment = receivables_port.record_confirmation_payment(
                    authorization,
                    counterparty_person_id=quotation.person_id,
                    amount_value=recognized,
                    currency_value=quotation.currency,
                    reported_at=reported_at,
                    method=payment_method,
                    reference=reference,
                    observation=observation,
                    idempotency_key=uuid5(key, "payment"),
                    root_reservation_id=readiness.reservation.root_id,
                    event_request_id=readiness.reservation.event_request_id,
                    confirmation_source_id=readiness.reservation.id,
                )
            confirmed = scheduling_port.confirm_prepared(
                authorization,
                canonical_reservation_id,
                kind=kind,
                recognized_amount=payment.amount if payment is not None else None,
                reported_at=payment.reported_at if payment is not None else None,
                reference=payment.reference if payment is not None else "",
                waiver_reason=waiver_reason,
            )
            obligation = receivables_port.create_or_get_confirmation_obligation(
                authorization,
                confirmed.reservation,
                quotation,
                confirmation_event_id=confirmed.confirmation_event_id,
                confirmation_source_id=confirmed.confirmation_source_id,
            )
            if payment is not None:
                receivables_port.apply_confirmation_payment(
                    authorization,
                    payment_id=payment.payment_id,
                    obligation_id=obligation.obligation_id,
                    amount_value=payment.amount,
                    idempotency_key=uuid5(key, "application"),
                )
            commercial_port.set_request_schedule_status(
                authorization, confirmed.reservation.event_request_id, status="confirmed"
            )
            try:
                operations_port.initialize_from_accepted_snapshot(
                    confirmed.reservation,
                    actor_membership_id=authorization.membership_id,
                    occurred_at=confirmed.reservation.confirmed_at or datetime.now().astimezone(),
                )
            except operations_port.OperationsError as error:
                raise scheduling_port.SchedulingError(
                    error.code, error.message, status=error.status
                ) from error
            receivables_port.complete_reservation_confirmation_command(
                authorization,
                idempotency_key=key,
                payload=payload,
                reservation_id=confirmed.reservation.id,
            )
            result = confirmed.data
    if expired:
        raise scheduling_port.SchedulingError(
            "hold_expired", "La reserva provisional venció.", status=409
        )
    if result is None:
        raise scheduling_port.SchedulingError(
            "schedule_integrity_conflict",
            "La confirmación no produjo un resultado.",
            status=409,
        )
    return result
