"""Fan-in P15 por puertos públicos, sin ORM/SQL de otros dominios ni fórmulas duplicadas."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone

import claridez.commercial.public as commercial_port
import claridez.crm.public as crm_port
import claridez.finance.public as finance_port
import claridez.operations.public as operations_port
import claridez.people.public as people_port
import claridez.receivables.public as receivables_port
import claridez.resources.public as resources_port
import claridez.scheduling.public as scheduling_port
from claridez.organizations.analytics_contracts import (
    Coverage,
    DimensionValues,
    MetricPoint,
    MetricValueStatus,
    SourceInputContract,
    SourceMetricQuery,
    SourceMetricResult,
    evidence_watermark,
    worst_coverage,
)
from claridez.organizations.analytics_values import MetricAccumulator
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.tenant_scope import TenantAuthorization

from .errors import invalid
from .registry import (
    CATALOG_HASH,
    CATALOG_VERSION,
    METRICS,
    MetricContract,
    contract,
    public_catalog,
)

MAX_QUERY_METRICS = 53
MAX_QUERY_ROWS = 2000
MAX_QUERY_BYTES = 512 * 1024
MAX_FILTER_VALUE_CHARACTERS = 80


@dataclass(frozen=True, slots=True)
class MetricSelection:
    metric_id: str
    metric_version: int = 1
    dimensions: tuple[str, ...] = ()
    filters: tuple[tuple[str, str], ...] = ()
    period_start: datetime | None = None
    period_end: datetime | None = None
    as_of_at: datetime | None = None
    operational_period_id: UUID | None = None

    def source_query(
        self, *, timezone_name: str, knowledge_cutoff_at: datetime, executed_at: datetime
    ) -> SourceMetricQuery:
        metric = contract(self.metric_id, self.metric_version)
        value = SourceMetricQuery(
            metric.sources[0].source_metric_id,
            metric.sources[0].source_metric_version,
            metric.temporal_mode,
            self.period_start,
            self.period_end,
            self.as_of_at,
            knowledge_cutoff_at,
            executed_at,
            timezone_name,
            self.dimensions,
            self.filters,
            self.operational_period_id,
        )
        SourceInputContract(
            metric.temporal_mode.value,
            " ".join(metric.dimensions),
            " ".join(metric.required_dimensions),
        ).validate(value)
        for name, selected in value.filters:
            if not isinstance(selected, str) or len(selected) > MAX_FILTER_VALUE_CHARACTERS:
                raise ValueError("invalid_filter_value")
            if name.endswith("_id"):
                UUID(selected)
            elif name == "time_bucket" and selected not in {"day", "week", "month"}:
                raise ValueError("invalid_time_bucket")
            elif name == "currency" and (
                len(selected) != 3
                or not selected.isascii()
                or not selected.isupper()
                or not selected.isalpha()
            ):
                raise ValueError("invalid_currency")
        return value


@dataclass(frozen=True, slots=True)
class MetricOutput:
    metric_id: str
    metric_version: int
    unit: str
    result: SourceMetricResult


@dataclass(frozen=True, slots=True)
class QueryOutput:
    selections: tuple[MetricSelection, ...]
    timezone_name: str
    knowledge_cutoff_at: datetime
    executed_at: datetime
    metrics: tuple[MetricOutput, ...]
    catalog_version: str = CATALOG_VERSION
    catalog_hash: str = CATALOG_HASH


def authorize_selections(
    authorization: TenantAuthorization,
    selections: tuple[MetricSelection, ...],
    capability: Capability,
) -> None:
    authorization.require(capability)
    if not 1 <= len(selections) <= MAX_QUERY_METRICS:
        raise invalid("metric_selection_limit", "Seleccione entre 1 y 53 métricas.")
    if len({(row.metric_id, row.metric_version) for row in selections}) != len(selections):
        raise invalid("duplicate_metric_selection", "La selección contiene métricas duplicadas.")
    for selected in selections:
        required_capabilities = contract(
            selected.metric_id, selected.metric_version
        ).required_capabilities
        for required in required_capabilities:
            authorization.require(required)
        if capability in {Capability.ANALYTICS_CREATE_EXPORT, Capability.ANALYTICS_DOWNLOAD_EXPORT}:
            if Capability.FINANCE_READ.value in required_capabilities:
                authorization.require(Capability.FINANCE_EXPORT)
            if Capability.SCHEDULE_READ_ANALYTICS.value in required_capabilities:
                authorization.require(Capability.SCHEDULE_EXPORT)


def allowed_catalog(authorization: TenantAuthorization) -> tuple[dict[str, object], ...]:
    authorization.require(Capability.ANALYTICS_READ_DASHBOARD)
    allowed = {item.value for item in capabilities_for_role(authorization.role)}
    return tuple(
        row
        for row, metric in zip(public_catalog(), METRICS, strict=True)
        if set(metric.required_capabilities) <= allowed
    )


def _composed(
    authorization: TenantAuthorization, metric: MetricContract, query: SourceMetricQuery
) -> SourceMetricResult:
    cohort = commercial_port.request_cohort(
        authorization,
        replace(
            query,
            source_metric_id="commercial.request_person_cohort"
            if metric.metric_id == "distinct_canonical_request_person_count"
            else "commercial.request_created_cohort",
        ),
    )
    acc = MetricAccumulator(query)
    cohorts: dict[DimensionValues, set[UUID]] = defaultdict(set)
    for member in cohort.items:
        key = acc.key(dict(member.dimensions), member.occurred_at)
        if key is not None:
            cohorts[key].add(member.subject_id)
    if not cohorts and not query.dimensions:
        cohorts[()] = set()
    reasons = tuple(reason for reason in (cohort.coverage_reason,) if reason)
    if metric.metric_id == "request_to_confirmed_sale_conversion_rate":
        confirmations = finance_port.confirmed_sale_cohort(
            authorization, replace(query, source_metric_id="finance.confirmed_sale_cohort")
        )
        coverage = worst_coverage(cohort.coverage, confirmations.coverage)
        if confirmations.coverage_reason:
            reasons += (confirmations.coverage_reason,)
        confirmed_ids = {row.subject_id for row in confirmations.items}
        points = []
        for key, members in cohorts.items():
            matched = len(members & confirmed_ids)
            value = (
                (Decimal(matched) / len(members) * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
                if members and coverage is Coverage.COMPLETE
                else None
            )
            points.append(
                MetricPoint(
                    key,
                    value,
                    MetricValueStatus.VALUE
                    if value is not None
                    else MetricValueStatus.NOT_CALCULABLE,
                    eligible_count=len(members),
                    sample_size=matched,
                )
            )
        refs = (cohort.watermark, confirmations.watermark)
        provenance = ("commercial.request_created_cohort@1", "finance.confirmed_sale_cohort@1")
    else:
        clusters = people_port.canonical_clusters_as_of(
            authorization,
            replace(query, source_metric_id="people.canonical_cluster_as_of"),
            tuple({row.related_id for row in cohort.items if row.related_id is not None}),
        )
        coverage = worst_coverage(cohort.coverage, clusters.coverage)
        if clusters.coverage_reason:
            reasons += (clusters.coverage_reason,)
        by_person = {row.person_id: row.canonical_person_id for row in clusters.items}
        by_request = {
            row.subject_id: by_person.get(row.related_id)
            for row in cohort.items
            if row.related_id is not None
        }
        missing = {row.subject_id for row in cohort.items if by_request.get(row.subject_id) is None}
        if missing:
            coverage = worst_coverage(
                coverage, Coverage.PARTIAL if by_person else Coverage.UNAVAILABLE
            )
            reasons += ("canonical_cluster_missing_for_cohort_member",)
        points = []
        for key, members in cohorts.items():
            known = {
                by_request[subject] for subject in members if by_request.get(subject) is not None
            }
            count = (
                len(known)
                if coverage is Coverage.COMPLETE or (known and coverage is Coverage.PARTIAL)
                else None
            )
            points.append(
                MetricPoint(
                    key,
                    count,
                    MetricValueStatus.VALUE
                    if count is not None
                    else MetricValueStatus.NOT_CALCULABLE,
                )
            )
        refs = (cohort.watermark, clusters.watermark)
        provenance = ("commercial.request_person_cohort@1", "people.canonical_cluster_as_of@1")
    return SourceMetricResult(
        metric.metric_id,
        metric.metric_version,
        tuple(points),
        coverage,
        cohort.coverage_from,
        ";".join(reasons) or None,
        provenance,
        evidence_watermark(refs),
    )


type BatchPort = Callable[
    [TenantAuthorization, tuple[SourceMetricQuery, ...]], tuple[SourceMetricResult, ...]
]
_PORTS: dict[str, BatchPort] = {
    "commercial": commercial_port.fetch_analytics_metrics,
    "crm": crm_port.fetch_analytics_metrics,
    "scheduling": scheduling_port.fetch_analytics_metrics,
    "operations": operations_port.fetch_analytics_metrics,
    "receivables": receivables_port.fetch_analytics_metrics,
    "finance": finance_port.fetch_analytics_metrics,
    "resources": resources_port.fetch_analytics_metrics,
}


def execute_query(
    authorization: TenantAuthorization,
    selections: tuple[MetricSelection, ...],
    *,
    timezone_name: str,
    capability: Capability,
) -> QueryOutput:
    """Nueva consulta: no existe un argumento para un cutoff elegido por el cliente."""
    now = timezone.now()
    return _execute_frozen(
        authorization,
        selections,
        timezone_name=timezone_name,
        knowledge_cutoff_at=now,
        executed_at=now,
        capability=capability,
    )


def _execute_frozen(
    authorization: TenantAuthorization,
    selections: tuple[MetricSelection, ...],
    *,
    timezone_name: str,
    knowledge_cutoff_at: datetime,
    executed_at: datetime,
    capability: Capability,
) -> QueryOutput:
    """Solo uso interno con parámetros congelados: nunca se expone desde una vista."""
    authorize_selections(authorization, selections, capability)
    ZoneInfo(timezone_name)
    grouped: dict[str, list[tuple[MetricContract, SourceMetricQuery]]] = defaultdict(list)
    for selected in selections:
        metric = contract(selected.metric_id, selected.metric_version)
        source_query = selected.source_query(
            timezone_name=timezone_name,
            knowledge_cutoff_at=knowledge_cutoff_at,
            executed_at=executed_at,
        )
        grouped[metric.owner].append((metric, source_query))
    values: dict[str, MetricOutput] = {}
    for owner, requests in grouped.items():
        if owner == "analytics":
            results = tuple(_composed(authorization, metric, query) for metric, query in requests)
        else:
            results = _PORTS[owner](authorization, tuple(query for _, query in requests))
        if len(results) != len(requests):
            raise ValueError("source_batch_result_count_mismatch")
        for (metric, query), result in zip(requests, results, strict=True):
            expected = metric.metric_id if owner == "analytics" else query.source_metric_id
            if (result.source_metric_id, result.source_metric_version) != (expected, 1):
                raise ValueError("source_metric_contract_mismatch")
            for point in result.points:
                if set(dict(point.dimensions)) != set(query.dimensions):
                    raise ValueError("source_returned_undeclared_dimensions")
            values[metric.metric_id] = MetricOutput(
                metric.metric_id, metric.metric_version, metric.unit, result
            )
    output = QueryOutput(
        selections,
        timezone_name,
        knowledge_cutoff_at,
        executed_at,
        tuple(values[row.metric_id] for row in selections),
    )
    if sum(len(row.result.points) for row in output.metrics) > MAX_QUERY_ROWS:
        raise invalid("result_row_limit", "Reduzca el rango o las dimensiones de la consulta.")
    if len(json.dumps(output_payload(output), separators=(",", ":")).encode()) > MAX_QUERY_BYTES:
        raise invalid("result_payload_limit", "El resultado supera el límite de tamaño.")
    return output


def selection_payload(row: MetricSelection) -> dict[str, object]:
    return {
        "metric_id": row.metric_id,
        "metric_version": row.metric_version,
        "dimensions": list(row.dimensions),
        "filters": dict(row.filters),
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "as_of_at": row.as_of_at.isoformat() if row.as_of_at else None,
        "operational_period_id": str(row.operational_period_id)
        if row.operational_period_id
        else None,
    }


def selection_from_payload(data: dict[str, object]) -> MetricSelection:
    allowed = {
        "metric_id",
        "metric_version",
        "dimensions",
        "filters",
        "period_start",
        "period_end",
        "as_of_at",
        "operational_period_id",
    }
    if set(data) - allowed:
        raise ValueError("unknown_metric_selection_field")
    return MetricSelection(
        str(data["metric_id"]),
        cast(int, data.get("metric_version", 1)),
        tuple(cast(list[str], data.get("dimensions", []))),
        tuple(sorted(cast(dict[str, str], data.get("filters", {})).items())),
        datetime.fromisoformat(str(data["period_start"])) if data.get("period_start") else None,
        datetime.fromisoformat(str(data["period_end"])) if data.get("period_end") else None,
        datetime.fromisoformat(str(data["as_of_at"])) if data.get("as_of_at") else None,
        UUID(str(data["operational_period_id"])) if data.get("operational_period_id") else None,
    )


def output_payload(output: QueryOutput) -> dict[str, object]:
    return {
        "catalog_version": output.catalog_version,
        "catalog_hash": output.catalog_hash,
        "timezone": output.timezone_name,
        "knowledge_cutoff_at": output.knowledge_cutoff_at.isoformat(),
        "executed_at": output.executed_at.isoformat(),
        "selection": [selection_payload(row) for row in output.selections],
        "metrics": [
            {
                "metric_id": row.metric_id,
                "metric_version": row.metric_version,
                "unit": row.unit,
                "coverage": row.result.coverage.value,
                "coverage_from": row.result.coverage_from.isoformat()
                if row.result.coverage_from
                else None,
                "coverage_reason": row.result.coverage_reason,
                "provisional": row.result.provisional,
                "exclusions": list(row.result.exclusions),
                "source_metrics": [
                    {
                        "source_metric_id": source.source_metric_id,
                        "source_metric_version": source.source_metric_version,
                    }
                    for source in contract(row.metric_id, row.metric_version).sources
                ],
                "provenance": {
                    "watermark": row.result.watermark,
                    "references_sha256": evidence_watermark(row.result.provenance),
                    "reference_count": len(row.result.provenance),
                    "authorization_scope_sha256": row.result.authorization_scope_sha256,
                },
                "points": [
                    {
                        "dimensions": dict(point.dimensions),
                        "value": str(point.value)
                        if isinstance(point.value, Decimal)
                        else point.value,
                        "status": point.status.value,
                        "sample_size": point.sample_size,
                        "eligible_count": point.eligible_count,
                    }
                    for point in row.result.points
                ],
            }
            for row in output.metrics
        ],
    }
