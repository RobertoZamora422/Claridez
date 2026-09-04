from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from claridez.analytics import services
from claridez.analytics.presets import PRESETS, permitted_preset
from claridez.analytics.registry import METRICS, MetricContract
from claridez.analytics.serializers import ExecutionCreateSerializer, QuerySerializer
from claridez.analytics.views import CatalogView
from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied


def payload(metric: MetricContract = METRICS[0]) -> dict[str, Any]:
    mode = metric.temporal_mode.value
    return {
        "timezone": "America/Guayaquil",
        "metrics": [
            {
                "metric_id": metric.metric_id,
                "metric_version": 1,
                "dimensions": list(metric.required_dimensions),
                "filters": {},
                "period_start": "2020-01-01T00:00:00-05:00" if mode in {"F", "SI", "C"} else None,
                "period_end": "2020-02-01T00:00:00-05:00" if mode in {"F", "SI", "C"} else None,
                "as_of_at": None if mode == "F" else "2020-03-01T00:00:00-05:00",
                "operational_period_id": str(UUID(int=1)) if mode == "FP" else None,
            }
        ],
    }


@pytest.mark.parametrize("metric", METRICS, ids=lambda row: row.versioned_id)
def test_all_53_published_api_contracts_validate(metric: MetricContract) -> None:
    form = QuerySerializer(data=payload(metric))
    assert form.is_valid(), form.errors


@pytest.mark.parametrize(
    "change",
    [
        {"metric_id": "confirmed_space_occupancy_pct"},
        {"metric_version": 2},
        {"dimensions": ["email"]},
        {"filters": {"person_id": str(UUID(int=1))}},
        {"period_start": "2020-01-01T00:00:00"},
        {"as_of_at": "2020-03-01T00:00:00Z"},
        {"period_end": "2019-01-01T00:00:00Z"},
        {"knowledge_cutoff_at": "2020-01-01T00:00:00Z"},
        {"filters": {"responsible_membership_id": "not-a-uuid"}},
        {"filters": {"time_bucket": "quarter"}},
    ],
)
def test_api_rejects_undeclared_filters_versions_and_temporal_inputs(
    change: dict[str, Any],
) -> None:
    value = payload()
    value["metrics"][0].update(change)
    assert not QuerySerializer(data=value).is_valid()


@pytest.mark.parametrize(
    "key", ["knowledge_cutoff_at", "executed_at", "organization_id", "formula", "sql"]
)
def test_client_cannot_set_cutoff_or_execution_authority(key: str) -> None:
    value = payload()
    value[key] = "arbitrary"
    assert not QuerySerializer(data=value).is_valid()


def test_cohort_as_of_cannot_be_future_or_precede_end() -> None:
    metric = next(row for row in METRICS if row.temporal_mode.value == "C")
    value = payload(metric)
    for instant in ["2019-01-01T00:00:00Z", "2999-01-01T00:00:00Z"]:
        value["metrics"][0]["as_of_at"] = instant
        assert not QuerySerializer(data=value).is_valid()


def test_execution_revision_cannot_override_frozen_definition() -> None:
    value = payload()
    value["report_revision_id"] = str(UUID(int=1))
    assert not ExecutionCreateSerializer(data=value).is_valid()
    assert ExecutionCreateSerializer(data={"report_revision_id": str(UUID(int=1))}).is_valid()


def test_presets_reference_existing_contracts_and_are_intersected_not_authorizing() -> None:
    ids = {row.metric_id for row in METRICS}
    for profile, chosen in PRESETS.items():
        assert set(chosen) <= ids
        assert permitted_preset(profile, set()) == []
        allowed = {chosen[0]}
        assert permitted_preset(profile, allowed) == [chosen[0]]


@pytest.mark.parametrize(
    "error_type,status", [(AuthorizationDenied, 403), (TenantAccessDenied, 404)]
)
def test_api_source_or_tenant_denial_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
    status: int,
) -> None:
    def denied(*args: object) -> None:
        raise error_type("private detail must not leak")

    monkeypatch.setattr(services, "catalog_metadata", denied)
    raw = APIRequestFactory().get("/analytics/catalog/")
    raw.user = User(id=UUID(int=1))
    response = CatalogView().get(Request(raw), UUID(int=2))
    assert response.status_code == status
    assert response["Cache-Control"] == "no-store"
    assert "private detail" not in str(getattr(response, "data", ""))


def test_anonymous_api_rejects_before_private_service(monkeypatch: pytest.MonkeyPatch) -> None:
    def should_not_run(*args: object) -> None:
        pytest.fail("anonymous request reached private service")

    monkeypatch.setattr(services, "catalog_metadata", should_not_run)
    raw = APIRequestFactory().get("/analytics/catalog/")
    raw.user = AnonymousUser()
    assert CatalogView().get(Request(raw), UUID(int=2)).status_code == 401


def test_analytics_cross_domain_imports_use_only_approved_ports() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "claridez" / "analytics"
    allowed = {
        "claridez.identity.models",
        "claridez.organizations.capabilities",
        "claridez.organizations.exceptions",
        "claridez.organizations.tenant_scope",
        "claridez.organizations.analytics_contracts",
        "claridez.organizations.analytics_values",
    }
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else ([alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            )
            for name in names:
                if name.startswith("claridez.") and not name.startswith("claridez.analytics"):
                    assert name.endswith(".public") or name in allowed, (path, name)


def test_aware_field_does_not_accept_naive_python_datetime() -> None:
    value = payload()
    value["metrics"][0]["period_start"] = datetime(2020, 1, 1)
    assert not QuerySerializer(data=value).is_valid()
    value["metrics"][0]["period_start"] = datetime(2020, 1, 1, tzinfo=UTC)
    assert QuerySerializer(data=value).is_valid()
