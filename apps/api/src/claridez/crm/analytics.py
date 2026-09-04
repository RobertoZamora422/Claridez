"""Métricas CRM source-owned: historia de interacción y tarea, sin PII nominal."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from decimal import Decimal
from uuid import UUID

from claridez.commercial.public import request_cohort, request_states_as_of
from claridez.organizations.analytics_contracts import (
    SourceMetricQuery,
    SourceMetricResult,
    evidence_watermark,
)
from claridez.organizations.analytics_values import MetricAccumulator
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .metric_inputs import INPUTS
from .models import FollowUpTaskHistory, Interaction


def _first_response(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> SourceMetricResult:
    authorization.require(Capability.INTERACTION_READ_ANALYTICS)
    authorization.require(Capability.SALES_READ)
    assert query.as_of_at is not None
    cohort = request_cohort(
        authorization, replace(query, source_metric_id="commercial.request_created_cohort")
    )
    by_request = {item.subject_id: item for item in cohort.items}
    raw = tuple(
        Interaction.objects.filter(
            organization_id=authorization.organization_id,
            event_request_id__in=by_request,
            created_at__lte=query.knowledge_cutoff_at,
        )
        .only(
            "id",
            "correction_of_id",
            "event_request_id",
            "direction",
            "channel",
            "occurred_at",
            "created_at",
        )
        .order_by("created_at", "id")
    )
    root_for: dict[UUID, UUID] = {}
    effective: dict[UUID, Interaction] = {}
    for row in raw:
        root = (
            root_for.get(row.correction_of_id, row.correction_of_id)
            if row.correction_of_id
            else row.pk
        )
        root_for[row.pk] = root
        effective[root] = row
    winners: dict[UUID, Interaction] = {}
    for row in effective.values():
        if row.event_request_id is None:
            continue
        member = by_request.get(row.event_request_id)
        if (
            member is None
            or row.direction != "outbound"
            or not member.occurred_at <= row.occurred_at <= query.as_of_at
        ):
            continue
        previous = winners.get(row.event_request_id)
        if previous is None or (row.occurred_at, row.created_at, str(row.pk)) < (
            previous.occurred_at,
            previous.created_at,
            str(previous.pk),
        ):
            winners[row.event_request_id] = row
    acc = MetricAccumulator(query, scale=3, average=True)
    for member in cohort.items:
        winner = winners.get(member.subject_id)
        seconds = None
        if winner:
            delta = winner.occurred_at.astimezone(UTC) - member.occurred_at.astimezone(UTC)
            micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
            seconds = Decimal(micros) / 1000000
        acc.add(
            seconds,
            {
                **dict(member.dimensions),
                "channel": winner.channel if winner else None,
            },
            at=member.occurred_at,
        )
    return acc.result(
        coverage=cohort.coverage,
        coverage_from=cohort.coverage_from,
        reason=cohort.coverage_reason,
        provenance=(*cohort.provenance, *(f"crm.Interaction:{r.pk}:{r.created_at}" for r in raw)),
        watermark=evidence_watermark((cohort.watermark, *(f"{r.pk}:{r.created_at}" for r in raw))),
    )


def _without_next_action(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> SourceMetricResult:
    authorization.require(Capability.TASK_READ_ANALYTICS)
    authorization.require(Capability.SALES_READ)
    assert query.as_of_at is not None
    collection = request_states_as_of(
        authorization, replace(query, source_metric_id="commercial.request_state_as_of")
    )
    states = tuple(row for row in collection.items if row.status in {"new", "quoted", "accepted"})
    history = tuple(
        FollowUpTaskHistory.objects.filter(
            organization_id=authorization.organization_id,
            task__event_request_id__in=[item.subject_id for item in states],
            created_at__lte=min(query.as_of_at, query.knowledge_cutoff_at),
        )
        .select_related("task")
        .only(
            "id",
            "task_id",
            "task__event_request_id",
            "status",
            "created_at",
            "revision",
        )
        .order_by("task_id", "revision", "created_at", "id")
    )
    current = {row.task_id: row for row in history}
    covered = {row.task.event_request_id for row in current.values() if row.status == "open"}
    acc = MetricAccumulator(query)
    for state in states:
        if state.subject_id not in covered:
            acc.add(1, dict(state.dimensions))
    return acc.result(
        coverage=collection.coverage,
        coverage_from=collection.coverage_from,
        reason=collection.coverage_reason,
        provenance=(
            *collection.provenance,
            *(f"crm.FollowUpTaskHistory:{r.pk}:{r.revision}" for r in history),
        ),
        watermark=evidence_watermark(
            (collection.watermark, *(f"{r.pk}:{r.revision}" for r in history))
        ),
    )


def fetch_analytics_metrics(
    authorization: TenantAuthorization,
    queries: tuple[SourceMetricQuery, ...],
) -> tuple[SourceMetricResult, ...]:
    for item in queries:
        if item.source_metric_id not in INPUTS:
            raise ValueError("métrica fuente no soportada")
        INPUTS[item.source_metric_id].validate(item)
    result = []
    for query in queries:
        if query.source_metric_id == "crm.first_outbound_response_elapsed_seconds":
            result.append(_first_response(authorization, query))
        elif query.source_metric_id == "crm.open_request_without_next_action_count":
            result.append(_without_next_action(authorization, query))
        else:
            raise ValueError("métrica CRM no soportada")
    return tuple(result)
