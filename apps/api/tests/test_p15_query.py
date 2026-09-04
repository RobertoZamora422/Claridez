from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from django.utils import timezone

import claridez.commercial.public as commercial_port
import claridez.finance.public as finance_port
import claridez.people.public as people_port
from claridez.analytics import query as engine
from claridez.analytics.query import MetricSelection, _execute_frozen, selection_from_payload
from claridez.organizations.analytics_contracts import (
    CanonicalCluster,
    CohortMember,
    Coverage,
    MetricPoint,
    MetricValueStatus,
    SourceCollection,
    SourceMetricQuery,
    SourceMetricResult,
)
from claridez.organizations.capabilities import Capability
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.models import Membership
from claridez.organizations.tenant_scope import TenantAuthorization

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def authorization(role: Membership.Role = Membership.Role.OWNER) -> TenantAuthorization:
    return TenantAuthorization(uuid4(), uuid4(), uuid4(), role, Capability.ANALYTICS_READ_DASHBOARD)


def collection[T](
    name: str, items: tuple[T, ...], coverage: Coverage = Coverage.COMPLETE
) -> SourceCollection[T]:
    return SourceCollection(
        name,
        1,
        items,
        coverage,
        None,
        "source_history_missing" if coverage != Coverage.COMPLETE else None,
        (name,),
        name,
    )


def selection(metric_id: str) -> MetricSelection:
    return MetricSelection(
        metric_id,
        period_start=NOW - timedelta(days=3),
        period_end=NOW - timedelta(days=1),
        as_of_at=NOW,
    )


def test_conversion_counts_requests_once_not_confirmations_and_preserves_both_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_a, request_b, request_outside = UUID(int=1), UUID(int=2), UUID(int=3)
    members = tuple(
        CohortMember(key, None, NOW - timedelta(days=2), ()) for key in (request_a, request_b)
    )
    confirmations = tuple(
        CohortMember(key, uuid4(), NOW, ()) for key in (request_a, request_a, request_outside)
    )
    monkeypatch.setattr(
        commercial_port,
        "request_cohort",
        lambda *args: collection("commercial.request_created_cohort", members),
    )
    monkeypatch.setattr(
        finance_port,
        "confirmed_sale_cohort",
        lambda *args: collection("finance.confirmed_sale_cohort", confirmations),
    )
    output = _execute_frozen(
        authorization(),
        (selection("request_to_confirmed_sale_conversion_rate"),),
        timezone_name="America/Guayaquil",
        knowledge_cutoff_at=NOW,
        executed_at=NOW,
        capability=Capability.ANALYTICS_READ_DASHBOARD,
    )
    result = output.metrics[0].result
    assert result.points[0].value == Decimal("50.00")
    assert result.points[0].eligible_count == 2
    assert result.points[0].sample_size == 1
    assert result.provenance == (
        "commercial.request_created_cohort@1",
        "finance.confirmed_sale_cohort@1",
    )


@pytest.mark.parametrize("coverage", (Coverage.COMPLETE, Coverage.PARTIAL, Coverage.UNAVAILABLE))
def test_conversion_never_invents_denominator_or_ratio(
    monkeypatch: pytest.MonkeyPatch, coverage: Coverage
) -> None:
    monkeypatch.setattr(
        commercial_port,
        "request_cohort",
        lambda *args: collection("commercial.request_created_cohort", (), coverage),
    )
    monkeypatch.setattr(
        finance_port,
        "confirmed_sale_cohort",
        lambda *args: collection("finance.confirmed_sale_cohort", ()),
    )
    output = _execute_frozen(
        authorization(),
        (selection("request_to_confirmed_sale_conversion_rate"),),
        timezone_name="America/Guayaquil",
        knowledge_cutoff_at=NOW,
        executed_at=NOW,
        capability=Capability.ANALYTICS_READ_DASHBOARD,
    )
    assert output.metrics[0].result.coverage == coverage
    assert output.metrics[0].result.points[0].value is None
    assert output.metrics[0].result.points[0].status is MetricValueStatus.NOT_CALCULABLE


def test_canonical_people_composition_deduplicates_cluster_without_returning_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persons = (UUID(int=4), UUID(int=5))
    members = tuple(
        CohortMember(uuid4(), person, NOW - timedelta(days=2), ())
        for person in (*persons, persons[0])
    )
    monkeypatch.setattr(
        commercial_port,
        "request_cohort",
        lambda *args: collection("commercial.request_person_cohort", members),
    )
    monkeypatch.setattr(
        people_port,
        "canonical_clusters_as_of",
        lambda *args: collection(
            "people.canonical_cluster_as_of",
            tuple(CanonicalCluster(person, persons[1], 1, NOW) for person in persons),
        ),
    )
    output = _execute_frozen(
        authorization(),
        (selection("distinct_canonical_request_person_count"),),
        timezone_name="America/Guayaquil",
        knowledge_cutoff_at=NOW,
        executed_at=NOW,
        capability=Capability.ANALYTICS_READ_DASHBOARD,
    )
    assert output.metrics[0].result.points[0].value == 1
    assert all(str(person) not in str(engine.output_payload(output)) for person in persons)


def test_fan_in_is_one_batch_call_per_owner_and_never_queries_row_by_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[SourceMetricQuery, ...]] = []

    def source(
        auth: TenantAuthorization, queries: tuple[SourceMetricQuery, ...]
    ) -> tuple[SourceMetricResult, ...]:
        calls.append(queries)
        return tuple(
            SourceMetricResult(
                row.source_metric_id,
                1,
                (MetricPoint((), 1),),
                Coverage.COMPLETE,
                None,
                None,
                ("source@1",),
                "revision",
            )
            for row in queries
        )

    monkeypatch.setitem(engine._PORTS, "commercial", source)
    chosen = tuple(
        replace(selection(name), as_of_at=None)
        for name in ("request_created_count", "quote_issued_count")
    )
    result = _execute_frozen(
        authorization(),
        chosen,
        timezone_name="America/Guayaquil",
        knowledge_cutoff_at=NOW,
        executed_at=NOW,
        capability=Capability.ANALYTICS_READ_DASHBOARD,
    )
    assert len(calls) == 1
    assert len(calls[0]) == len(result.metrics) == 2


def test_new_query_freezes_server_time_and_rejects_client_knowledge_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(timezone, "now", lambda: NOW)
    monkeypatch.setattr(
        commercial_port,
        "request_cohort",
        lambda *args: collection("commercial.request_person_cohort", ()),
    )
    monkeypatch.setattr(
        people_port,
        "canonical_clusters_as_of",
        lambda *args: collection("people.canonical_cluster_as_of", ()),
    )
    result = engine.execute_query(
        authorization(),
        (selection("distinct_canonical_request_person_count"),),
        timezone_name="America/Guayaquil",
        capability=Capability.ANALYTICS_READ_DASHBOARD,
    )
    assert result.executed_at == result.knowledge_cutoff_at == NOW
    with pytest.raises(ValueError, match="unknown_metric_selection_field"):
        selection_from_payload(
            {
                "metric_id": "request_created_count",
                "knowledge_cutoff_at": (NOW + timedelta(days=1)).isoformat(),
            }
        )
    with pytest.raises(ValueError, match="as_of_at"):
        engine.execute_query(
            authorization(),
            (
                replace(
                    selection("distinct_canonical_request_person_count"),
                    as_of_at=NOW + timedelta(seconds=1),
                ),
            ),
            timezone_name="America/Guayaquil",
            capability=Capability.ANALYTICS_READ_DASHBOARD,
        )


@pytest.mark.parametrize("role", (Membership.Role.COMMERCIAL, Membership.Role.OPERATIONS))
def test_analytics_capability_never_grants_finance(role: Membership.Role) -> None:
    with pytest.raises(AuthorizationDenied):
        engine.authorize_selections(
            authorization(role),
            (MetricSelection("recognized_revenue_amount"),),
            Capability.ANALYTICS_EXECUTE_REPORT,
        )
    assert all(row["owner"] != "finance" for row in engine.allowed_catalog(authorization(role)))


def test_source_cannot_return_undeclared_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    def source(
        auth: TenantAuthorization, queries: tuple[SourceMetricQuery, ...]
    ) -> tuple[SourceMetricResult, ...]:
        return (
            SourceMetricResult(
                queries[0].source_metric_id,
                1,
                (MetricPoint((("person_email", "forbidden"),), 1),),
                Coverage.COMPLETE,
                None,
                None,
                (),
                "revision",
            ),
        )

    monkeypatch.setitem(engine._PORTS, "commercial", source)
    with pytest.raises(ValueError, match="undeclared_dimensions"):
        _execute_frozen(
            authorization(),
            (replace(selection("request_created_count"), as_of_at=None),),
            timezone_name="America/Guayaquil",
            knowledge_cutoff_at=NOW,
            executed_at=NOW,
            capability=Capability.ANALYTICS_READ_DASHBOARD,
        )
