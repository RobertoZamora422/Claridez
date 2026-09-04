"""Métricas financieras batch. Finance conserva fórmulas, clasificación y snapshots."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import claridez.commercial.public as commercial_port
import claridez.operations.public as operations_port
import claridez.receivables.public as receivables_port
import claridez.scheduling.public as scheduling_port
from claridez.organizations.capabilities import Capability
from claridez.organizations.public import (
    CohortMember,
    Coverage,
    DimensionValues,
    MetricAccumulator,
    MetricPoint,
    MetricValueStatus,
    SourceCollection,
    SourceMetricQuery,
    SourceMetricResult,
    TemporalMode,
    dimension_values,
    evidence_watermark,
    worst_coverage,
)
from claridez.organizations.tenant_scope import TenantAuthorization

from .metric_inputs import INPUTS
from .models import (
    ActualDirectCost,
    CashMovementCorrection,
    DirectCostCorrection,
    DirectCostPlanLine,
    DirectCostPlanRevision,
    ExpenseAllocation,
    ExpenseOccurrence,
    ExpenseOccurrenceCorrection,
    OperatingCashMovement,
    OperationalPeriod,
    PeriodCloseSnapshot,
    RecognitionAdjustment,
    RecognitionAdjustmentCorrection,
)
from .money import json_value
from .services import (
    _attribution_map,
    _metric_bucket,
    _metric_result,
    _p10_source_in_close,
    _signed,
)

ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class ConfirmedSale:
    root_reservation_id: UUID
    event_request_id: UUID
    total: Decimal
    currency: str
    venue_id: UUID
    confirmed_at: datetime


def _sales(authorization: TenantAuthorization, cutoff: datetime) -> SourceCollection[ConfirmedSale]:
    obligations = receivables_port.obligation_sales_for_analytics(
        authorization, knowledge_cutoff_at=cutoff
    )
    quotes = commercial_port.economic_sales_for_analytics(
        authorization,
        tuple(row.quotation_version_id for row in obligations.items),
        knowledge_cutoff_at=cutoff,
    )
    by_quote = {row.quotation_version_id: row for row in quotes.items}
    result: list[ConfirmedSale] = []
    mismatches = False
    for obligation in obligations.items:
        quote = by_quote.get(obligation.quotation_version_id)
        if (
            quote is None
            or quote.total != obligation.original_total
            or quote.currency != obligation.currency
            or quote.accepted_at > obligation.confirmed_at
        ):
            mismatches = True
            continue
        result.append(
            ConfirmedSale(
                obligation.root_reservation_id,
                obligation.event_request_id,
                quote.total,
                quote.currency,
                quote.venue_id,
                obligation.confirmed_at,
            )
        )
    reasons = tuple(
        reason
        for reason in (
            obligations.coverage_reason,
            quotes.coverage_reason,
            "economic_sale_source_mismatch" if mismatches else None,
        )
        if reason
    )
    coverage = worst_coverage(obligations.coverage, quotes.coverage)
    if mismatches:
        coverage = Coverage.PARTIAL if result else Coverage.UNAVAILABLE
    refs = obligations.provenance + quotes.provenance
    return SourceCollection(
        "finance.confirmed_sale_cohort",
        1,
        tuple(result),
        coverage,
        obligations.coverage_from,
        ";".join(reasons) or None,
        refs,
        evidence_watermark(refs),
    )


def confirmed_sale_cohort(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> SourceCollection[CohortMember]:
    authorization.require(Capability.FINANCE_READ)
    if (
        query.source_metric_id != "finance.confirmed_sale_cohort"
        or query.mode is not TemporalMode.COHORT
    ):
        raise ValueError("invalid_confirmed_sale_cohort_contract")
    assert query.as_of_at is not None
    source = _sales(authorization, query.knowledge_cutoff_at)
    # No se filtra la confirmación por la ventana de creación: la cohorte la gobierna Commercial.
    return SourceCollection(
        source.source_metric_id,
        1,
        tuple(
            CohortMember(row.event_request_id, row.root_reservation_id, row.confirmed_at, ())
            for row in source.items
            if row.confirmed_at <= query.as_of_at
        ),
        source.coverage,
        source.coverage_from,
        source.coverage_reason,
        source.provenance,
        source.watermark,
    )


@dataclass(frozen=True, slots=True)
class FinancialSlice:
    component: str
    amount: Decimal
    currency: str
    registration_period_id: UUID
    economic_date: date
    root_reservation_id: UUID | None
    venue_id: UUID | None
    category_id: UUID | None
    source_kind: str
    reference: str
    cash_direction: str = ""


@dataclass(frozen=True, slots=True)
class _PeriodBatch:
    periods: tuple[OperationalPeriod, ...]
    closes: tuple[PeriodCloseSnapshot, ...]
    slices: tuple[FinancialSlice, ...]
    reasons: tuple[str, ...]
    provenance: tuple[str, ...]


def _load_periods(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
    *,
    queried_period_ids: tuple[UUID, ...] = (),
) -> _PeriodBatch:
    assert query.as_of_at is not None
    oid, cutoff, asof = authorization.organization_id, query.knowledge_cutoff_at, query.as_of_at
    local_date = asof.astimezone(ZoneInfo(query.timezone_name)).date()
    periods = tuple(
        OperationalPeriod.objects.filter(organization_id=oid, created_at__lte=cutoff)
        .only("id", "starts_on", "ends_on", "currency", "created_at")
        .order_by("starts_on")
    )
    closes = tuple(
        PeriodCloseSnapshot.objects.filter(
            organization_id=oid, created_at__lte=cutoff, closed_at__lte=cutoff
        ).only("id", "period_id", "snapshot", "snapshot_sha256", "created_at", "closed_at")
    )
    # FP: el snapshot cerrado visible al límite de conocimiento siempre gobierna.
    if queried_period_ids and set(queried_period_ids) <= {row.period_id for row in closes}:
        return _PeriodBatch(periods, closes, (), (), ())
    sales = _sales(authorization, cutoff)
    sale_map = {row.root_reservation_id: row for row in sales.items}
    identities = scheduling_port.reservation_identities_for_analytics(
        authorization, knowledge_cutoff_at=cutoff
    )
    identity_map = {row.reservation_id: row for row in identities}
    executions = operations_port.execution_facts_for_analytics(
        authorization, as_of_at=asof, knowledge_cutoff_at=cutoff
    )
    reasons: set[str] = set()
    refs: set[str] = set()
    if executions.coverage_reason:
        reasons.add(executions.coverage_reason)
    slices: list[FinancialSlice] = []
    completed_roots: set[UUID] = set()
    root_venues = {
        row.root_reservation_id: row.venue_id
        for row in sorted(identities, key=lambda item: (item.recorded_at, str(item.reservation_id)))
        if row.recorded_at <= asof
    }
    for execution in executions.items:
        if execution.kind != "execution_completed":
            continue
        identity = identity_map.get(execution.reservation_id)
        if identity is None:
            reasons.add("execution_schedule_identity_missing")
            continue
        root_venues[identity.root_reservation_id] = identity.venue_id
        sale = sale_map.get(identity.root_reservation_id)
        if sale is None:
            reasons.add("execution_economic_sale_missing")
            continue
        economic_date = execution.occurred_at.astimezone(ZoneInfo(query.timezone_name)).date()
        period = next((p for p in periods if p.starts_on <= economic_date < p.ends_on), None)
        if period is None:
            continue
        if identity.root_reservation_id in completed_roots:
            reasons.add("duplicate_root_execution_evidence")
            continue
        completed_roots.add(identity.root_reservation_id)
        slices.append(
            FinancialSlice(
                "recognized_revenue",
                sale.total,
                sale.currency,
                period.pk,
                economic_date,
                identity.root_reservation_id,
                identity.venue_id,
                None,
                "execution_completed",
                f"execution:{execution.transition_id}:{execution.recorded_at.isoformat()}",
            )
        )

    # Consultas por tabla, nunca por fila. Los campos de texto libre no se materializan.
    costs = tuple(
        ActualDirectCost.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
            "id",
            "root_reservation_id",
            "venue_id",
            "category_id",
            "amount",
            "currency",
            "registration_period_id",
            "economic_date",
            "created_at",
        )
    )
    cost_map = {row.pk: row for row in costs}
    for cost in costs:
        slices.append(
            FinancialSlice(
                "direct_cost",
                cost.amount,
                cost.currency,
                cost.registration_period_id,
                cost.economic_date,
                cost.root_reservation_id,
                cost.venue_id,
                cost.category_id,
                "direct_cost",
                f"cost:{cost.pk}:{cost.created_at.isoformat()}",
            )
        )
    for correction in DirectCostCorrection.objects.filter(
        organization_id=oid, created_at__lte=cutoff
    ).only(
        "id",
        "direct_cost_id",
        "direction",
        "amount",
        "currency",
        "registration_period_id",
        "economic_date",
        "created_at",
    ):
        parent_cost = cost_map.get(correction.direct_cost_id)
        if parent_cost is None:
            reasons.add("cost_correction_parent_missing")
            continue
        slices.append(
            FinancialSlice(
                "direct_cost",
                _signed(correction.direction, correction.amount),
                correction.currency,
                correction.registration_period_id,
                correction.economic_date,
                parent_cost.root_reservation_id,
                parent_cost.venue_id,
                parent_cost.category_id,
                "direct_cost_correction",
                f"cost_correction:{correction.pk}:{correction.created_at.isoformat()}",
            )
        )

    expenses = tuple(
        ExpenseOccurrence.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
            "id",
            "expense_type",
            "category_id",
            "currency",
            "registration_period_id",
            "economic_date",
            "created_at",
        )
    )
    expense_map = {row.pk: row for row in expenses}
    for allocation in ExpenseAllocation.objects.filter(
        organization_id=oid, created_at__lte=cutoff
    ).only(
        "id",
        "expense_occurrence_id",
        "root_reservation_id",
        "venue_id",
        "amount",
        "currency",
        "created_at",
    ):
        expense = expense_map.get(allocation.expense_occurrence_id)
        if expense is None:
            reasons.add("expense_allocation_parent_missing")
            continue
        slices.append(
            FinancialSlice(
                f"{expense.expense_type}_expense",
                allocation.amount,
                allocation.currency,
                expense.registration_period_id,
                expense.economic_date,
                allocation.root_reservation_id,
                allocation.venue_id,
                expense.category_id,
                "expense_allocation",
                f"expense_allocation:{allocation.pk}:{allocation.created_at.isoformat()}",
            )
        )
    for exp_correction in ExpenseOccurrenceCorrection.objects.filter(
        organization_id=oid, created_at__lte=cutoff
    ).only(
        "id",
        "expense_occurrence_id",
        "root_reservation_id",
        "venue_id",
        "direction",
        "amount",
        "currency",
        "registration_period_id",
        "economic_date",
        "created_at",
    ):
        expense = expense_map.get(exp_correction.expense_occurrence_id)
        if expense is None:
            reasons.add("expense_correction_parent_missing")
            continue
        slices.append(
            FinancialSlice(
                f"{expense.expense_type}_expense",
                _signed(exp_correction.direction, exp_correction.amount),
                exp_correction.currency,
                exp_correction.registration_period_id,
                exp_correction.economic_date,
                exp_correction.root_reservation_id,
                exp_correction.venue_id,
                expense.category_id,
                "expense_correction",
                f"expense_correction:{exp_correction.pk}:{exp_correction.created_at.isoformat()}",
            )
        )

    adjustments = tuple(
        RecognitionAdjustment.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
            "id",
            "root_reservation_id",
            "venue_id",
            "amount",
            "direction",
            "currency",
            "registration_period_id",
            "economic_date",
            "created_at",
        )
    )
    adjustment_map = {row.pk: row for row in adjustments}
    for adjustment in adjustments:
        slices.append(
            FinancialSlice(
                "recognized_revenue",
                _signed(adjustment.direction, adjustment.amount),
                adjustment.currency,
                adjustment.registration_period_id,
                adjustment.economic_date,
                adjustment.root_reservation_id,
                adjustment.venue_id,
                None,
                "recognition_adjustment",
                f"recognition:{adjustment.pk}:{adjustment.created_at.isoformat()}",
            )
        )
    for rec_correction in RecognitionAdjustmentCorrection.objects.filter(
        organization_id=oid, created_at__lte=cutoff
    ).only(
        "id",
        "recognition_adjustment_id",
        "amount",
        "direction",
        "currency",
        "registration_period_id",
        "economic_date",
        "created_at",
    ):
        parent_adjustment = adjustment_map.get(rec_correction.recognition_adjustment_id)
        if parent_adjustment is None:
            reasons.add("recognition_correction_parent_missing")
            continue
        effect = _signed(
            parent_adjustment.direction, _signed(rec_correction.direction, rec_correction.amount)
        )
        slices.append(
            FinancialSlice(
                "recognized_revenue",
                effect,
                rec_correction.currency,
                rec_correction.registration_period_id,
                rec_correction.economic_date,
                parent_adjustment.root_reservation_id,
                parent_adjustment.venue_id,
                None,
                "recognition_correction",
                f"recognition_correction:{rec_correction.pk}:{rec_correction.created_at.isoformat()}",
            )
        )

    close_by_period = {row.period_id: row for row in closes}
    for source in receivables_port.cash_contributions_for_finance(
        authorization, knowledge_cutoff_at=cutoff
    ):
        if source.economic_at > asof:
            continue
        economic_date = source.economic_at.astimezone(ZoneInfo(query.timezone_name)).date()
        economic_period = next(
            (row for row in periods if row.starts_on <= economic_date < row.ends_on), None
        )
        if economic_period is None:
            continue
        registration = next(
            (
                row
                for row in periods
                if row.starts_on >= economic_period.starts_on
                and (
                    row.pk not in close_by_period
                    or _p10_source_in_close(source, close_by_period[row.pk])
                )
            ),
            None,
        )
        if registration is None:
            continue
        slices.append(
            FinancialSlice(
                "p10_cash",
                source.amount if source.direction == "inflow" else -source.amount,
                source.currency,
                registration.pk,
                economic_date,
                source.root_reservation_id,
                root_venues.get(source.root_reservation_id) if source.root_reservation_id else None,
                None,
                source.source_kind,
                f"{source.source_kind}:{source.source_id}:{source.registered_at.isoformat()}",
                source.direction,
            )
        )

    cash_rows = tuple(
        OperatingCashMovement.objects.filter(organization_id=oid, created_at__lte=cutoff).only(
            "id",
            "direction",
            "source_kind",
            "source_id",
            "amount",
            "expense_attributions",
            "currency",
            "registration_period_id",
            "economic_date",
            "created_at",
        )
    )
    cash_map = {row.pk: row for row in cash_rows}

    def cash_slices(
        cash: OperatingCashMovement,
        value: Decimal,
        attributions: object,
        registration_id: UUID,
        economic: date,
        reference: str,
    ) -> None:
        sign = Decimal(-1) if cash.direction == "outflow" else Decimal(1)
        direction = "outflow" if sign < 0 else "inflow"
        if cash.source_kind == "expense":
            for (_, root_id, venue_id), attributed in _attribution_map(attributions).items():
                slices.append(
                    FinancialSlice(
                        "p11_cash",
                        sign * value * attributed,
                        cash.currency,
                        registration_id,
                        economic,
                        root_id,
                        venue_id,
                        None,
                        "expense",
                        reference,
                        direction,
                    )
                )
        else:
            cost = cost_map.get(cash.source_id)
            if cost is None:
                reasons.add("cash_cost_parent_missing")
                return
            slices.append(
                FinancialSlice(
                    "p11_cash",
                    sign * value,
                    cash.currency,
                    registration_id,
                    economic,
                    cost.root_reservation_id,
                    cost.venue_id,
                    None,
                    "direct_cost",
                    reference,
                    direction,
                )
            )

    for cash in cash_rows:
        cash_slices(
            cash,
            Decimal(1) if cash.source_kind == "expense" else cash.amount,
            cash.expense_attributions,
            cash.registration_period_id,
            cash.economic_date,
            f"cash:{cash.pk}:{cash.created_at.isoformat()}",
        )
    for cash_correction in CashMovementCorrection.objects.filter(
        organization_id=oid, created_at__lte=cutoff
    ).only(
        "id",
        "cash_movement_id",
        "direction",
        "amount",
        "expense_attributions",
        "currency",
        "registration_period_id",
        "economic_date",
        "created_at",
    ):
        parent_cash = cash_map.get(cash_correction.cash_movement_id)
        if parent_cash is None:
            reasons.add("cash_correction_parent_missing")
            continue
        value = _signed(
            cash_correction.direction,
            Decimal(1) if parent_cash.source_kind == "expense" else cash_correction.amount,
        )
        cash_slices(
            parent_cash,
            value,
            cash_correction.expense_attributions,
            cash_correction.registration_period_id,
            cash_correction.economic_date,
            f"cash_correction:{cash_correction.pk}:{cash_correction.created_at.isoformat()}",
        )
    visible = tuple(row for row in slices if row.economic_date <= local_date)
    refs.update(row.reference for row in visible)
    refs.update(sales.provenance)
    refs.update(executions.provenance)
    refs.update(f"period:{row.pk}:{row.created_at.isoformat()}" for row in periods)
    refs.update(f"close:{row.pk}:{row.snapshot_sha256}" for row in closes)
    return _PeriodBatch(periods, closes, visible, tuple(sorted(reasons)), tuple(sorted(refs)))


_COMPONENTS = {
    "recognized_revenue_amount": "recognized_revenue",
    "actual_direct_cost_amount": "direct_cost",
    "variable_expense_amount": "variable_expense",
    "recurring_expense_amount": "recurring_expense",
    "gross_margin_amount": "gross_margin",
    "contribution_margin_amount": "contribution_margin",
    "operating_result_amount": "operating_result",
    "profitability_rate": "profitability_percentage",
    "net_cash_flow_amount": "net_cash_flow",
}


def _aggregate(
    query: SourceMetricQuery,
    slices: tuple[FinancialSlice, ...],
    *,
    currency: str,
    reasons: tuple[str, ...],
    refs: tuple[str, ...],
    provisional: bool,
) -> SourceMetricResult:
    metric = query.source_metric_id.removeprefix("finance.")
    acc = MetricAccumulator(query, scale=2)
    buckets: dict[DimensionValues, dict[str, Decimal]] = defaultdict(_metric_bucket)
    for row in slices:
        dimensions = {
            "currency": row.currency,
            "venue_id": row.venue_id,
            "root_reservation_id": row.root_reservation_id,
            "category_id": row.category_id,
            "source_kind": row.source_kind,
        }
        if metric in {"cash_inflow_amount", "cash_outflow_amount"}:
            if row.cash_direction == ("inflow" if metric == "cash_inflow_amount" else "outflow"):
                acc.add(row.amount if row.cash_direction == "inflow" else -row.amount, dimensions)
        elif metric in _COMPONENTS and _COMPONENTS[metric] in _metric_bucket():
            if row.component == _COMPONENTS[metric]:
                acc.add(row.amount, dimensions)
        else:
            key = acc.key(dimensions)
            if key is not None:
                buckets[key][row.component] += row.amount
    if not slices and set(query.dimensions) <= {"currency"}:
        if metric in {
            "profitability_rate",
            "gross_margin_amount",
            "contribution_margin_amount",
            "operating_result_amount",
            "net_cash_flow_amount",
        }:
            key = acc.key({"currency": currency})
            if key is not None:
                buckets[key] = _metric_bucket()
        else:
            acc.add(0, {"currency": currency})
    undefined: set[DimensionValues] = set()
    for key, bucket in buckets.items():
        value = cast(Decimal | None, _metric_result(bucket)[_COMPONENTS[metric]])
        if value is None:
            undefined.add(key)
        acc.add(value, dict(query.filters) | dict(key) | {"currency": currency})
    needed = {
        "recognized_revenue_amount": {"revenue"},
        "actual_direct_cost_amount": {"cost"},
        "variable_expense_amount": {"expense"},
        "recurring_expense_amount": {"expense"},
        "gross_margin_amount": {"revenue", "cost"},
        "contribution_margin_amount": {"revenue", "cost", "expense"},
        "operating_result_amount": {"revenue", "cost", "expense"},
        "profitability_rate": {"revenue", "cost", "expense"},
        "net_cash_flow_amount": {"cash"},
        "cash_inflow_amount": {"cash"},
        "cash_outflow_amount": {"cash"},
    }[metric]

    def affects(reason: str) -> bool:
        if reason.startswith(("execution_", "recognition_", "duplicate_root_")):
            return "revenue" in needed
        if reason.startswith("cost_"):
            return "cost" in needed
        if reason.startswith("expense_"):
            return "expense" in needed
        if reason.startswith("cash_"):
            return "cash" in needed
        return True

    active_reasons = tuple(reason for reason in reasons if affects(reason))
    missing_basis = False
    for reason in active_reasons:
        if reason.startswith(("execution_", "recognition_", "duplicate_root_")):
            components = {"recognized_revenue"}
        elif reason.startswith("cost_"):
            components = {"direct_cost"}
        elif reason.startswith("expense_"):
            components = {"variable_expense", "recurring_expense"}
        else:
            components = {"p10_cash", "p11_cash"}
        if not any(row.component in components for row in slices):
            missing_basis = True
    result = acc.result(
        provenance=refs,
        watermark=evidence_watermark(refs),
        coverage=Coverage.UNAVAILABLE if missing_basis else Coverage.COMPLETE,
        reason=";".join(active_reasons) or None,
        provisional=provisional,
    )
    if undefined:
        result = replace(
            result,
            points=tuple(
                replace(point, value=None, status=MetricValueStatus.NOT_CALCULABLE)
                if point.dimensions in undefined
                else point
                for point in result.points
            ),
        )
    return result


def _period_metric(query: SourceMetricQuery, batch: _PeriodBatch) -> SourceMetricResult:
    period = next((row for row in batch.periods if row.pk == query.operational_period_id), None)
    if period is None:
        raise ValueError("financial_period_not_available")
    selected_currency = query.filter_value("currency")
    if selected_currency is not None and selected_currency != period.currency:
        raise ValueError("financial_period_currency_mismatch")
    close = next((row for row in batch.closes if row.period_id == period.pk), None)
    if close is None:
        return _aggregate(
            query,
            tuple(row for row in batch.slices if row.registration_period_id == period.pk),
            currency=period.currency,
            reasons=batch.reasons,
            refs=batch.provenance,
            provisional=True,
        )
    return _closed_metric(query, period, close)


def _closed_metric(
    query: SourceMetricQuery, period: OperationalPeriod, close: PeriodCloseSnapshot
) -> SourceMetricResult:
    """Jamás consulta hechos posteriores para rellenar dimensiones ausentes de un cierre."""
    snapshot = cast(dict[str, object], close.snapshot)
    stored = snapshot.get("p15_metric_slices")
    refs = (f"finance_close:{close.pk}:{close.snapshot_sha256}",)
    if isinstance(stored, dict) and stored.get("version") == 1:
        rows: list[FinancialSlice] = []
        for raw in cast(list[dict[str, object]], stored["slices"]):
            rows.append(
                FinancialSlice(
                    str(raw["component"]),
                    Decimal(str(raw["amount"])),
                    str(raw["currency"]),
                    UUID(str(raw["registration_period_id"])),
                    date.fromisoformat(str(raw["economic_date"])),
                    UUID(str(raw["root_reservation_id"])) if raw["root_reservation_id"] else None,
                    UUID(str(raw["venue_id"])) if raw["venue_id"] else None,
                    UUID(str(raw["category_id"])) if raw["category_id"] else None,
                    str(raw["source_kind"]),
                    str(raw["reference"]),
                    str(raw["cash_direction"]),
                )
            )
        return _aggregate(
            query,
            tuple(rows),
            currency=period.currency,
            reasons=tuple(cast(list[str], stored.get("reasons", []))),
            refs=refs,
            provisional=False,
        )
    # Snapshots P11 previos: su total presentado es autoritativo; no inventar sus desgloses.
    metric = query.source_metric_id.removeprefix("finance.")
    scope = set(query.dimensions) | set(dict(query.filters))
    if scope <= {"currency"} and metric in _COMPONENTS:
        presented = cast(dict[str, object], snapshot["presented"])
        raw_value = presented.get(_COMPONENTS[metric])
        point = MetricPoint(
            dimension_values(currency=period.currency) if "currency" in query.dimensions else (),
            Decimal(str(raw_value)) if raw_value is not None else None,
            MetricValueStatus.VALUE if raw_value is not None else MetricValueStatus.NOT_CALCULABLE,
        )
        return SourceMetricResult(
            query.source_metric_id,
            1,
            (point,),
            Coverage.COMPLETE,
            None,
            None,
            refs,
            evidence_watermark(refs),
        )
    return MetricAccumulator(query, scale=2).result(
        provenance=refs,
        watermark=evidence_watermark(refs),
        coverage=Coverage.UNAVAILABLE,
        reason="closed_snapshot_dimension_not_materialized",
    )


def _baseline(authorization: TenantAuthorization, query: SourceMetricQuery) -> SourceMetricResult:
    assert query.as_of_at is not None
    identities = scheduling_port.reservation_identities_for_analytics(
        authorization, knowledge_cutoff_at=query.knowledge_cutoff_at
    )
    roots = {row.reservation_id: row.root_reservation_id for row in identities}
    facts = operations_port.execution_facts_for_analytics(
        authorization, as_of_at=query.as_of_at, knowledge_cutoff_at=query.knowledge_cutoff_at
    )
    started = {
        roots[row.reservation_id]: row.occurred_at
        for row in facts.items
        if row.kind == "execution_started" and row.reservation_id in roots
    }
    plans = tuple(
        DirectCostPlanRevision.objects.filter(
            organization_id=authorization.organization_id,
            created_at__lte=query.knowledge_cutoff_at,
            published_at__lte=query.as_of_at,
        )
        .only("id", "root_reservation_id", "revision", "currency", "published_at")
        .order_by("revision")
    )
    baseline = {
        row.root_reservation_id: row
        for row in plans
        if row.root_reservation_id in started
        and row.published_at <= started[row.root_reservation_id]
    }
    acc = MetricAccumulator(query, scale=2)
    refs = list(facts.provenance)
    for line in (
        DirectCostPlanLine.objects.filter(
            organization_id=authorization.organization_id,
            plan_revision_id__in=[p.pk for p in baseline.values()],
            created_at__lte=query.knowledge_cutoff_at,
        )
        .select_related("plan_revision")
        .only(
            "id",
            "plan_revision_id",
            "plan_revision__root_reservation_id",
            "currency",
            "category_id",
            "amount",
            "created_at",
        )
    ):
        acc.add(
            line.amount,
            {
                "currency": line.currency,
                "root_reservation_id": line.plan_revision.root_reservation_id,
                "category_id": line.category_id,
            },
        )
        refs.append(f"baseline_line:{line.pk}:{line.created_at.isoformat()}")
    result = acc.result(
        provenance=tuple(refs),
        watermark=evidence_watermark(tuple(refs)),
        reason=facts.coverage_reason,
    )
    root_filter = query.filter_value("root_reservation_id")
    if root_filter and UUID(root_filter) not in baseline and facts.coverage is Coverage.COMPLETE:
        dims = tuple((name, str(dict(query.filters).get(name, ""))) for name in query.dimensions)
        return replace(result, points=(MetricPoint(dims, None, MetricValueStatus.NOT_APPLICABLE),))
    return result


def fetch_analytics_metrics(
    authorization: TenantAuthorization, queries: tuple[SourceMetricQuery, ...]
) -> tuple[SourceMetricResult, ...]:
    authorization.require(Capability.FINANCE_READ)
    for query in queries:
        if query.source_metric_id not in INPUTS:
            raise ValueError("unknown_finance_source_metric")
        INPUTS[query.source_metric_id].validate(query)
    periods: dict[tuple[datetime, datetime | None, str], _PeriodBatch] = {}
    sales: dict[datetime, SourceCollection[ConfirmedSale]] = {}
    results = []
    for query in queries:
        if query.mode is TemporalMode.FACT:
            if query.knowledge_cutoff_at not in sales:
                sales[query.knowledge_cutoff_at] = _sales(authorization, query.knowledge_cutoff_at)
            source = sales[query.knowledge_cutoff_at]
            acc = MetricAccumulator(
                query, scale=2 if query.source_metric_id.endswith("_amount") else 0
            )
            assert query.period_start is not None and query.period_end is not None
            for sale in source.items:
                if query.period_start <= sale.confirmed_at < query.period_end:
                    acc.add(
                        sale.total if query.source_metric_id.endswith("_amount") else 1,
                        {"currency": sale.currency, "venue_id": sale.venue_id},
                        at=sale.confirmed_at,
                    )
            results.append(
                acc.result(
                    provenance=source.provenance,
                    watermark=source.watermark,
                    coverage=source.coverage,
                    reason=source.coverage_reason,
                    coverage_from=source.coverage_from,
                )
            )
        elif query.mode is TemporalMode.STATE:
            results.append(_baseline(authorization, query))
        else:
            key = (query.knowledge_cutoff_at, query.as_of_at, query.timezone_name)
            if key not in periods:
                requested = tuple(
                    item.operational_period_id
                    for item in queries
                    if item.mode is TemporalMode.FINANCIAL_PERIOD
                    and (item.knowledge_cutoff_at, item.as_of_at, item.timezone_name) == key
                    and item.operational_period_id is not None
                )
                periods[key] = _load_periods(authorization, query, queried_period_ids=requested)
            results.append(_period_metric(query, periods[key]))
    return tuple(results)


def snapshot_metric_slices(
    authorization: TenantAuthorization,
    *,
    period_id: UUID,
    currency: str,
    timezone_name: str,
    cutoff: datetime,
    presented: dict[str, object],
) -> dict[str, object]:
    """Enriquece solo futuros cierres Finance; no reconstruye ni altera cierres existentes."""
    authorization.require(Capability.FINANCE_READ)
    query = SourceMetricQuery(
        "finance.operating_result_amount",
        1,
        TemporalMode.FINANCIAL_PERIOD,
        None,
        None,
        cutoff,
        cutoff,
        cutoff,
        timezone_name,
        filters=(("currency", currency),),
        operational_period_id=period_id,
    )
    batch = _load_periods(authorization, query)
    rows = tuple(row for row in batch.slices if row.registration_period_id == period_id)
    buckets = _metric_bucket()
    for row in rows:
        buckets[row.component] += row.amount
    result = _metric_result(buckets)
    if batch.reasons or any(str(result[key]) != str(presented[key]) for key in buckets):
        # El cierre existente sigue mandando. Una cobertura incompleta no autoriza fabricar slices.
        return {"version": 0, "reason": "source_slices_do_not_reconcile_with_authoritative_close"}
    return {
        "version": 1,
        "slices": cast(list[object], json_value([asdict(row) for row in rows])),
        "reasons": [],
        "provenance": list(batch.provenance),
    }
