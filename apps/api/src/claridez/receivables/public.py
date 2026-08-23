"""Puerto público estrecho e inmutable de cuentas por cobrar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .errors import ReceivablesError, conflict, unavailable
from .models import MovementReversal, ReceivableObligation, ReceivedPayment, RefundRecord
from .money import amount
from .services import (
    adjusted_obligation_amount,
    apply_payment_authorized,
    command_replay,
    complete_command,
    create_obligation_authorized,
    obligation_balance,
    record_payment_authorized,
)

if TYPE_CHECKING:
    from claridez.commercial.public import AcceptedQuotationProjection
    from claridez.scheduling.public import ReservationProjection


@dataclass(frozen=True, slots=True)
class ConfirmationPaymentProjection:
    payment_id: UUID
    amount: Decimal
    currency: str
    reported_at: datetime
    reference: str


@dataclass(frozen=True, slots=True)
class ConfirmationObligationProjection:
    obligation_id: UUID


@dataclass(frozen=True, slots=True)
class ConfirmationApplicationProjection:
    application_id: UUID
    payment_id: UUID
    obligation_id: UUID
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class ReceivableSummaryProjection:
    root_reservation_id: UUID
    event_request_id: UUID
    currency: str
    original_total: Decimal
    applied_total: Decimal
    balance: Decimal
    derived_status: str


@dataclass(frozen=True, slots=True)
class FinanceObligationProjection:
    obligation_id: UUID
    root_reservation_id: UUID
    quotation_version_id: UUID
    currency: str
    original_total: Decimal
    registered_at: datetime


@dataclass(frozen=True, slots=True)
class FinanceCashContributionProjection:
    source_kind: str
    source_id: UUID
    root_reservation_id: UUID | None
    direction: str
    amount: Decimal
    currency: str
    economic_at: datetime
    registered_at: datetime


def obligation_for_finance(
    authorization: TenantAuthorization, root_reservation_id: UUID
) -> FinanceObligationProjection:
    try:
        row = ReceivableObligation.objects.get(
            organization_id=authorization.organization_id,
            root_reservation_id=root_reservation_id,
        )
    except ReceivableObligation.DoesNotExist:
        raise unavailable("La obligación") from None
    return FinanceObligationProjection(
        obligation_id=row.pk,
        root_reservation_id=row.root_reservation_id,
        quotation_version_id=row.quotation_version_id,
        currency=row.currency,
        original_total=row.original_total,
        registered_at=row.created_at,
    )


def cash_contributions_for_finance(
    authorization: TenantAuthorization,
) -> tuple[FinanceCashContributionProjection, ...]:
    organization_id = authorization.organization_id
    payments = {
        row.pk: row for row in ReceivedPayment.objects.filter(organization_id=organization_id)
    }
    refunds = {
        row.pk: row
        for row in RefundRecord.objects.select_related("payment").filter(
            organization_id=organization_id
        )
    }
    result = [
        FinanceCashContributionProjection(
            source_kind="payment",
            source_id=row.pk,
            root_reservation_id=row.root_reservation_id,
            direction="inflow",
            amount=row.amount,
            currency=row.currency,
            economic_at=row.reported_at,
            registered_at=row.created_at,
        )
        for row in payments.values()
    ]
    result.extend(
        FinanceCashContributionProjection(
            source_kind="refund",
            source_id=row.pk,
            root_reservation_id=row.payment.root_reservation_id,
            direction="outflow",
            amount=row.amount,
            currency=row.currency,
            economic_at=row.refunded_at,
            registered_at=row.created_at,
        )
        for row in refunds.values()
    )
    for reversal in MovementReversal.objects.filter(
        organization_id=organization_id,
        target_kind__in=[
            MovementReversal.TargetKind.PAYMENT,
            MovementReversal.TargetKind.REFUND,
        ],
    ):
        if reversal.target_kind == MovementReversal.TargetKind.PAYMENT:
            payment = payments.get(reversal.target_id)
            if payment is None:
                continue
            root_id = payment.root_reservation_id
            direction = "outflow"
            kind = "payment_reversal"
        else:
            refund = refunds.get(reversal.target_id)
            if refund is None:
                continue
            root_id = refund.payment.root_reservation_id
            direction = "inflow"
            kind = "refund_reversal"
        result.append(
            FinanceCashContributionProjection(
                source_kind=kind,
                source_id=reversal.pk,
                root_reservation_id=root_id,
                direction=direction,
                amount=reversal.amount,
                currency=reversal.currency,
                economic_at=reversal.reversed_at,
                registered_at=reversal.created_at,
            )
        )
    return tuple(sorted(result, key=lambda row: (row.registered_at, str(row.source_id))))


def invalid_confirmation_idempotency_key() -> ReceivablesError:
    return conflict("invalid_idempotency_key", "La clave de idempotencia no es válida.")


def validate_confirmation_deposit(
    recognized_amount: Decimal | None,
    reported_at: datetime | None,
    *,
    accepted_total: Decimal,
) -> Decimal:
    if recognized_amount is None or reported_at is None:
        raise conflict(
            "invalid_confirmation_deposit",
            "El monto y la fecha reportada del anticipo son obligatorios.",
        )
    try:
        normalized = amount(recognized_amount)
    except ValueError as error:
        raise conflict("invalid_confirmation_deposit", str(error)) from error
    if normalized <= 0 or normalized > accepted_total:
        raise conflict(
            "invalid_confirmation_deposit",
            "El anticipo debe ser mayor que cero y no superar el total aceptado.",
        )
    return normalized


def replay_reservation_confirmation_command(
    authorization: TenantAuthorization,
    *,
    idempotency_key: UUID,
    payload: object,
) -> UUID | None:
    return command_replay(
        authorization,
        command_type="confirm_reservation",
        idempotency_key=idempotency_key,
        payload=payload,
    )


def complete_reservation_confirmation_command(
    authorization: TenantAuthorization,
    *,
    idempotency_key: UUID,
    payload: object,
    reservation_id: UUID,
) -> None:
    complete_command(
        authorization,
        command_type="confirm_reservation",
        idempotency_key=idempotency_key,
        payload=payload,
        result_type="reservation",
        result_reference=reservation_id,
    )


def record_confirmation_payment(
    authorization: TenantAuthorization,
    *,
    counterparty_person_id: UUID,
    amount_value: Decimal,
    currency_value: str,
    reported_at: datetime,
    method: str,
    reference: str,
    observation: str,
    idempotency_key: UUID,
    root_reservation_id: UUID,
    event_request_id: UUID,
    confirmation_source_id: UUID,
) -> ConfirmationPaymentProjection:
    row = record_payment_authorized(
        authorization,
        counterparty_person_id=counterparty_person_id,
        amount_value=amount_value,
        currency_value=currency_value,
        reported_at=reported_at,
        method=method,
        reference=reference,
        observation=observation,
        provenance=ReceivedPayment.Provenance.CONFIRMATION_DEPOSIT,
        evidence_level=ReceivedPayment.EvidenceLevel.INTERNAL_REPORT,
        idempotency_key=idempotency_key,
        root_reservation_id=root_reservation_id,
        event_request_id=event_request_id,
        confirmation_source_id=confirmation_source_id,
    )
    return ConfirmationPaymentProjection(
        payment_id=row.pk,
        amount=row.amount,
        currency=row.currency,
        reported_at=row.reported_at,
        reference=row.reference,
    )


def create_or_get_confirmation_obligation(
    authorization: TenantAuthorization,
    reservation: ReservationProjection,
    quotation: AcceptedQuotationProjection,
    *,
    confirmation_event_id: UUID,
    confirmation_source_id: UUID,
) -> ConfirmationObligationProjection:
    row = create_obligation_authorized(
        authorization,
        reservation,
        quotation,
        confirmation_event_id=confirmation_event_id,
        confirmation_source_id=confirmation_source_id,
    )
    return ConfirmationObligationProjection(obligation_id=row.pk)


def apply_confirmation_payment(
    authorization: TenantAuthorization,
    *,
    payment_id: UUID,
    obligation_id: UUID,
    amount_value: Decimal,
    idempotency_key: UUID,
) -> ConfirmationApplicationProjection:
    row = apply_payment_authorized(
        authorization,
        payment_id=payment_id,
        obligation_id=obligation_id,
        amount_value=amount_value,
        idempotency_key=idempotency_key,
    )
    return ConfirmationApplicationProjection(
        application_id=row.pk,
        payment_id=row.payment_id,
        obligation_id=row.obligation_id,
        amount=row.amount,
        currency=row.currency,
    )


def summary_for_commercial(
    authorization: TenantAuthorization, root_reservation_id: UUID
) -> ReceivableSummaryProjection:
    authorization.require(Capability.RECEIVABLES_READ_SUMMARY)
    row = ReceivableObligation.objects.filter(
        organization_id=authorization.organization_id,
        root_reservation_id=root_reservation_id,
    ).first()
    if row is None:
        raise unavailable("La obligación")
    balance = obligation_balance(row)
    applied = adjusted_obligation_amount(row) - balance
    return ReceivableSummaryProjection(
        root_reservation_id=row.root_reservation_id,
        event_request_id=row.event_request_id,
        currency=row.currency,
        original_total=row.original_total,
        applied_total=applied,
        balance=balance,
        derived_status=(
            "satisfied" if balance == Decimal("0.00") else "partial" if applied > 0 else "open"
        ),
    )


__all__ = (
    "ConfirmationApplicationProjection",
    "ConfirmationObligationProjection",
    "ConfirmationPaymentProjection",
    "ReceivableSummaryProjection",
    "FinanceObligationProjection",
    "FinanceCashContributionProjection",
    "ReceivablesError",
    "apply_confirmation_payment",
    "complete_reservation_confirmation_command",
    "create_or_get_confirmation_obligation",
    "invalid_confirmation_idempotency_key",
    "record_confirmation_payment",
    "obligation_for_finance",
    "cash_contributions_for_finance",
    "replay_reservation_confirmation_command",
    "summary_for_commercial",
    "validate_confirmation_deposit",
)
