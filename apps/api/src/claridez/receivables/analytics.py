"""Métricas P15 bajo autoridad Receivables; lecturas batch y bitemporales."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from claridez.organizations.analytics_contracts import (
    SourceMetricQuery,
    SourceMetricResult,
    evidence_watermark,
)
from claridez.organizations.analytics_values import MetricAccumulator
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .metric_inputs import INPUTS
from .models import (
    CollectionScheduleDue,
    CollectionScheduleRevision,
    LegacyEvidenceReview,
    MovementReversal,
    PaymentApplication,
    ReceivableAdjustment,
    ReceivableObligation,
    ReceivedPayment,
    RefundApplication,
    RefundRecord,
)
from .services import _ObligationReadContext, obligation_aging

ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class _Ledger:
    obligations: tuple[ReceivableObligation, ...]
    payments: tuple[ReceivedPayment, ...]
    applications: tuple[PaymentApplication, ...]
    adjustments: tuple[ReceivableAdjustment, ...]
    refunds: tuple[RefundRecord, ...]
    allocations: tuple[RefundApplication, ...]
    reversals: tuple[MovementReversal, ...]
    revisions: tuple[CollectionScheduleRevision, ...]
    dues: tuple[CollectionScheduleDue, ...]
    legacy_missing: bool


def _references(ledger: _Ledger) -> tuple[str, ...]:
    return tuple(
        f"receivables.{type(row).__name__}:{row.pk}"
        for rows in (
            ledger.obligations,
            ledger.payments,
            ledger.applications,
            ledger.adjustments,
            ledger.refunds,
            ledger.allocations,
            ledger.reversals,
            ledger.revisions,
            ledger.dues,
        )
        for row in rows
    )


def _load(authorization: TenantAuthorization, cutoff: datetime) -> _Ledger:
    """Once per cutoff, never once per obligation/payment/metric row."""
    oid = authorization.organization_id
    return _Ledger(
        tuple(
            ReceivableObligation.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
                "id",
                "currency",
                "original_total",
                "confirmed_at",
                "created_at",
            )
        ),
        tuple(
            ReceivedPayment.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
                "id",
                "currency",
                "amount",
                "reported_at",
                "method",
                "provenance",
                "created_at",
            )
        ),
        tuple(
            PaymentApplication.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
                "id",
                "payment_id",
                "obligation_id",
                "amount",
                "currency",
                "due_key",
                "applied_at",
            )
        ),
        tuple(
            ReceivableAdjustment.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
                "id",
                "obligation_id",
                "amount",
                "currency",
                "direction",
                "occurred_at",
            )
        ),
        tuple(
            RefundRecord.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
                "id",
                "payment_id",
                "amount",
                "currency",
                "refunded_at",
            )
        ),
        tuple(
            RefundApplication.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
                "id",
                "refund_id",
                "payment_application_id",
                "amount",
                "currency",
            )
        ),
        tuple(
            MovementReversal.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
                "id",
                "target_kind",
                "target_id",
                "amount",
                "currency",
                "reversed_at",
            )
        ),
        tuple(
            CollectionScheduleRevision.objects.filter(
                organization_id=oid,
                created_at__lte=cutoff,
            )
            .only("id", "obligation_id", "revision", "published_at")
            .order_by("revision", "id")
        ),
        tuple(
            CollectionScheduleDue.objects.filter(organization_id=oid, created_at__lte=cutoff)
            .only(
                "id",
                "schedule_revision_id",
                "obligation_id",
                "due_key",
                "amount",
                "currency",
                "due_on",
                "position",
            )
            .order_by("due_on", "position", "id")
        ),
        LegacyEvidenceReview.objects.filter(organization_id=oid, created_at__lte=cutoff).exists(),
    )


def _facts(query: SourceMetricQuery, ledger: _Ledger) -> SourceMetricResult:
    assert query.period_start is not None and query.period_end is not None
    period_start, period_end = query.period_start, query.period_end
    acc = MetricAccumulator(query, scale=2)

    def add(at: datetime, value: Decimal, currency: str, **dimensions: object) -> None:
        if period_start <= at < period_end:
            acc.add(value, {"currency": currency, **dimensions}, at=at)

    metric = query.source_metric_id.removeprefix("receivables.")
    if metric == "obligation_original_amount":
        for obligation in ledger.obligations:
            add(obligation.confirmed_at, obligation.original_total, obligation.currency)
    elif metric == "payment_received_amount":
        for payment in ledger.payments:
            add(
                payment.reported_at,
                payment.amount,
                payment.currency,
                method=payment.method,
                provenance=payment.provenance,
            )
    elif metric == "refund_recorded_amount":
        for refund in ledger.refunds:
            add(refund.refunded_at, refund.amount, refund.currency)
    elif metric == "movement_reversal_amount_by_target":
        targets = {
            **{("payment", row.pk): row.currency for row in ledger.payments},
            **{("application", row.pk): row.currency for row in ledger.applications},
            **{("adjustment", row.pk): row.currency for row in ledger.adjustments},
            **{("refund", row.pk): row.currency for row in ledger.refunds},
        }
        for reversal in ledger.reversals:
            if targets.get((reversal.target_kind, reversal.target_id)) != reversal.currency:
                acc.reasons.add("reversal_target_not_visible_or_currency_mismatch")
                continue
            add(
                reversal.reversed_at,
                reversal.amount,
                reversal.currency,
                target_kind=reversal.target_kind,
            )
    elif metric == "adjustment_net_amount":
        adjustments = {row.pk: row for row in ledger.adjustments}
        for adjustment in ledger.adjustments:
            sign = 1 if adjustment.direction == "increase" else -1
            add(
                adjustment.occurred_at,
                sign * adjustment.amount,
                adjustment.currency,
                direction=adjustment.direction,
            )
        for reversal in ledger.reversals:
            if reversal.target_kind != "adjustment":
                continue
            target = adjustments.get(reversal.target_id)
            if target is None or target.currency != reversal.currency:
                acc.reasons.add("adjustment_target_not_visible_or_currency_mismatch")
                continue
            direction = "decrease" if target.direction == "increase" else "increase"
            add(
                reversal.reversed_at,
                (-1 if direction == "decrease" else 1) * reversal.amount,
                reversal.currency,
                direction=direction,
            )
    elif metric == "application_net_amount":
        for application in ledger.applications:
            add(
                application.applied_at,
                application.amount,
                application.currency,
                effect_kind="application",
            )
        refunds = {row.pk: row for row in ledger.refunds}
        allocated: dict[UUID, Decimal] = defaultdict(Decimal)
        for allocation in ledger.allocations:
            parent = refunds.get(allocation.refund_id)
            if parent is None or parent.currency != allocation.currency:
                acc.reasons.add("refund_allocation_chain_incomplete")
                continue
            allocated[parent.pk] += allocation.amount
            add(
                parent.refunded_at,
                -allocation.amount,
                allocation.currency,
                effect_kind="refund_allocation",
            )
        for reversal in ledger.reversals:
            if reversal.target_kind == "application":
                add(
                    reversal.reversed_at,
                    -reversal.amount,
                    reversal.currency,
                    effect_kind="application_reversal",
                )
            elif reversal.target_kind == "refund":
                # Solo la porción que había reabierto saldo, nunca el refund bruto.
                add(
                    reversal.reversed_at,
                    allocated[reversal.target_id],
                    reversal.currency,
                    effect_kind="refund_reversal",
                )
    else:
        raise ValueError("métrica Receivables de hecho no soportada")
    return acc.result(
        provenance=_references(ledger),
        watermark=evidence_watermark(_references(ledger)),
        reason="legacy_evidence_requires_review" if ledger.legacy_missing else None,
    )


def _state(query: SourceMetricQuery, ledger: _Ledger) -> SourceMetricResult:
    assert query.as_of_at is not None
    as_of = query.as_of_at
    acc = MetricAccumulator(query, scale=2)
    reversed_ids: dict[str, set[UUID]] = defaultdict(set)
    for reversal in ledger.reversals:
        if reversal.reversed_at <= as_of:
            reversed_ids[reversal.target_kind].add(reversal.target_id)
    payments = {row.pk: row for row in ledger.payments if row.reported_at <= as_of}
    obligations = {row.pk: row for row in ledger.obligations if row.confirmed_at <= as_of}
    apps = {
        row.pk: row
        for row in ledger.applications
        if row.applied_at <= as_of
        and row.pk not in reversed_ids["application"]
        and row.payment_id not in reversed_ids["payment"]
        and row.payment_id in payments
        and row.obligation_id in obligations
    }
    refunds = {
        row.pk: row
        for row in ledger.refunds
        if row.refunded_at <= as_of
        and row.pk not in reversed_ids["refund"]
        and row.payment_id not in reversed_ids["payment"]
        and row.payment_id in payments
    }
    restored: dict[UUID, Decimal] = defaultdict(Decimal)
    for allocation in ledger.allocations:
        if allocation.refund_id in refunds and allocation.payment_application_id in apps:
            restored[allocation.payment_application_id] += allocation.amount
    adjusted = {row.pk: row.original_total for row in obligations.values()}
    for adjustment in ledger.adjustments:
        if (
            adjustment.occurred_at <= as_of
            and adjustment.pk not in reversed_ids["adjustment"]
            and adjustment.obligation_id in adjusted
        ):
            adjusted[adjustment.obligation_id] += (
                adjustment.amount if adjustment.direction == "increase" else -adjustment.amount
            )
    by_obligation: dict[UUID, list[PaymentApplication]] = defaultdict(list)
    applied: dict[UUID, Decimal] = defaultdict(Decimal)
    restored_obligations: dict[UUID, Decimal] = defaultdict(Decimal)
    applied_payments: dict[UUID, Decimal] = defaultdict(Decimal)
    restored_payments: dict[UUID, Decimal] = defaultdict(Decimal)
    refunded_payments: dict[UUID, Decimal] = defaultdict(Decimal)
    for application in apps.values():
        by_obligation[application.obligation_id].append(application)
        applied[application.obligation_id] += application.amount
        restored_obligations[application.obligation_id] += restored[application.pk]
        applied_payments[application.payment_id] += application.amount
        restored_payments[application.payment_id] += restored[application.pk]
    for refund in refunds.values():
        refunded_payments[refund.payment_id] += refund.amount
    metric = query.source_metric_id.removeprefix("receivables.")
    if metric == "payment_unapplied_amount":
        assert query.period_start is not None and query.period_end is not None
        for payment in payments.values():
            if not query.period_start <= payment.reported_at < query.period_end:
                continue
            value = (
                ZERO
                if payment.pk in reversed_ids["payment"]
                else (
                    payment.amount
                    - applied_payments[payment.pk]
                    - refunded_payments[payment.pk]
                    + restored_payments[payment.pk]
                )
            )
            acc.add(
                value,
                {
                    "currency": payment.currency,
                    "method": payment.method,
                    "provenance": payment.provenance,
                },
                at=payment.reported_at,
            )
    elif metric == "open_balance_amount":
        for obligation in obligations.values():
            acc.add(
                adjusted[obligation.pk]
                - applied[obligation.pk]
                + restored_obligations[obligation.pk],
                {"currency": obligation.currency},
            )
    else:
        return _scheduled(
            query,
            ledger,
            obligations,
            adjusted,
            applied,
            restored_obligations,
            by_obligation,
            restored,
            acc,
        )
    return acc.result(
        provenance=_references(ledger),
        watermark=evidence_watermark(_references(ledger)),
        reason="legacy_evidence_requires_review" if ledger.legacy_missing else None,
    )


def _scheduled(
    query: SourceMetricQuery,
    ledger: _Ledger,
    obligations: dict[UUID, ReceivableObligation],
    adjusted: dict[UUID, Decimal],
    applied: dict[UUID, Decimal],
    restored_obligations: dict[UUID, Decimal],
    by_obligation: dict[UUID, list[PaymentApplication]],
    restored: dict[UUID, Decimal],
    acc: MetricAccumulator,
) -> SourceMetricResult:
    assert query.as_of_at is not None
    revisions = {
        row.obligation_id: row for row in ledger.revisions if row.published_at <= query.as_of_at
    }
    dues: dict[UUID, list[CollectionScheduleDue]] = defaultdict(list)
    for due in ledger.dues:
        revision = revisions.get(due.obligation_id)
        if revision is not None and due.schedule_revision_id == revision.pk:
            dues[due.obligation_id].append(due)
    # Exactamente el asignador P10 con contexto histórico batch: cero queries por fila.
    context = _ObligationReadContext(
        adjusted,
        applied,
        restored_obligations,
        {key: tuple(dues[key]) for key in obligations},
        {key: tuple(by_obligation[key]) for key in obligations},
        restored,
        {},
    )
    zone = ZoneInfo(query.timezone_name)
    excluded = False
    metric = query.source_metric_id.removeprefix("receivables.")
    for obligation in obligations.values():
        for item in obligation_aging(
            obligation, query.as_of_at.astimezone(zone).date(), context=context
        ):
            if metric == "aging_open_balance_amount":
                acc.add(
                    cast(Decimal, item["open_amount"]),
                    {
                        "currency": obligation.currency,
                        "aging_bucket": item["bucket"],
                    },
                )
            elif metric == "expected_collection_amount":
                assert query.period_start is not None and query.period_end is not None
                due_on = cast(date | None, item["due_on"])
                if due_on is None:
                    excluded = True
                    continue
                due_at = datetime.combine(due_on, datetime.min.time(), zone)
                if query.period_start <= due_at < query.period_end:
                    acc.add(
                        cast(Decimal, item["open_amount"]),
                        {"currency": obligation.currency},
                        at=due_at,
                    )
            else:
                raise ValueError("métrica Receivables de estado no soportada")
    return acc.result(
        provenance=_references(ledger),
        watermark=evidence_watermark(_references(ledger)),
        reason="legacy_evidence_requires_review" if ledger.legacy_missing else None,
        exclusions=("unscheduled_obligations",) if excluded else (),
    )


def fetch_analytics_metrics(
    authorization: TenantAuthorization,
    queries: tuple[SourceMetricQuery, ...],
) -> tuple[SourceMetricResult, ...]:
    for item in queries:
        if item.source_metric_id not in INPUTS:
            raise ValueError("métrica fuente no soportada")
        INPUTS[item.source_metric_id].validate(item)
    authorization.require(Capability.RECEIVABLES_READ)
    ledgers: dict[datetime, _Ledger] = {}
    results = []
    for query in queries:
        if query.knowledge_cutoff_at not in ledgers:
            ledgers[query.knowledge_cutoff_at] = _load(authorization, query.knowledge_cutoff_at)
        ledger = ledgers[query.knowledge_cutoff_at]
        results.append(_facts(query, ledger) if query.as_of_at is None else _state(query, ledger))
    return tuple(results)
