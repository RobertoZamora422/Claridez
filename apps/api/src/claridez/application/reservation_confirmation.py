"""Coordinación neutral de confirmación, cuentas por cobrar y operación."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.receivables.errors import conflict as financial_conflict
from claridez.receivables.models import ReceivedPayment
from claridez.receivables.money import amount
from claridez.receivables.services import (
    apply_payment_authorized,
    command_replay,
    complete_command,
    create_obligation_authorized,
    record_payment_authorized,
)

CONFIRMATION_NAMESPACE = UUID("4a50764d-0e97-5f68-b060-101572103532")


def _key(value: UUID | str | None, *, organization_id: UUID, reservation_id: UUID) -> UUID:
    if value is None:
        return uuid5(CONFIRMATION_NAMESPACE, f"{organization_id}:{reservation_id}:compatibility")
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise financial_conflict(
            "invalid_idempotency_key", "La clave de idempotencia no es válida."
        ) from None


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
    payment_method: str = ReceivedPayment.Method.LEGACY_UNSPECIFIED,
    observation: str = "",
    idempotency_key: UUID | str | None = None,
) -> dict[str, Any]:
    # Imports locales: el coordinador compone puertos públicos sin convertirlos
    # en dependencias de carga entre los dominios propietarios.
    import claridez.commercial.public as commercial_port
    import claridez.operations.public as operations_port
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
        key = _key(
            idempotency_key,
            organization_id=authorization.organization_id,
            reservation_id=canonical_reservation_id,
        )
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
        replay = command_replay(
            authorization,
            command_type="confirm_reservation",
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
            complete_command(
                authorization,
                command_type="confirm_reservation",
                idempotency_key=key,
                payload=payload,
                result_type="reservation",
                result_reference=readiness.reservation.id,
            )
        else:
            quotation = commercial_port.accepted_quotation_snapshot(
                authorization, readiness.reservation.quotation_version_id
            )
            payment = None
            if kind == "external_deposit":
                authorization.require(Capability.RECEIVABLES_RECORD_PAYMENT)
                authorization.require(Capability.RECEIVABLES_APPLY_PAYMENT)
                if recognized_amount is None or reported_at is None:
                    raise financial_conflict(
                        "invalid_confirmation_deposit",
                        "El monto y la fecha reportada del anticipo son obligatorios.",
                    )
                try:
                    recognized = amount(recognized_amount)
                except ValueError as error:
                    raise financial_conflict("invalid_confirmation_deposit", str(error)) from error
                if recognized <= 0 or recognized > quotation.total:
                    raise financial_conflict(
                        "invalid_confirmation_deposit",
                        "El anticipo debe ser mayor que cero y no superar el total aceptado.",
                    )
                payment = record_payment_authorized(
                    authorization,
                    counterparty_person_id=quotation.person_id,
                    amount_value=recognized,
                    currency_value=quotation.currency,
                    reported_at=reported_at,
                    method=payment_method,
                    reference=reference,
                    observation=observation,
                    provenance=ReceivedPayment.Provenance.CONFIRMATION_DEPOSIT,
                    evidence_level=ReceivedPayment.EvidenceLevel.INTERNAL_REPORT,
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
            obligation = create_obligation_authorized(
                authorization,
                confirmed.reservation,
                quotation,
                confirmation_event_id=confirmed.confirmation_event_id,
                confirmation_source_id=confirmed.confirmation_source_id,
            )
            if payment is not None:
                apply_payment_authorized(
                    authorization,
                    payment_id=payment.pk,
                    obligation_id=obligation.pk,
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
            complete_command(
                authorization,
                command_type="confirm_reservation",
                idempotency_key=key,
                payload=payload,
                result_type="reservation",
                result_reference=confirmed.reservation.id,
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
