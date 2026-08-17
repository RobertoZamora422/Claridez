from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.db import connection
from django.db.models import Max, Q, Sum
from django.utils import timezone

import claridez.documents.public as documents_port
import claridez.people.public as people_port
import claridez.scheduling.public as scheduling_port
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.public import contractual_organization
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from .errors import conflict, invalid, unavailable
from .models import (
    CollectionScheduleDue,
    CollectionScheduleRevision,
    FinancialCommand,
    FinancialEvent,
    MovementReversal,
    PaymentApplication,
    Receipt,
    ReceiptSequence,
    ReceivableAdjustment,
    ReceivableObligation,
    ReceivedPayment,
    RefundApplication,
    RefundRecord,
)
from .money import amount, currency, payload_hash, positive_amount

ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class _ObligationReadContext:
    adjusted_totals: dict[UUID, Decimal]
    applied_totals: dict[UUID, Decimal]
    restored_totals: dict[UUID, Decimal]
    dues: dict[UUID, tuple[CollectionScheduleDue, ...]]
    applications: dict[UUID, tuple[PaymentApplication, ...]]
    restored_by_application: dict[UUID, Decimal]
    schedules: dict[UUID, scheduling_port.ContractualScheduleProjection]


class AcceptedQuotationValue(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def organization_id(self) -> UUID: ...

    @property
    def event_request_id(self) -> UUID: ...

    @property
    def person_id(self) -> UUID: ...

    @property
    def visible_number(self) -> str: ...

    @property
    def version(self) -> int: ...

    @property
    def currency(self) -> str: ...

    @property
    def person_name(self) -> str: ...

    @property
    def subtotal(self) -> Decimal: ...

    @property
    def discount_total(self) -> Decimal: ...

    @property
    def total(self) -> Decimal: ...

    @property
    def quotation_notes(self) -> str: ...

    @property
    def accepted_at(self) -> datetime: ...


class ConfirmedReservationValue(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def organization_id(self) -> UUID: ...

    @property
    def event_request_id(self) -> UUID: ...

    @property
    def quotation_version_id(self) -> UUID: ...

    @property
    def root_id(self) -> UUID: ...

    @property
    def status(self) -> str: ...

    @property
    def confirmed_at(self) -> datetime | None: ...


def _uuid(value: UUID | str, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise unavailable(label) from None


def _positive_money(value: Decimal | int | str) -> Decimal:
    try:
        return positive_amount(value)
    except ValueError as error:
        raise invalid(str(error)) from error


def _currency_code(value: str) -> str:
    try:
        return currency(value)
    except ValueError as error:
        raise invalid(str(error)) from error


def _lock_idempotency(organization_id: UUID, command_type: str, key: UUID) -> None:
    lock_key = f"receivables:{organization_id}:{command_type}:{key}"
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [lock_key])


def command_replay(
    authorization: TenantAuthorization,
    *,
    command_type: str,
    idempotency_key: UUID,
    payload: object,
) -> UUID | None:
    _lock_idempotency(authorization.organization_id, command_type, idempotency_key)
    row = FinancialCommand.objects.filter(
        organization_id=authorization.organization_id,
        command_type=command_type,
        idempotency_key=idempotency_key,
    ).first()
    if row is None:
        return None
    if row.payload_hash != payload_hash(payload):
        raise conflict(
            "idempotency_conflict",
            "La clave de idempotencia ya fue usada con una solicitud diferente.",
        )
    return row.result_reference


def complete_command(
    authorization: TenantAuthorization,
    *,
    command_type: str,
    idempotency_key: UUID,
    payload: object,
    result_type: str,
    result_reference: UUID,
) -> None:
    FinancialCommand.objects.create(
        organization_id=authorization.organization_id,
        command_type=command_type,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash(payload),
        result_type=result_type,
        result_reference=result_reference,
    )


def _event(
    authorization: TenantAuthorization,
    *,
    kind: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, object],
    occurred_at: datetime | None = None,
) -> None:
    FinancialEvent.objects.create(
        organization_id=authorization.organization_id,
        kind=kind,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        actor_membership_id=authorization.membership_id,
        payload=payload,
        occurred_at=occurred_at or timezone.now(),
    )


def _obligation(
    authorization: TenantAuthorization, obligation_id: UUID | str, *, lock: bool = False
) -> ReceivableObligation:
    rows = ReceivableObligation.objects.all()
    if lock:
        rows = rows.select_for_update()
    try:
        return rows.get(
            organization_id=authorization.organization_id,
            pk=_uuid(obligation_id, "La obligación"),
        )
    except ReceivableObligation.DoesNotExist:
        raise unavailable("La obligación") from None


def _payment(
    authorization: TenantAuthorization, payment_id: UUID | str, *, lock: bool = False
) -> ReceivedPayment:
    rows = ReceivedPayment.objects.all()
    if lock:
        rows = rows.select_for_update()
    try:
        return rows.get(
            organization_id=authorization.organization_id,
            pk=_uuid(payment_id, "El pago"),
        )
    except ReceivedPayment.DoesNotExist:
        raise unavailable("El pago") from None


def _reversed_ids(organization_id: UUID, target_kind: str) -> frozenset[UUID]:
    return frozenset(
        MovementReversal.objects.filter(
            organization_id=organization_id, target_kind=target_kind
        ).values_list("target_id", flat=True)
    )


def _active_applications(
    organization_id: UUID,
    *,
    payment_id: UUID | None = None,
    obligation_id: UUID | None = None,
) -> Any:
    rows = (
        PaymentApplication.objects.filter(organization_id=organization_id)
        .exclude(pk__in=_reversed_ids(organization_id, MovementReversal.TargetKind.APPLICATION))
        .exclude(payment_id__in=_reversed_ids(organization_id, MovementReversal.TargetKind.PAYMENT))
    )
    if payment_id is not None:
        rows = rows.filter(payment_id=payment_id)
    if obligation_id is not None:
        rows = rows.filter(obligation_id=obligation_id)
    return rows


def _active_refunds(
    organization_id: UUID,
    *,
    payment_id: UUID | None = None,
    obligation_id: UUID | None = None,
) -> Any:
    rows = (
        RefundRecord.objects.filter(organization_id=organization_id)
        .exclude(pk__in=_reversed_ids(organization_id, MovementReversal.TargetKind.REFUND))
        .exclude(payment_id__in=_reversed_ids(organization_id, MovementReversal.TargetKind.PAYMENT))
    )
    if payment_id is not None:
        rows = rows.filter(payment_id=payment_id)
    if obligation_id is not None:
        rows = rows.filter(obligation_id=obligation_id)
    return rows


def _active_refund_allocations(organization_id: UUID, *, obligation_id: UUID | None = None) -> Any:
    rows = (
        RefundApplication.objects.filter(organization_id=organization_id)
        .exclude(refund_id__in=_reversed_ids(organization_id, MovementReversal.TargetKind.REFUND))
        .exclude(
            payment_application_id__in=_reversed_ids(
                organization_id, MovementReversal.TargetKind.APPLICATION
            )
        )
        .exclude(
            payment_application__payment_id__in=_reversed_ids(
                organization_id, MovementReversal.TargetKind.PAYMENT
            )
        )
    )
    if obligation_id is not None:
        rows = rows.filter(payment_application__obligation_id=obligation_id)
    return rows


def _sum(rows: Any, field: str = "amount") -> Decimal:
    return cast(Decimal | None, rows.aggregate(value=Sum(field))["value"]) or ZERO


def adjusted_obligation_amount(row: ReceivableObligation) -> Decimal:
    reversed_adjustments = _reversed_ids(
        row.organization_id, MovementReversal.TargetKind.ADJUSTMENT
    )
    adjustments = ReceivableAdjustment.objects.filter(
        organization_id=row.organization_id, obligation_id=row.pk
    ).exclude(pk__in=reversed_adjustments)
    increases = _sum(adjustments.filter(direction=ReceivableAdjustment.Direction.INCREASE))
    decreases = _sum(adjustments.filter(direction=ReceivableAdjustment.Direction.DECREASE))
    return amount(row.original_total + increases - decreases)


def obligation_balance(row: ReceivableObligation) -> Decimal:
    applied = _sum(_active_applications(row.organization_id, obligation_id=row.pk))
    restored = _sum(_active_refund_allocations(row.organization_id, obligation_id=row.pk))
    return amount(adjusted_obligation_amount(row) - applied + restored)


def payment_available(row: ReceivedPayment) -> Decimal:
    if MovementReversal.objects.filter(
        organization_id=row.organization_id,
        target_kind=MovementReversal.TargetKind.PAYMENT,
        target_id=row.pk,
    ).exists():
        return ZERO
    applications = _sum(_active_applications(row.organization_id, payment_id=row.pk))
    refunds = _sum(_active_refunds(row.organization_id, payment_id=row.pk))
    restored = _sum(
        _active_refund_allocations(row.organization_id).filter(
            payment_application__payment_id=row.pk
        )
    )
    return amount(row.amount - applications - refunds + restored)


def create_obligation_authorized(
    authorization: TenantAuthorization,
    reservation: ConfirmedReservationValue,
    quotation: AcceptedQuotationValue,
    *,
    confirmation_event_id: UUID,
    confirmation_source_id: UUID,
) -> ReceivableObligation:
    if reservation.organization_id != authorization.organization_id:
        raise unavailable("La reserva")
    if quotation.organization_id != authorization.organization_id:
        raise unavailable("La cotización aceptada")
    if reservation.status != "confirmed" or reservation.confirmed_at is None:
        raise conflict("reservation_not_confirmed", "La reserva todavía no está confirmada.")
    if reservation.event_request_id != quotation.event_request_id:
        raise conflict("financial_source_mismatch", "La reserva y la cotización no coinciden.")
    if reservation.quotation_version_id != quotation.id:
        raise conflict("financial_source_mismatch", "La versión comercial no coincide.")
    existing = (
        ReceivableObligation.objects.select_for_update()
        .filter(
            organization_id=authorization.organization_id,
            root_reservation_id=reservation.root_id,
        )
        .first()
    )
    if existing is not None:
        if (
            existing.event_request_id != quotation.event_request_id
            or existing.quotation_version_id != quotation.id
            or existing.original_total != amount(quotation.total)
            or existing.currency != currency(quotation.currency)
        ):
            raise conflict(
                "financial_source_mismatch", "La raíz ya posee una obligación incompatible."
            )
        return existing
    row = ReceivableObligation.objects.create(
        organization_id=authorization.organization_id,
        root_reservation_id=reservation.root_id,
        confirmation_source_id=confirmation_source_id,
        confirmation_event_id=confirmation_event_id,
        event_request_id=quotation.event_request_id,
        quotation_version_id=quotation.id,
        quotation_visible_number=quotation.visible_number,
        quotation_version=quotation.version,
        counterparty_person_id=quotation.person_id,
        counterparty_name_snapshot=quotation.person_name,
        currency=currency(quotation.currency),
        subtotal=amount(quotation.subtotal),
        discount_total=amount(quotation.discount_total),
        original_total=amount(quotation.total),
        economic_terms_snapshot={
            "quotation_notes": quotation.quotation_notes,
            "accepted_at": quotation.accepted_at.isoformat(),
        },
        confirmed_at=reservation.confirmed_at,
        created_by_membership_id=authorization.membership_id,
    )
    _event(
        authorization,
        kind="obligation_created",
        aggregate_type="obligation",
        aggregate_id=row.pk,
        payload={
            "root_reservation_id": str(row.root_reservation_id),
            "quotation_version_id": str(row.quotation_version_id),
            "currency": row.currency,
            "original_total": format(row.original_total, ".2f"),
        },
        occurred_at=row.confirmed_at,
    )
    return row


def record_payment_authorized(
    authorization: TenantAuthorization,
    *,
    counterparty_person_id: UUID,
    amount_value: Decimal | int | str,
    currency_value: str,
    reported_at: datetime,
    method: str,
    reference: str,
    observation: str,
    provenance: str,
    evidence_level: str,
    idempotency_key: UUID,
    root_reservation_id: UUID | None = None,
    event_request_id: UUID | None = None,
    confirmation_source_id: UUID | None = None,
    duplicate_review_note: str = "",
) -> ReceivedPayment:
    authorization.require(Capability.RECEIVABLES_RECORD_PAYMENT)
    normalized_amount = _positive_money(amount_value)
    normalized_currency = _currency_code(currency_value)
    if reported_at.tzinfo is None:
        raise invalid("La fecha reportada debe incluir zona horaria.")
    try:
        canonical_person = people_port.get_person(
            authorization.organization_id, counterparty_person_id
        )
    except people_port.PeopleError:
        raise unavailable("La contraparte") from None
    if canonical_person.id != counterparty_person_id:
        raise conflict("counterparty_merged", "Debe utilizarse la contraparte canónica.")
    if root_reservation_id is not None:
        schedule = scheduling_port.contractual_schedule(authorization, root_reservation_id)
        if event_request_id is not None and schedule.event_request_id != event_request_id:
            raise conflict("financial_context_mismatch", "El contexto del pago no coincide.")
        event_request_id = schedule.event_request_id
        obligation = ReceivableObligation.objects.filter(
            organization_id=authorization.organization_id,
            root_reservation_id=root_reservation_id,
        ).first()
        if obligation is None and provenance != ReceivedPayment.Provenance.CONFIRMATION_DEPOSIT:
            raise conflict(
                "financial_context_not_confirmed",
                "La raíz todavía no posee una obligación canónica.",
            )
        if obligation is not None and (
            obligation.event_request_id != event_request_id
            or obligation.counterparty_person_id != counterparty_person_id
        ):
            raise conflict("financial_context_mismatch", "El contexto del pago no coincide.")
        if obligation is not None and obligation.currency != normalized_currency:
            raise conflict("currency_mismatch", "El pago y la obligación tienen monedas distintas.")
    normalized_reference = " ".join(reference.strip().casefold().split())
    payload = {
        "counterparty_person_id": counterparty_person_id,
        "amount": normalized_amount,
        "currency": normalized_currency,
        "reported_at": reported_at,
        "method": method,
        "reference": reference.strip(),
        "observation": observation.strip(),
        "provenance": provenance,
        "evidence_level": evidence_level,
        "root_reservation_id": root_reservation_id,
        "event_request_id": event_request_id,
        "confirmation_source_id": confirmation_source_id,
    }
    replay = command_replay(
        authorization,
        command_type="record_payment",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        return _payment(authorization, replay)
    if method not in ReceivedPayment.Method.values:
        raise invalid("El método de pago no es válido.")
    if provenance not in ReceivedPayment.Provenance.values:
        raise invalid("La procedencia del pago no es válida.")
    if evidence_level not in ReceivedPayment.EvidenceLevel.values:
        raise invalid("El nivel de evidencia no es válido.")
    possible_duplicate = ReceivedPayment.objects.filter(
        organization_id=authorization.organization_id,
        counterparty_person_id=counterparty_person_id,
        amount=normalized_amount,
        currency=normalized_currency,
        reported_at=reported_at,
        method=method,
    ).exists()
    if possible_duplicate and not duplicate_review_note.strip():
        raise conflict(
            "possible_duplicate_payment",
            "Existe un pago parecido. Confirme la decisión con una nota de revisión.",
        )
    row = ReceivedPayment.objects.create(
        organization_id=authorization.organization_id,
        root_reservation_id=root_reservation_id,
        event_request_id=event_request_id,
        counterparty_person_id=counterparty_person_id,
        amount=normalized_amount,
        currency=normalized_currency,
        reported_at=reported_at,
        method=method,
        reference=reference.strip(),
        normalized_reference=normalized_reference,
        observation=observation.strip(),
        provenance=provenance,
        evidence_level=evidence_level,
        confirmation_source_id=confirmation_source_id,
        recorded_by_membership_id=authorization.membership_id,
        possible_duplicate=possible_duplicate,
        duplicate_review_note=duplicate_review_note.strip(),
    )
    complete_command(
        authorization,
        command_type="record_payment",
        idempotency_key=idempotency_key,
        payload=payload,
        result_type="payment",
        result_reference=row.pk,
    )
    _event(
        authorization,
        kind="payment_recorded",
        aggregate_type="payment",
        aggregate_id=row.pk,
        payload={"amount": format(row.amount, ".2f"), "currency": row.currency},
        occurred_at=row.reported_at,
    )
    return row


def apply_payment_authorized(
    authorization: TenantAuthorization,
    *,
    payment_id: UUID | str,
    obligation_id: UUID | str,
    amount_value: Decimal | int | str,
    idempotency_key: UUID,
    due_key: UUID | None = None,
) -> PaymentApplication:
    authorization.require(Capability.RECEIVABLES_APPLY_PAYMENT)
    normalized_amount = _positive_money(amount_value)
    payload = {
        "payment_id": _uuid(payment_id, "El pago"),
        "obligation_id": _uuid(obligation_id, "La obligación"),
        "amount": normalized_amount,
        "due_key": due_key,
    }
    replay = command_replay(
        authorization,
        command_type="apply_payment",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        try:
            return PaymentApplication.objects.get(
                organization_id=authorization.organization_id, pk=replay
            )
        except PaymentApplication.DoesNotExist:
            raise unavailable("La aplicación") from None
    obligation = _obligation(authorization, obligation_id, lock=True)
    payment = _payment(authorization, payment_id, lock=True)
    if payment.currency != obligation.currency:
        raise conflict("currency_mismatch", "El pago y la obligación tienen monedas distintas.")
    if payment.counterparty_person_id != obligation.counterparty_person_id:
        raise conflict("counterparty_mismatch", "El pago pertenece a otra contraparte.")
    available = payment_available(payment)
    balance = obligation_balance(obligation)
    if normalized_amount > available:
        raise conflict("payment_overallocated", "El pago no tiene suficiente importe sin aplicar.")
    if normalized_amount > balance:
        raise conflict(
            "obligation_overallocated", "La aplicación supera el saldo de la obligación."
        )
    if due_key is not None:
        current = current_schedule(obligation)
        due = next((item for item in current if item.due_key == due_key), None)
        if due is None:
            raise unavailable("El vencimiento")
        due_applied = _sum(
            _active_applications(authorization.organization_id, obligation_id=obligation.pk).filter(
                due_key=due_key
            )
        )
        due_restored = _sum(
            _active_refund_allocations(
                authorization.organization_id, obligation_id=obligation.pk
            ).filter(payment_application__due_key=due_key)
        )
        if normalized_amount > amount(due.amount - due_applied + due_restored):
            raise conflict("due_overallocated", "La aplicación supera el saldo del vencimiento.")
    row = PaymentApplication.objects.create(
        organization_id=authorization.organization_id,
        payment=payment,
        obligation=obligation,
        due_key=due_key,
        amount=normalized_amount,
        currency=obligation.currency,
        applied_by_membership_id=authorization.membership_id,
        applied_at=timezone.now(),
    )
    complete_command(
        authorization,
        command_type="apply_payment",
        idempotency_key=idempotency_key,
        payload=payload,
        result_type="application",
        result_reference=row.pk,
    )
    _event(
        authorization,
        kind="payment_applied",
        aggregate_type="application",
        aggregate_id=row.pk,
        payload={
            "payment_id": str(payment.pk),
            "obligation_id": str(obligation.pk),
            "amount": format(row.amount, ".2f"),
        },
        occurred_at=row.applied_at,
    )
    return row


def current_schedule(obligation: ReceivableObligation) -> tuple[CollectionScheduleDue, ...]:
    revision = CollectionScheduleRevision.objects.filter(
        organization_id=obligation.organization_id, obligation=obligation
    ).aggregate(value=Max("revision"))["value"]
    if revision is None:
        return ()
    return tuple(
        CollectionScheduleDue.objects.filter(
            organization_id=obligation.organization_id,
            obligation=obligation,
            schedule_revision__revision=revision,
        ).order_by("due_on", "position", "id")
    )


def _obligation_read_context(
    authorization: TenantAuthorization, obligations: tuple[ReceivableObligation, ...]
) -> _ObligationReadContext:
    obligation_ids = tuple(row.pk for row in obligations)
    if not obligation_ids:
        return _ObligationReadContext({}, {}, {}, {}, {}, {}, {})

    reversed_targets: dict[str, set[UUID]] = {}
    for target_kind, target_id in MovementReversal.objects.filter(
        organization_id=authorization.organization_id
    ).values_list("target_kind", "target_id"):
        reversed_targets.setdefault(target_kind, set()).add(target_id)

    adjustments = (
        ReceivableAdjustment.objects.filter(
            organization_id=authorization.organization_id,
            obligation_id__in=obligation_ids,
        )
        .exclude(pk__in=reversed_targets.get(MovementReversal.TargetKind.ADJUSTMENT, set()))
        .values("obligation_id", "direction")
        .annotate(total=Sum("amount"))
    )
    adjustment_deltas = {obligation_id: ZERO for obligation_id in obligation_ids}
    for item in adjustments:
        signed = cast(Decimal, item["total"])
        if item["direction"] == ReceivableAdjustment.Direction.DECREASE:
            signed = -signed
        obligation_id = cast(UUID, item["obligation_id"])
        adjustment_deltas[obligation_id] += signed

    active_applications = tuple(
        PaymentApplication.objects.filter(
            organization_id=authorization.organization_id,
            obligation_id__in=obligation_ids,
        )
        .exclude(pk__in=reversed_targets.get(MovementReversal.TargetKind.APPLICATION, set()))
        .exclude(payment_id__in=reversed_targets.get(MovementReversal.TargetKind.PAYMENT, set()))
        .order_by("applied_at", "id")
    )
    applications: dict[UUID, list[PaymentApplication]] = {
        obligation_id: [] for obligation_id in obligation_ids
    }
    applied_totals = {obligation_id: ZERO for obligation_id in obligation_ids}
    for application in active_applications:
        applications[application.obligation_id].append(application)
        applied_totals[application.obligation_id] += application.amount

    active_refund_allocations = (
        RefundApplication.objects.filter(
            organization_id=authorization.organization_id,
            payment_application__obligation_id__in=obligation_ids,
        )
        .exclude(refund_id__in=reversed_targets.get(MovementReversal.TargetKind.REFUND, set()))
        .exclude(
            payment_application_id__in=reversed_targets.get(
                MovementReversal.TargetKind.APPLICATION, set()
            )
        )
        .exclude(
            payment_application__payment_id__in=reversed_targets.get(
                MovementReversal.TargetKind.PAYMENT, set()
            )
        )
        .values("payment_application_id", "payment_application__obligation_id")
        .annotate(total=Sum("amount"))
    )
    restored_totals = {obligation_id: ZERO for obligation_id in obligation_ids}
    restored_by_application: dict[UUID, Decimal] = {}
    for item in active_refund_allocations:
        restored = cast(Decimal, item["total"])
        application_id = cast(UUID, item["payment_application_id"])
        obligation_id = cast(UUID, item["payment_application__obligation_id"])
        restored_by_application[application_id] = restored
        restored_totals[obligation_id] += restored

    latest_revision_ids: dict[UUID, UUID] = {}
    for obligation_id, revision_id in (
        CollectionScheduleRevision.objects.filter(
            organization_id=authorization.organization_id,
            obligation_id__in=obligation_ids,
        )
        .order_by("obligation_id", "-revision", "-id")
        .values_list("obligation_id", "id")
    ):
        latest_revision_ids.setdefault(obligation_id, revision_id)
    due_groups: dict[UUID, list[CollectionScheduleDue]] = {
        obligation_id: [] for obligation_id in obligation_ids
    }
    for due in (
        CollectionScheduleDue.objects.select_related("schedule_revision")
        .filter(
            organization_id=authorization.organization_id,
            schedule_revision_id__in=tuple(latest_revision_ids.values()),
        )
        .order_by("obligation_id", "due_on", "position", "id")
    ):
        due_groups[due.obligation_id].append(due)

    adjusted_totals = {
        row.pk: amount(row.original_total + adjustment_deltas[row.pk]) for row in obligations
    }
    schedules = scheduling_port.contractual_schedules(
        authorization, tuple(row.root_reservation_id for row in obligations)
    )
    return _ObligationReadContext(
        adjusted_totals=adjusted_totals,
        applied_totals=applied_totals,
        restored_totals=restored_totals,
        dues={key: tuple(value) for key, value in due_groups.items()},
        applications={key: tuple(value) for key, value in applications.items()},
        restored_by_application=restored_by_application,
        schedules=schedules,
    )


def revise_schedule_authorized(
    authorization: TenantAuthorization,
    *,
    obligation_id: UUID | str,
    dues: Iterable[dict[str, object]],
    provenance: str,
    reason: str,
    idempotency_key: UUID,
) -> CollectionScheduleRevision:
    authorization.require(Capability.RECEIVABLES_MANAGE_SCHEDULE)
    if not reason.strip():
        raise invalid("La razón de la revisión es obligatoria.")
    materialized: list[dict[str, object]] = []
    for position, item in enumerate(dues, start=1):
        due_key = item.get("due_key") or uuid4()
        materialized.append(
            {
                "due_key": _uuid(cast(UUID | str, due_key), "El vencimiento"),
                "position": position,
                "amount": _positive_money(cast(Decimal | int | str, item["amount"])),
                "due_on": cast(date, item["due_on"]),
            }
        )
    payload = {
        "obligation_id": _uuid(obligation_id, "La obligación"),
        "dues": materialized,
        "provenance": provenance,
        "reason": reason.strip(),
    }
    replay = command_replay(
        authorization,
        command_type="revise_schedule",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        return CollectionScheduleRevision.objects.get(
            organization_id=authorization.organization_id, pk=replay
        )
    obligation = _obligation(authorization, obligation_id, lock=True)
    if provenance not in CollectionScheduleRevision.Provenance.values:
        raise invalid("La procedencia del calendario no es válida.")
    if materialized and sum(
        (cast(Decimal, item["amount"]) for item in materialized), ZERO
    ) > adjusted_obligation_amount(obligation):
        raise conflict(
            "schedule_total_mismatch",
            "La suma del calendario no puede exceder el importe ajustado de la obligación.",
        )
    if len({item["due_key"] for item in materialized}) != len(materialized):
        raise invalid("Los vencimientos no pueden repetirse dentro de una revisión.")
    active_by_due = {
        key: _sum(
            _active_applications(authorization.organization_id, obligation_id=obligation.pk).filter(
                due_key=key
            )
        )
        - _sum(
            _active_refund_allocations(
                authorization.organization_id, obligation_id=obligation.pk
            ).filter(payment_application__due_key=key)
        )
        for key in set(
            _active_applications(authorization.organization_id, obligation_id=obligation.pk)
            .exclude(due_key__isnull=True)
            .values_list("due_key", flat=True)
        )
    }
    new_by_due = {
        cast(UUID, item["due_key"]): cast(Decimal, item["amount"]) for item in materialized
    }
    for key, applied in active_by_due.items():
        if key not in new_by_due or new_by_due[key] < applied:
            raise conflict(
                "schedule_application_conflict",
                "La revisión no puede eliminar ni reducir un vencimiento por debajo "
                "de lo aplicado.",
            )
    last = CollectionScheduleRevision.objects.filter(
        organization_id=authorization.organization_id, obligation=obligation
    ).aggregate(value=Max("revision"))["value"]
    row = CollectionScheduleRevision.objects.create(
        organization_id=authorization.organization_id,
        obligation=obligation,
        revision=(cast(int | None, last) or 0) + 1,
        provenance=provenance,
        reason=reason.strip(),
        actor_membership_id=authorization.membership_id,
        published_at=timezone.now(),
    )
    CollectionScheduleDue.objects.bulk_create(
        [
            CollectionScheduleDue(
                organization_id=authorization.organization_id,
                schedule_revision=row,
                obligation=obligation,
                due_key=cast(UUID, item["due_key"]),
                position=cast(int, item["position"]),
                amount=cast(Decimal, item["amount"]),
                currency=obligation.currency,
                due_on=cast(date, item["due_on"]),
            )
            for item in materialized
        ]
    )
    complete_command(
        authorization,
        command_type="revise_schedule",
        idempotency_key=idempotency_key,
        payload=payload,
        result_type="schedule_revision",
        result_reference=row.pk,
    )
    _event(
        authorization,
        kind="schedule_revised",
        aggregate_type="schedule_revision",
        aggregate_id=row.pk,
        payload={"obligation_id": str(obligation.pk), "revision": row.revision},
        occurred_at=row.published_at,
    )
    return row


def record_adjustment_authorized(
    authorization: TenantAuthorization,
    *,
    obligation_id: UUID | str,
    direction: str,
    amount_value: Decimal | int | str,
    currency_value: str,
    reason: str,
    idempotency_key: UUID,
    correlation_reference: str = "",
    evidence_reference: str = "",
) -> ReceivableAdjustment:
    authorization.require(Capability.RECEIVABLES_RECORD_ADJUSTMENT)
    normalized_amount = _positive_money(amount_value)
    normalized_currency = _currency_code(currency_value)
    if direction not in ReceivableAdjustment.Direction.values:
        raise invalid("La dirección del ajuste no es válida.")
    if not reason.strip():
        raise invalid("La razón del ajuste es obligatoria.")
    payload = {
        "obligation_id": _uuid(obligation_id, "La obligación"),
        "direction": direction,
        "amount": normalized_amount,
        "currency": normalized_currency,
        "reason": reason.strip(),
        "correlation_reference": correlation_reference.strip(),
        "evidence_reference": evidence_reference.strip(),
    }
    replay = command_replay(
        authorization,
        command_type="record_adjustment",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        return ReceivableAdjustment.objects.get(
            organization_id=authorization.organization_id, pk=replay
        )
    obligation = _obligation(authorization, obligation_id, lock=True)
    if normalized_currency != obligation.currency:
        raise conflict("currency_mismatch", "El ajuste y la obligación tienen monedas distintas.")
    if (
        direction == ReceivableAdjustment.Direction.DECREASE
        and normalized_amount > obligation_balance(obligation)
    ):
        raise conflict("adjustment_exceeds_balance", "El ajuste no puede dejar un saldo negativo.")
    projected_adjusted_total = adjusted_obligation_amount(obligation) + (
        normalized_amount
        if direction == ReceivableAdjustment.Direction.INCREASE
        else -normalized_amount
    )
    if sum((due.amount for due in current_schedule(obligation)), ZERO) > projected_adjusted_total:
        raise conflict(
            "schedule_total_conflict",
            "Primero revise el calendario para que no exceda la obligación ajustada.",
        )
    row = ReceivableAdjustment.objects.create(
        organization_id=authorization.organization_id,
        obligation=obligation,
        direction=direction,
        amount=normalized_amount,
        currency=normalized_currency,
        reason=reason.strip(),
        correlation_reference=correlation_reference.strip(),
        evidence_reference=evidence_reference.strip(),
        recorded_by_membership_id=authorization.membership_id,
        occurred_at=timezone.now(),
    )
    complete_command(
        authorization,
        command_type="record_adjustment",
        idempotency_key=idempotency_key,
        payload=payload,
        result_type="adjustment",
        result_reference=row.pk,
    )
    _event(
        authorization,
        kind="adjustment_recorded",
        aggregate_type="adjustment",
        aggregate_id=row.pk,
        payload={
            "obligation_id": str(obligation.pk),
            "direction": row.direction,
            "amount": format(row.amount, ".2f"),
        },
        occurred_at=row.occurred_at,
    )
    return row


def _movement_target(
    authorization: TenantAuthorization,
    target_kind: str,
    target_id: UUID,
    *,
    lock: bool,
) -> ReceivedPayment | PaymentApplication | ReceivableAdjustment | RefundRecord:
    mapping: dict[str, type[Any]] = {
        MovementReversal.TargetKind.PAYMENT: ReceivedPayment,
        MovementReversal.TargetKind.APPLICATION: PaymentApplication,
        MovementReversal.TargetKind.ADJUSTMENT: ReceivableAdjustment,
        MovementReversal.TargetKind.REFUND: RefundRecord,
    }
    model = mapping.get(target_kind)
    if model is None:
        raise invalid("El tipo de movimiento no es válido.")
    rows = model.objects
    if lock:
        rows = rows.select_for_update()
    try:
        return cast(
            ReceivedPayment | PaymentApplication | ReceivableAdjustment | RefundRecord,
            rows.get(organization_id=authorization.organization_id, pk=target_id),
        )
    except model.DoesNotExist:
        raise unavailable("El movimiento") from None


def reverse_movement_authorized(
    authorization: TenantAuthorization,
    *,
    target_kind: str,
    target_id: UUID | str,
    reason: str,
    idempotency_key: UUID,
) -> MovementReversal:
    authorization.require(Capability.RECEIVABLES_REVERSE_MOVEMENT)
    canonical_target_id = _uuid(target_id, "El movimiento")
    if not reason.strip():
        raise invalid("La razón del reverso es obligatoria.")
    payload = {
        "target_kind": target_kind,
        "target_id": canonical_target_id,
        "reason": reason.strip(),
    }
    replay = command_replay(
        authorization,
        command_type="reverse_movement",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        return MovementReversal.objects.get(
            organization_id=authorization.organization_id, pk=replay
        )
    target_preview = _movement_target(authorization, target_kind, canonical_target_id, lock=False)
    obligation_ids: set[UUID] = set()
    payment_ids: set[UUID] = set()
    if isinstance(target_preview, PaymentApplication):
        obligation_ids.add(target_preview.obligation_id)
        payment_ids.add(target_preview.payment_id)
    elif isinstance(target_preview, ReceivableAdjustment):
        obligation_ids.add(target_preview.obligation_id)
    elif isinstance(target_preview, RefundRecord):
        if target_preview.obligation_id is not None:
            obligation_ids.add(target_preview.obligation_id)
        payment_ids.add(target_preview.payment_id)
    else:
        payment_ids.add(target_preview.pk)
    tuple(
        ReceivableObligation.objects.select_for_update()
        .filter(
            organization_id=authorization.organization_id,
            pk__in=sorted(obligation_ids, key=str),
        )
        .order_by("id")
    )
    tuple(
        ReceivedPayment.objects.select_for_update()
        .filter(
            organization_id=authorization.organization_id,
            pk__in=sorted(payment_ids, key=str),
        )
        .order_by("id")
    )
    target = _movement_target(authorization, target_kind, canonical_target_id, lock=True)
    if MovementReversal.objects.filter(
        organization_id=authorization.organization_id,
        target_kind=target_kind,
        target_id=canonical_target_id,
    ).exists():
        raise conflict("movement_already_reversed", "El movimiento ya fue reversado.")
    if isinstance(target, ReceivedPayment):
        if (
            _active_applications(authorization.organization_id, payment_id=target.pk).exists()
            or _active_refunds(authorization.organization_id, payment_id=target.pk).exists()
        ):
            raise conflict(
                "movement_has_dependents",
                "Debe corregir primero las aplicaciones y devoluciones activas del pago.",
            )
    elif (
        isinstance(target, PaymentApplication)
        and _active_refund_allocations(authorization.organization_id)
        .filter(payment_application=target)
        .exists()
    ):
        raise conflict(
            "movement_has_dependents",
            "Debe corregir primero la devolución vinculada a la aplicación.",
        )
    if (
        isinstance(target, ReceivableAdjustment)
        and target.direction == ReceivableAdjustment.Direction.INCREASE
    ):
        obligation = _obligation(authorization, target.obligation_id)
        projected_adjusted_total = adjusted_obligation_amount(obligation) - target.amount
        if (
            sum((due.amount for due in current_schedule(obligation)), ZERO)
            > projected_adjusted_total
        ):
            raise conflict(
                "schedule_total_conflict",
                "Primero revise el calendario para que no exceda la obligación ajustada.",
            )
    amount_value = target.amount
    currency_value = target.currency
    row = MovementReversal.objects.create(
        organization_id=authorization.organization_id,
        target_kind=target_kind,
        target_id=canonical_target_id,
        amount=amount_value,
        currency=currency_value,
        reason=reason.strip(),
        reversed_by_membership_id=authorization.membership_id,
        reversed_at=timezone.now(),
    )
    complete_command(
        authorization,
        command_type="reverse_movement",
        idempotency_key=idempotency_key,
        payload=payload,
        result_type="reversal",
        result_reference=row.pk,
    )
    _event(
        authorization,
        kind="movement_reversed",
        aggregate_type="reversal",
        aggregate_id=row.pk,
        payload={
            "target_kind": target_kind,
            "target_id": str(canonical_target_id),
            "amount": format(row.amount, ".2f"),
        },
        occurred_at=row.reversed_at,
    )
    return row


def record_refund_authorized(
    authorization: TenantAuthorization,
    *,
    payment_id: UUID | str,
    amount_value: Decimal | int | str,
    currency_value: str,
    refunded_at: datetime,
    method: str,
    reference: str,
    reason: str,
    idempotency_key: UUID,
    allocations: Iterable[dict[str, object]] = (),
    obligation_id: UUID | str | None = None,
    evidence_reference: str = "",
) -> RefundRecord:
    authorization.require(Capability.RECEIVABLES_RECORD_REFUND)
    normalized_amount = _positive_money(amount_value)
    normalized_currency = _currency_code(currency_value)
    if refunded_at.tzinfo is None:
        raise invalid("La fecha de devolución debe incluir zona horaria.")
    if method not in ReceivedPayment.Method.values:
        raise invalid("El método de devolución no es válido.")
    if not reason.strip():
        raise invalid("La razón de la devolución es obligatoria.")
    materialized = tuple(
        {
            "application_id": _uuid(cast(UUID | str, item["application_id"]), "La aplicación"),
            "amount": _positive_money(cast(Decimal | int | str, item["amount"])),
        }
        for item in allocations
    )
    payload = {
        "payment_id": _uuid(payment_id, "El pago"),
        "obligation_id": (
            _uuid(obligation_id, "La obligación") if obligation_id is not None else None
        ),
        "amount": normalized_amount,
        "currency": normalized_currency,
        "refunded_at": refunded_at,
        "method": method,
        "reference": reference.strip(),
        "reason": reason.strip(),
        "allocations": materialized,
        "evidence_reference": evidence_reference.strip(),
    }
    replay = command_replay(
        authorization,
        command_type="record_refund",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        return RefundRecord.objects.get(organization_id=authorization.organization_id, pk=replay)
    application_rows = list(
        PaymentApplication.objects.filter(
            organization_id=authorization.organization_id,
            pk__in=[item["application_id"] for item in materialized],
        )
    )
    if len(application_rows) != len(materialized):
        raise unavailable("La aplicación")
    obligation_ids = sorted(
        {row.obligation_id for row in application_rows}
        | ({_uuid(obligation_id, "La obligación")} if obligation_id is not None else set()),
        key=str,
    )
    locked_obligations = list(
        ReceivableObligation.objects.select_for_update().filter(
            organization_id=authorization.organization_id, pk__in=obligation_ids
        )
    )
    if len(locked_obligations) != len(obligation_ids):
        raise unavailable("La obligación")
    payment = _payment(authorization, payment_id, lock=True)
    if normalized_currency != payment.currency:
        raise conflict("currency_mismatch", "La devolución y el pago tienen monedas distintas.")
    application_rows = list(
        PaymentApplication.objects.select_for_update().filter(
            organization_id=authorization.organization_id,
            pk__in=[item["application_id"] for item in materialized],
            payment=payment,
        )
    )
    if len(application_rows) != len(materialized):
        raise unavailable("La aplicación")
    if normalized_amount > amount(
        payment.amount - _sum(_active_refunds(authorization.organization_id, payment_id=payment.pk))
    ):
        raise conflict(
            "refund_exceeds_available", "La devolución supera el dinero disponible para devolver."
        )
    allocation_by_id = {
        cast(UUID, item["application_id"]): cast(Decimal, item["amount"]) for item in materialized
    }
    allocation_total = sum(allocation_by_id.values(), ZERO)
    if allocation_total > normalized_amount:
        raise conflict(
            "refund_allocation_exceeds_amount",
            "Las asignaciones de devolución superan el importe devuelto.",
        )
    for application in application_rows:
        active_amount = (
            ZERO
            if application.pk
            in _reversed_ids(authorization.organization_id, MovementReversal.TargetKind.APPLICATION)
            else application.amount
        )
        already_restored = _sum(
            _active_refund_allocations(authorization.organization_id).filter(
                payment_application=application
            )
        )
        if allocation_by_id[application.pk] > amount(active_amount - already_restored):
            raise conflict(
                "refund_application_exceeds_available",
                "La devolución supera la aplicación activa seleccionada.",
            )
    if normalized_amount > amount(payment_available(payment) + allocation_total):
        raise conflict(
            "refund_exceeds_unapplied",
            "La devolución debe identificar las aplicaciones que restituye.",
        )
    explicit_obligation = (
        next(
            (row for row in locked_obligations if row.pk == _uuid(obligation_id, "La obligación")),
            None,
        )
        if obligation_id is not None
        else None
    )
    if explicit_obligation is not None and any(
        row.obligation_id != explicit_obligation.pk for row in application_rows
    ):
        raise conflict("refund_context_mismatch", "La devolución mezcla obligaciones distintas.")
    row = RefundRecord.objects.create(
        organization_id=authorization.organization_id,
        payment=payment,
        obligation=explicit_obligation,
        amount=normalized_amount,
        currency=normalized_currency,
        refunded_at=refunded_at,
        method=method,
        reference=reference.strip(),
        reason=reason.strip(),
        evidence_reference=evidence_reference.strip(),
        recorded_by_membership_id=authorization.membership_id,
    )
    RefundApplication.objects.bulk_create(
        [
            RefundApplication(
                organization_id=authorization.organization_id,
                refund=row,
                payment_application=application,
                amount=allocation_by_id[application.pk],
                currency=normalized_currency,
            )
            for application in application_rows
        ]
    )
    complete_command(
        authorization,
        command_type="record_refund",
        idempotency_key=idempotency_key,
        payload=payload,
        result_type="refund",
        result_reference=row.pk,
    )
    _event(
        authorization,
        kind="refund_recorded",
        aggregate_type="refund",
        aggregate_id=row.pk,
        payload={
            "payment_id": str(payment.pk),
            "amount": format(row.amount, ".2f"),
            "external_execution": True,
        },
        occurred_at=row.refunded_at,
    )
    return row


def issue_receipt_authorized(
    authorization: TenantAuthorization,
    *,
    payment_id: UUID | str,
    idempotency_key: UUID,
) -> Receipt:
    authorization.require(Capability.RECEIVABLES_ISSUE_RECEIPT)
    payload = {"payment_id": _uuid(payment_id, "El pago")}
    replay = command_replay(
        authorization,
        command_type="issue_receipt",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        return Receipt.objects.get(organization_id=authorization.organization_id, pk=replay)
    payment = _payment(authorization, payment_id, lock=True)
    organization = contractual_organization(authorization.organization_id)
    local_now = timezone.now().astimezone(ZoneInfo(organization.timezone_name))
    year = local_now.year
    _lock_idempotency(authorization.organization_id, "receipt_sequence", UUID(int=year))
    sequence, _ = ReceiptSequence.objects.get_or_create(
        organization_id=authorization.organization_id,
        year=year,
        defaults={"next_value": 1},
    )
    sequence = ReceiptSequence.objects.select_for_update().get(pk=sequence.pk)
    number = sequence.next_value
    sequence.next_value += 1
    sequence.save(update_fields=["next_value", "updated_at"])
    applications = tuple(
        _active_applications(authorization.organization_id, payment_id=payment.pk).order_by(
            "applied_at", "id"
        )
    )
    obligation_ids = {row.obligation_id for row in applications}
    obligation = (
        ReceivableObligation.objects.get(
            organization_id=authorization.organization_id, pk=next(iter(obligation_ids))
        )
        if len(obligation_ids) == 1
        else None
    )
    receipt_id = uuid4()
    visible_number = f"RC-{year}-{number:06d}"
    snapshot: dict[str, object] = {
        "schema_version": "receivables-receipt-v1",
        "label": "recibo/comprobante de cobro — no factura",
        "receipt_id": str(receipt_id),
        "visible_number": visible_number,
        "organization": {"id": str(organization.id), "name": organization.name},
        "payment": {
            "id": str(payment.pk),
            "amount": format(payment.amount, ".2f"),
            "currency": payment.currency,
            "reported_at": payment.reported_at.isoformat(),
            "method": payment.method,
            "reference": payment.reference,
        },
        "counterparty_person_id": str(payment.counterparty_person_id),
        "root_reservation_id": (
            str(payment.root_reservation_id) if payment.root_reservation_id else None
        ),
        "applications": [
            {
                "id": str(row.pk),
                "obligation_id": str(row.obligation_id),
                "due_key": str(row.due_key) if row.due_key else None,
                "amount": format(row.amount, ".2f"),
                "applied_at": row.applied_at.isoformat(),
            }
            for row in applications
        ],
        "issued_at": local_now.isoformat(),
    }
    try:
        artifact = documents_port.request_receipt_pdf(
            authorization,
            receipt_id=receipt_id,
            snapshot=snapshot,
            correlation_id=f"receipt:{receipt_id}",
        )
    except documents_port.DocumentsPortError as error:
        raise conflict("document_platform_unavailable", error.detail) from error
    row = Receipt.objects.create(
        id=receipt_id,
        organization_id=authorization.organization_id,
        payment=payment,
        obligation=obligation,
        year=year,
        sequence=number,
        visible_number=visible_number,
        snapshot=snapshot,
        snapshot_sha256=payload_hash(snapshot),
        issued_by_membership_id=authorization.membership_id,
        issued_at=timezone.now(),
        document_artifact_id=artifact.id,
    )
    complete_command(
        authorization,
        command_type="issue_receipt",
        idempotency_key=idempotency_key,
        payload=payload,
        result_type="receipt",
        result_reference=row.pk,
    )
    _event(
        authorization,
        kind="receipt_issued",
        aggregate_type="receipt",
        aggregate_id=row.pk,
        payload={"visible_number": row.visible_number, "payment_id": str(payment.pk)},
        occurred_at=row.issued_at,
    )
    return row


def _payment_availability_map(
    organization_id: UUID,
    payments: tuple[ReceivedPayment, ...],
    reversed_targets: dict[str, set[UUID]],
) -> dict[UUID, Decimal]:
    payment_ids = tuple(row.pk for row in payments)
    if not payment_ids:
        return {}
    active_applications = (
        PaymentApplication.objects.filter(
            organization_id=organization_id, payment_id__in=payment_ids
        )
        .exclude(pk__in=reversed_targets.get(MovementReversal.TargetKind.APPLICATION, set()))
        .exclude(payment_id__in=reversed_targets.get(MovementReversal.TargetKind.PAYMENT, set()))
    )
    applied = {
        cast(UUID, item["payment_id"]): cast(Decimal, item["total"])
        for item in active_applications.values("payment_id").annotate(total=Sum("amount"))
    }
    active_refunds = (
        RefundRecord.objects.filter(organization_id=organization_id, payment_id__in=payment_ids)
        .exclude(pk__in=reversed_targets.get(MovementReversal.TargetKind.REFUND, set()))
        .exclude(payment_id__in=reversed_targets.get(MovementReversal.TargetKind.PAYMENT, set()))
    )
    refunded = {
        cast(UUID, item["payment_id"]): cast(Decimal, item["total"])
        for item in active_refunds.values("payment_id").annotate(total=Sum("amount"))
    }
    restored = {
        cast(UUID, item["payment_application__payment_id"]): cast(Decimal, item["total"])
        for item in RefundApplication.objects.filter(
            organization_id=organization_id,
            payment_application__payment_id__in=payment_ids,
        )
        .exclude(refund_id__in=reversed_targets.get(MovementReversal.TargetKind.REFUND, set()))
        .exclude(
            payment_application_id__in=reversed_targets.get(
                MovementReversal.TargetKind.APPLICATION, set()
            )
        )
        .exclude(
            payment_application__payment_id__in=reversed_targets.get(
                MovementReversal.TargetKind.PAYMENT, set()
            )
        )
        .values("payment_application__payment_id")
        .annotate(total=Sum("amount"))
    }
    reversed_payments = reversed_targets.get(MovementReversal.TargetKind.PAYMENT, set())
    return {
        row.pk: (
            ZERO
            if row.pk in reversed_payments
            else amount(
                row.amount
                - applied.get(row.pk, ZERO)
                - refunded.get(row.pk, ZERO)
                + restored.get(row.pk, ZERO)
            )
        )
        for row in payments
    }


def payment_data(
    row: ReceivedPayment, *, available_amount: Decimal | None = None
) -> dict[str, object]:
    return {
        "id": row.pk,
        "counterparty_person_id": row.counterparty_person_id,
        "root_reservation_id": row.root_reservation_id,
        "event_request_id": row.event_request_id,
        "amount": row.amount,
        "currency": row.currency,
        "reported_at": row.reported_at,
        "method": row.method,
        "reference": row.reference,
        "observation": row.observation,
        "provenance": row.provenance,
        "evidence_level": row.evidence_level,
        "possible_duplicate": row.possible_duplicate,
        "unapplied_amount": (
            payment_available(row) if available_amount is None else available_amount
        ),
        "created_at": row.created_at,
    }


def application_data(
    row: PaymentApplication,
    *,
    reversal_ids: dict[UUID, UUID] | None = None,
    restored_totals: dict[UUID, Decimal] | None = None,
) -> dict[str, object]:
    if reversal_ids is None:
        reversed_row = MovementReversal.objects.filter(
            organization_id=row.organization_id,
            target_kind=MovementReversal.TargetKind.APPLICATION,
            target_id=row.pk,
        ).first()
        reversal_id = reversed_row.pk if reversed_row else None
    else:
        reversal_id = reversal_ids.get(row.pk)
    restored = (
        _sum(_active_refund_allocations(row.organization_id).filter(payment_application=row))
        if restored_totals is None
        else restored_totals.get(row.pk, ZERO)
    )
    return {
        "id": row.pk,
        "payment_id": row.payment_id,
        "obligation_id": row.obligation_id,
        "due_key": row.due_key,
        "amount": row.amount,
        "currency": row.currency,
        "applied_at": row.applied_at,
        "restored_by_refunds": restored,
        "reversed": reversal_id is not None,
        "reversal_id": reversal_id,
    }


def payments_data_authorized(authorization: TenantAuthorization) -> dict[str, object]:
    payments = tuple(
        ReceivedPayment.objects.filter(organization_id=authorization.organization_id).order_by(
            "-reported_at", "-id"
        )
    )
    reversed_targets: dict[str, set[UUID]] = {}
    for target_kind, target_id in MovementReversal.objects.filter(
        organization_id=authorization.organization_id
    ).values_list("target_kind", "target_id"):
        reversed_targets.setdefault(target_kind, set()).add(target_id)
    availability = _payment_availability_map(
        authorization.organization_id, payments, reversed_targets
    )
    return {
        "payments": [payment_data(row, available_amount=availability[row.pk]) for row in payments]
    }


def payment_detail_authorized(
    authorization: TenantAuthorization, payment_id: UUID | str
) -> dict[str, object]:
    payment = _payment(authorization, payment_id)
    applications = tuple(
        PaymentApplication.objects.filter(
            organization_id=authorization.organization_id, payment=payment
        ).order_by("applied_at", "id")
    )
    application_ids = tuple(row.pk for row in applications)
    reversal_ids = {
        target_id: reversal_id
        for target_id, reversal_id in MovementReversal.objects.filter(
            organization_id=authorization.organization_id,
            target_kind=MovementReversal.TargetKind.APPLICATION,
            target_id__in=application_ids,
        ).values_list("target_id", "id")
    }
    restored_totals = {
        cast(UUID, item["payment_application_id"]): cast(Decimal, item["total"])
        for item in _active_refund_allocations(authorization.organization_id)
        .filter(payment_application_id__in=application_ids)
        .values("payment_application_id")
        .annotate(total=Sum("amount"))
    }
    return {
        **payment_data(payment),
        "applications": [
            application_data(
                application,
                reversal_ids=reversal_ids,
                restored_totals=restored_totals,
            )
            for application in applications
        ],
    }


def _aging_bucket(days_overdue: int | None, *, has_due: bool) -> str:
    if not has_due:
        return "unscheduled"
    if days_overdue is None or days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "1_30"
    if days_overdue <= 60:
        return "31_60"
    if days_overdue <= 90:
        return "61_90"
    return "over_90"


def obligation_aging(
    row: ReceivableObligation,
    local_date: date,
    *,
    context: _ObligationReadContext | None = None,
) -> list[dict[str, object]]:
    balance = (
        obligation_balance(row)
        if context is None
        else amount(
            context.adjusted_totals[row.pk]
            - context.applied_totals[row.pk]
            + context.restored_totals[row.pk]
        )
    )
    if balance <= ZERO:
        return []
    dues = current_schedule(row) if context is None else context.dues[row.pk]
    if not dues:
        return [
            {
                "due_key": None,
                "due_on": None,
                "open_amount": balance,
                "days_overdue": None,
                "bucket": "unscheduled",
            }
        ]
    applications = (
        tuple(_active_applications(row.organization_id, obligation_id=row.pk))
        if context is None
        else context.applications[row.pk]
    )
    restored_by_application = (
        {
            application.pk: _sum(
                _active_refund_allocations(row.organization_id).filter(
                    payment_application=application
                )
            )
            for application in applications
        }
        if context is None
        else context.restored_by_application
    )
    targeted: dict[UUID, Decimal] = {}
    untargeted = ZERO
    for application in applications:
        effective = amount(application.amount - restored_by_application[application.pk])
        if application.due_key is None:
            untargeted += effective
        else:
            targeted[application.due_key] = targeted.get(application.due_key, ZERO) + effective
    result: list[dict[str, object]] = []
    for due in dues:
        open_amount = amount(due.amount - targeted.get(due.due_key, ZERO))
        from_untargeted = min(open_amount, untargeted)
        open_amount = amount(open_amount - from_untargeted)
        untargeted = amount(untargeted - from_untargeted)
        if open_amount <= ZERO:
            continue
        days_overdue = (local_date - due.due_on).days
        result.append(
            {
                "due_key": due.due_key,
                "due_on": due.due_on,
                "open_amount": open_amount,
                "days_overdue": days_overdue,
                "bucket": _aging_bucket(days_overdue, has_due=True),
            }
        )
    scheduled_open = sum((cast(Decimal, item["open_amount"]) for item in result), ZERO)
    residual = amount(balance - scheduled_open)
    if residual > ZERO:
        result.append(
            {
                "due_key": None,
                "due_on": None,
                "open_amount": residual,
                "days_overdue": None,
                "bucket": "unscheduled",
            }
        )
    return result


def obligation_data(
    authorization: TenantAuthorization,
    row: ReceivableObligation,
    *,
    summary: bool = False,
    context: _ObligationReadContext | None = None,
) -> dict[str, object]:
    applied = (
        _sum(_active_applications(row.organization_id, obligation_id=row.pk))
        if context is None
        else context.applied_totals[row.pk]
    )
    restored = (
        _sum(_active_refund_allocations(row.organization_id, obligation_id=row.pk))
        if context is None
        else context.restored_totals[row.pk]
    )
    net_applied = amount(applied - restored)
    adjusted_total = (
        adjusted_obligation_amount(row) if context is None else context.adjusted_totals[row.pk]
    )
    balance = amount(adjusted_total - applied + restored)
    schedule = (
        scheduling_port.contractual_schedule(authorization, row.root_reservation_id)
        if context is None
        else context.schedules[row.root_reservation_id]
    )
    base: dict[str, object] = {
        "id": row.pk,
        "root_reservation_id": row.root_reservation_id,
        "current_reservation_id": schedule.current_reservation_id,
        "event_request_id": row.event_request_id,
        "counterparty_person_id": row.counterparty_person_id,
        "counterparty_name": row.counterparty_name_snapshot,
        "currency": row.currency,
        "original_total": row.original_total,
        "adjusted_total": adjusted_total,
        "applied_total": net_applied,
        "balance": balance,
        "derived_status": (
            "satisfied" if balance == ZERO else "partial" if net_applied > ZERO else "open"
        ),
        "reservation_status": schedule.status,
        "financial_review_required": schedule.status == "cancelled" and balance > ZERO,
    }
    if summary:
        return base
    due_rows = current_schedule(row) if context is None else context.dues[row.pk]
    base.update(
        {
            "quotation_version_id": row.quotation_version_id,
            "quotation_visible_number": row.quotation_visible_number,
            "quotation_version": row.quotation_version,
            "subtotal": row.subtotal,
            "discount_total": row.discount_total,
            "confirmed_at": row.confirmed_at,
            "schedule_configured": bool(due_rows),
            "schedule": [
                {
                    "id": due.pk,
                    "due_key": due.due_key,
                    "position": due.position,
                    "amount": due.amount,
                    "currency": due.currency,
                    "due_on": due.due_on,
                    "revision": due.schedule_revision.revision,
                }
                for due in due_rows
            ],
        }
    )
    return base


def portfolio_authorized(authorization: TenantAuthorization) -> dict[str, object]:
    rows = tuple(
        ReceivableObligation.objects.filter(organization_id=authorization.organization_id).order_by(
            "confirmed_at", "id"
        )
    )
    context = _obligation_read_context(authorization, rows)
    obligations = [obligation_data(authorization, row, context=context) for row in rows]
    return {
        "currency_groups": [
            {
                "currency": currency_value,
                "original_total": sum(
                    (
                        cast(Decimal, item["original_total"])
                        for item in obligations
                        if item["currency"] == currency_value
                    ),
                    ZERO,
                ),
                "balance": sum(
                    (
                        cast(Decimal, item["balance"])
                        for item in obligations
                        if item["currency"] == currency_value
                    ),
                    ZERO,
                ),
            }
            for currency_value in sorted({cast(str, item["currency"]) for item in obligations})
        ],
        "obligations": obligations,
    }


def aging_authorized(authorization: TenantAuthorization) -> dict[str, object]:
    organization = contractual_organization(authorization.organization_id)
    local_date = timezone.now().astimezone(ZoneInfo(organization.timezone_name)).date()
    obligations = tuple(
        ReceivableObligation.objects.filter(organization_id=authorization.organization_id).order_by(
            "confirmed_at", "id"
        )
    )
    context = _obligation_read_context(authorization, obligations)
    entries: list[dict[str, object]] = []
    for obligation in obligations:
        for aging in obligation_aging(obligation, local_date, context=context):
            entries.append(
                {
                    "obligation_id": obligation.pk,
                    "root_reservation_id": obligation.root_reservation_id,
                    "counterparty_person_id": obligation.counterparty_person_id,
                    "counterparty_name": obligation.counterparty_name_snapshot,
                    "currency": obligation.currency,
                    **aging,
                }
            )
    buckets: dict[str, dict[str, Decimal]] = {}
    for entry in entries:
        bucket = cast(str, entry["bucket"])
        currency_value = cast(str, entry["currency"])
        buckets.setdefault(bucket, {}).setdefault(currency_value, ZERO)
        buckets[bucket][currency_value] += cast(Decimal, entry["open_amount"])
    return {"as_of": local_date, "buckets": buckets, "entries": entries}


def statement_authorized(
    authorization: TenantAuthorization, obligation_id: UUID | str
) -> dict[str, object]:
    row = _obligation(authorization, obligation_id)
    context = _obligation_read_context(authorization, (row,))
    statement = obligation_data(authorization, row, context=context)
    payments = tuple(
        ReceivedPayment.objects.filter(
            Q(root_reservation_id=row.root_reservation_id) | Q(applications__obligation=row),
            organization_id=authorization.organization_id,
        )
        .distinct()
        .order_by("reported_at", "id")
    )
    applications = tuple(
        PaymentApplication.objects.filter(
            organization_id=authorization.organization_id, obligation=row
        ).order_by("applied_at", "id")
    )
    reversal_rows = tuple(
        MovementReversal.objects.filter(organization_id=authorization.organization_id).order_by(
            "reversed_at", "id"
        )
    )
    reversed_targets: dict[str, set[UUID]] = {}
    reversal_ids: dict[UUID, UUID] = {}
    for reversal in reversal_rows:
        reversed_targets.setdefault(reversal.target_kind, set()).add(reversal.target_id)
        if reversal.target_kind == MovementReversal.TargetKind.APPLICATION:
            reversal_ids[reversal.target_id] = reversal.pk
    payment_availability = _payment_availability_map(
        authorization.organization_id, payments, reversed_targets
    )
    statement["payments"] = [
        payment_data(payment, available_amount=payment_availability[payment.pk])
        for payment in payments
    ]
    statement["applications"] = [
        application_data(
            application,
            reversal_ids=reversal_ids,
            restored_totals=context.restored_by_application,
        )
        for application in applications
    ]
    adjustments = tuple(
        ReceivableAdjustment.objects.filter(
            organization_id=authorization.organization_id, obligation=row
        ).order_by("occurred_at", "id")
    )
    statement["adjustments"] = [
        {
            "id": adjustment.pk,
            "direction": adjustment.direction,
            "amount": adjustment.amount,
            "currency": adjustment.currency,
            "reason": adjustment.reason,
            "occurred_at": adjustment.occurred_at,
        }
        for adjustment in adjustments
    ]
    payment_ids = tuple(payment.pk for payment in payments)
    refunds = tuple(
        RefundRecord.objects.filter(
            Q(obligation=row) | Q(payment_id__in=payment_ids),
            organization_id=authorization.organization_id,
        )
        .distinct()
        .order_by("refunded_at", "id")
    )
    statement["refunds"] = [
        {
            "id": refund.pk,
            "payment_id": refund.payment_id,
            "amount": refund.amount,
            "currency": refund.currency,
            "reason": refund.reason,
            "refunded_at": refund.refunded_at,
        }
        for refund in refunds
    ]
    relevant_targets: dict[str, set[UUID]] = {
        MovementReversal.TargetKind.PAYMENT: set(payment_ids),
        MovementReversal.TargetKind.APPLICATION: {item.pk for item in applications},
        MovementReversal.TargetKind.ADJUSTMENT: {item.pk for item in adjustments},
        MovementReversal.TargetKind.REFUND: {item.pk for item in refunds},
    }
    statement["reversals"] = [
        {
            "id": reversal.pk,
            "target_kind": reversal.target_kind,
            "target_id": reversal.target_id,
            "amount": reversal.amount,
            "currency": reversal.currency,
            "reason": reversal.reason,
            "reversed_at": reversal.reversed_at,
        }
        for reversal in reversal_rows
        if reversal.target_id in relevant_targets.get(reversal.target_kind, set())
    ]
    statement["receipts"] = [
        {
            "id": receipt.pk,
            "visible_number": receipt.visible_number,
            "payment_id": receipt.payment_id,
            "snapshot_sha256": receipt.snapshot_sha256,
            "issued_at": receipt.issued_at,
            "document_artifact_id": receipt.document_artifact_id,
        }
        for receipt in Receipt.objects.filter(
            Q(obligation=row) | Q(payment_id__in=payment_ids),
            organization_id=authorization.organization_id,
        )
        .distinct()
        .order_by("issued_at", "id")
    ]
    return statement


def receivables_capabilities(actor: User, organization_reference: UUID | str) -> tuple[str, ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.ORGANIZATION_ACCESS
    ) as authorization:
        return tuple(
            capability.value
            for capability in Capability
            if capability.value.startswith("receivables:")
            and capability in authorization_capabilities(authorization)
        )


def authorization_capabilities(
    authorization: TenantAuthorization,
) -> frozenset[Capability]:
    from claridez.organizations.capabilities import capabilities_for_role

    return capabilities_for_role(authorization.role)


def portfolio(actor: User, organization_reference: UUID | str) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RECEIVABLES_READ
    ) as authorization:
        return portfolio_authorized(authorization)


def aging(actor: User, organization_reference: UUID | str) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RECEIVABLES_READ
    ) as authorization:
        return aging_authorized(authorization)


def read_obligation(
    actor: User, organization_reference: UUID | str, *, obligation_id: UUID | str
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RECEIVABLES_READ
    ) as authorization:
        return obligation_data(authorization, _obligation(authorization, obligation_id))


def read_statement(
    actor: User, organization_reference: UUID | str, *, obligation_id: UUID | str
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RECEIVABLES_READ
    ) as authorization:
        return statement_authorized(authorization, obligation_id)


def commercial_summary(
    actor: User,
    organization_reference: UUID | str,
    *,
    root_reservation_id: UUID | str,
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RECEIVABLES_READ_SUMMARY
    ) as authorization:
        root_id = _uuid(root_reservation_id, "La raíz de reserva")
        schedule = scheduling_port.contractual_schedule(authorization, root_id)
        row = ReceivableObligation.objects.filter(
            organization_id=authorization.organization_id,
            root_reservation_id=root_id,
            event_request_id=schedule.event_request_id,
        ).first()
        if row is None:
            raise unavailable("La obligación")
        return obligation_data(authorization, row, summary=True)
