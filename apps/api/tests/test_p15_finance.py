from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from claridez.finance.analytics import (
    FinancialSlice,
    _aggregate,
    _closed_metric,
    _period_metric,
    _PeriodBatch,
)
from claridez.finance.models import OperationalPeriod, PeriodCloseSnapshot
from claridez.finance.money import json_value
from claridez.organizations.analytics_contracts import (
    Coverage,
    MetricValueStatus,
    SourceMetricQuery,
    TemporalMode,
)

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)
PERIOD = UUID(int=1)
ROOT = UUID(int=2)
VENUE = UUID(int=3)


def query(metric: str) -> SourceMetricQuery:
    return SourceMetricQuery(
        "finance." + metric,
        1,
        TemporalMode.FINANCIAL_PERIOD,
        None,
        None,
        NOW,
        NOW,
        NOW,
        "America/Guayaquil",
        dimensions=("currency",),
        operational_period_id=PERIOD,
    )


def slices() -> tuple[FinancialSlice, ...]:
    return tuple(
        FinancialSlice(
            component,
            Decimal(amount),
            "USD",
            PERIOD,
            date(2026, 8, 3),
            ROOT,
            VENUE,
            None,
            kind,
            "test:" + str(index),
            direction,
        )
        for index, (component, amount, kind, direction) in enumerate(
            (
                ("recognized_revenue", "100.00", "execution_completed", ""),
                ("recognized_revenue", "-5.00", "recognition_adjustment", ""),
                ("direct_cost", "30.00", "direct_cost", ""),
                ("direct_cost", "-2.00", "direct_cost_correction", ""),
                ("variable_expense", "10.00", "expense", ""),
                ("recurring_expense", "5.00", "expense", ""),
                ("p10_cash", "120.00", "payment", "inflow"),
                ("p10_cash", "-20.00", "refund", "outflow"),
                ("p10_cash", "5.00", "refund_reversal", "inflow"),
                ("p11_cash", "-30.00", "direct_cost", "outflow"),
                ("p11_cash", "2.00", "direct_cost", "outflow"),
            )
        )
    )


@pytest.mark.parametrize(
    ("metric", "expected"),
    (
        ("recognized_revenue_amount", "95.00"),
        ("actual_direct_cost_amount", "28.00"),
        ("variable_expense_amount", "10.00"),
        ("recurring_expense_amount", "5.00"),
        ("gross_margin_amount", "67.00"),
        ("contribution_margin_amount", "57.00"),
        ("operating_result_amount", "52.00"),
        ("profitability_rate", "54.74"),
        ("cash_inflow_amount", "125.00"),
        ("cash_outflow_amount", "48.00"),
        ("net_cash_flow_amount", "77.00"),
    ),
)
def test_source_owned_finance_formulas(metric: str, expected: str) -> None:
    result = _aggregate(
        query(metric), slices(), currency="USD", reasons=(), refs=("test",), provisional=True
    )
    assert result.coverage is Coverage.COMPLETE
    assert result.provisional
    assert result.points[0].value == Decimal(expected)


def test_filtered_derived_metric_does_not_lose_already_authorized_scope() -> None:
    selected = replace(
        query("operating_result_amount"), filters=(("root_reservation_id", str(ROOT)),)
    )
    result = _aggregate(selected, slices(), currency="USD", reasons=(), refs=(), provisional=True)
    assert result.coverage is Coverage.COMPLETE
    assert result.points[0].value == Decimal("52.00")


def test_zero_revenue_is_not_calculable_and_no_denominator_is_invented() -> None:
    result = _aggregate(
        query("profitability_rate"), (), currency="USD", reasons=(), refs=(), provisional=True
    )
    assert result.points[0].value is None
    assert result.points[0].status is MetricValueStatus.NOT_CALCULABLE


def test_coverage_defect_in_execution_does_not_contaminate_unrelated_cash() -> None:
    reasons = ("execution_registration_history_unavailable",)
    cash = _aggregate(
        query("net_cash_flow_amount"),
        slices(),
        currency="USD",
        reasons=reasons,
        refs=(),
        provisional=True,
    )
    revenue = _aggregate(
        query("recognized_revenue_amount"),
        slices(),
        currency="USD",
        reasons=reasons,
        refs=(),
        provisional=True,
    )
    assert cash.coverage is Coverage.COMPLETE
    assert revenue.coverage is Coverage.PARTIAL


def test_unknown_revenue_is_unavailable_not_zero() -> None:
    result = _aggregate(
        query("recognized_revenue_amount"),
        (),
        currency="USD",
        reasons=("execution_registration_history_unavailable",),
        refs=(),
        provisional=True,
    )
    assert result.coverage is Coverage.UNAVAILABLE
    assert all(point.value is None for point in result.points)


def test_closed_legacy_snapshot_wins_even_with_newer_different_slices() -> None:
    period = OperationalPeriod(id=PERIOD, currency="USD")
    close = PeriodCloseSnapshot(
        id=UUID(int=10),
        period_id=PERIOD,
        snapshot={"presented": {"operating_result": "999.00"}},
        snapshot_sha256="a" * 64,
    )
    batch = _PeriodBatch((period,), (close,), slices(), (), ())
    result = _period_metric(query("operating_result_amount"), batch)
    assert result.points[0].value == Decimal("999.00")
    assert not result.provisional
    assert result.provenance == (f"finance_close:{close.pk}:{'a' * 64}",)
    grouped = replace(query("operating_result_amount"), dimensions=("currency", "venue_id"))
    result = _period_metric(grouped, batch)
    assert result.coverage is Coverage.UNAVAILABLE
    assert result.coverage_reason == "closed_snapshot_dimension_not_materialized"


def test_closed_versioned_slices_preserve_dimensions_and_prior_period_effects() -> None:
    period = OperationalPeriod(
        id=PERIOD, currency="USD", starts_on=date(2026, 8, 1), ends_on=date(2026, 9, 1)
    )
    rows = slices() + (
        FinancialSlice(
            "direct_cost",
            Decimal("5.00"),
            "USD",
            PERIOD,
            date(2026, 7, 1),
            ROOT,
            VENUE,
            None,
            "direct_cost_correction",
            "prior",
            "",
        ),
    )
    close = PeriodCloseSnapshot(
        id=UUID(int=10),
        period_id=PERIOD,
        snapshot={
            "p15_metric_slices": {
                "version": 1,
                "slices": json_value([asdict(row) for row in rows]),
                "reasons": [],
            }
        },
        snapshot_sha256="b" * 64,
    )
    selected = replace(query("operating_result_amount"), dimensions=("currency", "venue_id"))
    result = _closed_metric(selected, period, close)
    assert result.coverage is Coverage.COMPLETE
    assert result.points[0].value == Decimal("47.00")
    assert dict(result.points[0].dimensions) == {"currency": "USD", "venue_id": str(VENUE)}


def test_financial_period_does_not_allow_fx() -> None:
    period = OperationalPeriod(id=PERIOD, currency="USD")
    selected = replace(query("recognized_revenue_amount"), filters=(("currency", "EUR"),))
    with pytest.raises(ValueError, match="currency_mismatch"):
        _period_metric(selected, _PeriodBatch((period,), (), (), (), ()))
