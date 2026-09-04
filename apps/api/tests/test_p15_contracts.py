from __future__ import annotations

import re
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from claridez.analytics.registry import CATALOG_HASH, METRICS, contract
from claridez.organizations.analytics_contracts import (
    Coverage,
    MetricValueStatus,
    SourceMetricQuery,
    SourceMetricResult,
    TemporalMode,
)
from claridez.organizations.analytics_values import MetricAccumulator, interval_slices
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.models import Membership

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


@pytest.mark.parametrize("metric", METRICS, ids=lambda row: row.versioned_id)
def test_source_dto_preserves_public_metric_identity_and_unit(metric: object) -> None:
    from claridez.analytics.registry import MetricContract

    assert isinstance(metric, MetricContract)
    source_id = (
        metric.metric_id if metric.owner == "analytics" else metric.sources[0].source_metric_id
    )
    result = SourceMetricResult(source_id, 1, (), Coverage.COMPLETE, None, None, (), "watermark")
    assert result.metric_id == metric.metric_id
    assert result.unit == metric.unit


def query(mode: TemporalMode = TemporalMode.FACT) -> SourceMetricQuery:
    return SourceMetricQuery(
        "commercial.request_created_count",
        1,
        mode,
        NOW - timedelta(days=3)
        if mode in {TemporalMode.FACT, TemporalMode.COHORT, TemporalMode.STATE_IN_PERIOD}
        else None,
        NOW - timedelta(days=1)
        if mode in {TemporalMode.FACT, TemporalMode.COHORT, TemporalMode.STATE_IN_PERIOD}
        else None,
        None if mode is TemporalMode.FACT else NOW,
        NOW,
        NOW,
        "America/Guayaquil",
        operational_period_id=uuid4() if mode is TemporalMode.FINANCIAL_PERIOD else None,
    )


def test_normative_catalog_exact_ids_and_frozen_content() -> None:
    root = Path(__file__).resolve().parents[3]
    adr = (root / "docs/adr/0024-analytics-reporting-and-exports.md").read_text(encoding="utf-8")
    expected = [
        item
        for item in re.findall(r"^\| `([a-z_]+)@1`", adr, flags=re.MULTILINE)
        if item != "metric_id"
    ]
    assert len(expected) == 53
    assert {m.metric_id for m in METRICS} == set(expected)
    assert CATALOG_HASH == "c1c79d37cb9bd397c5012d27f048fd39debc5cd2ef1a196e2b9f7262d18d8c23"


@pytest.mark.parametrize("metric", METRICS, ids=lambda m: m.versioned_id)
def test_every_metric_has_versioned_owner_capabilities_dimensions_and_formula(
    metric: object,
) -> None:
    from claridez.analytics.registry import MetricContract

    assert isinstance(metric, MetricContract)
    assert metric.metric_version == 1
    assert metric.formula and metric.grain and metric.coverage_rule
    assert len(set(metric.dimensions)) == len(metric.dimensions)
    assert set(metric.required_dimensions) <= set(metric.dimensions)
    assert metric.sources and all(s.source_metric_version == 1 for s in metric.sources)
    assert metric.required_capabilities
    assert all(Capability(cap) for cap in metric.required_capabilities)
    if metric.owner != "analytics":
        assert metric.sources[0].source_metric_id.startswith(metric.owner + ".")
    assert "occupancy_pct" not in metric.metric_id


def test_exactly_two_analytics_owned_compositions() -> None:
    assert {m.metric_id for m in METRICS if m.owner == "analytics"} == {
        "request_to_confirmed_sale_conversion_rate",
        "distinct_canonical_request_person_count",
    }
    with pytest.raises(KeyError):
        contract("request_created_count", 2)
    with pytest.raises(FrozenInstanceError):
        attribute = "metric_version"
        setattr(METRICS[0], attribute, 2)


@pytest.mark.parametrize(
    "owner",
    ["commercial", "crm", "scheduling", "operations", "receivables", "finance", "resources"],
)
def test_source_owned_input_specs_reconcile_with_catalog(owner: str) -> None:
    inputs = import_module(f"claridez.{owner}.metric_inputs").INPUTS
    for metric in METRICS:
        if metric.owner != owner:
            continue
        spec = inputs[metric.sources[0].source_metric_id]
        assert spec.mode == metric.temporal_mode.value
        assert set(spec.dimensions.split()) == set(metric.dimensions)
        assert set(spec.partitions.split()) == set(metric.required_dimensions)


@pytest.mark.parametrize("mode", list(TemporalMode))
def test_all_temporal_modes_validate_valid_contract(mode: TemporalMode) -> None:
    assert query(mode).mode is mode


@pytest.mark.parametrize("mode", list(TemporalMode))
def test_future_knowledge_is_rejected(mode: TemporalMode) -> None:
    with pytest.raises(ValueError, match="knowledge_cutoff_at"):
        replace(query(mode), knowledge_cutoff_at=NOW + timedelta(seconds=1))


@pytest.mark.parametrize(
    "mode",
    [
        TemporalMode.STATE,
        TemporalMode.STATE_IN_PERIOD,
        TemporalMode.COHORT,
        TemporalMode.FINANCIAL_PERIOD,
    ],
)
def test_asof_cannot_exceed_knowledge(mode: TemporalMode) -> None:
    with pytest.raises(ValueError, match="as_of_at"):
        replace(query(mode), as_of_at=NOW + timedelta(seconds=1))


def test_invalid_mode_parameters_and_naive_time_are_rejected() -> None:
    with pytest.raises(ValueError, match="F exige"):
        replace(query(), as_of_at=NOW)
    with pytest.raises(ValueError, match="period_end"):
        replace(query(TemporalMode.COHORT), as_of_at=NOW - timedelta(days=2))
    with pytest.raises(ValueError, match="FP exige"):
        replace(query(TemporalMode.FINANCIAL_PERIOD), period_start=NOW)
    with pytest.raises(ValueError, match="zona horaria"):
        replace(query(), executed_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="semiabierto"):
        replace(query(), period_start=query().period_end)


@pytest.mark.parametrize("day,hours", [(datetime(2026, 3, 8), 23), (datetime(2026, 11, 1), 25)])
def test_dst_civil_days_use_exact_utc_duration(day: datetime, hours: int) -> None:
    zone = ZoneInfo("America/New_York")
    start = day.replace(tzinfo=zone)
    end = start + timedelta(days=1)
    q = replace(
        query(),
        period_start=start,
        period_end=end,
        timezone_name=zone.key,
        dimensions=("time_bucket",),
        filters=(("time_bucket", "day"),),
    )
    pieces = interval_slices(start, end, q)
    assert len(pieces) == 1
    assert pieces[0][1] == Decimal(hours * 3600)
    assert interval_slices(end, end + timedelta(hours=1), q) == ()


def test_duration_rounds_after_aggregation_and_splits_buckets() -> None:
    q = replace(
        query(),
        period_start=NOW.replace(hour=0) - timedelta(days=2),
        period_end=NOW.replace(hour=0),
        timezone_name="UTC",
        dimensions=("time_bucket",),
        filters=(("time_bucket", "day"),),
    )
    assert q.period_start is not None and q.period_end is not None
    parts = interval_slices(q.period_start, q.period_end, q)
    assert len(parts) == 2
    assert sum((value for _, value in parts), Decimal(0)) == 172800
    acc = MetricAccumulator(query(), scale=3)
    acc.add(Decimal("0.0004"), {})
    acc.add(Decimal("0.0004"), {})
    assert acc.result(provenance=("test",), watermark="test").points[0].value == Decimal("0.001")


def test_empty_average_never_invents_zero_and_unavailable_has_no_value() -> None:
    acc = MetricAccumulator(query(), scale=3, average=True)
    result = acc.result(provenance=("test",), watermark="test")
    assert result.points[0].value is None
    assert result.points[0].status is MetricValueStatus.NOT_CALCULABLE
    acc.reasons.add("history_missing")
    result = acc.result(provenance=("test",), watermark="test")
    assert result.coverage is Coverage.UNAVAILABLE
    assert result.points[0].value is None


def test_missing_filter_dimension_does_not_match_and_partial_does_not_estimate() -> None:
    q = replace(query(), filters=(("origin", "phone"),))
    acc = MetricAccumulator(q)
    acc.add(500, {})
    acc.add(2, {"origin": "phone"})
    result = acc.result(provenance=("test",), watermark="test")
    assert result.coverage is Coverage.PARTIAL
    assert result.points[0].value == 2


@pytest.mark.parametrize("role", list(Membership.Role))
def test_p15_capabilities_do_not_grant_unrelated_source_authority(role: Membership.Role) -> None:
    capabilities = capabilities_for_role(role)
    p15 = {c for c in Capability if c.value.startswith("analytics:")}
    assert len(p15) == 6
    expected = (
        p15
        if role in {Membership.Role.OWNER, Membership.Role.ADMINISTRATOR}
        else (p15 - {Capability.ANALYTICS_MANAGE_SHARED_REPORT})
    )
    assert capabilities & p15 == expected
    crm_read = {
        Capability.INTERACTION_READ_ANALYTICS,
        Capability.TASK_READ_ANALYTICS,
        Capability.PERSON_RESOLVE_ANALYTICS,
    }
    assert capabilities & crm_read == (
        crm_read
        if role
        in {
            Membership.Role.OWNER,
            Membership.Role.ADMINISTRATOR,
            Membership.Role.COMMERCIAL,
        }
        else set()
    )
    assert (Capability.SCHEDULE_READ_ANALYTICS in capabilities) == (
        role is not Membership.Role.FINANCE
    )
    if role in {Membership.Role.OPERATIONS, Membership.Role.COMMERCIAL}:
        assert Capability.FINANCE_READ not in capabilities
        assert Capability.RECEIVABLES_READ not in capabilities
