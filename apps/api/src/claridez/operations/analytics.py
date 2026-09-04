"""Métricas Operations: hechos, correcciones y estados de su historia propia."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from django.db.models import Q

from claridez.organizations.analytics_contracts import (
    SourceMetricQuery,
    SourceMetricResult,
    evidence_watermark,
)
from claridez.organizations.analytics_values import MetricAccumulator
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .advanced_models import (
    OperationalChangeDecision,
    OperationalIncidentEvent,
    OperationalPhaseFact,
    OperationalVerification,
    OperationalVerificationEvent,
    PostEventClose,
)
from .metric_inputs import INPUTS
from .models import PreparationAnalyticsState, PreparationTransition


def _seconds(start: datetime, end: datetime) -> Decimal:
    delta = end.astimezone(UTC) - start.astimezone(UTC)
    micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    return Decimal(micros) / 1000000


def _transitions(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> tuple[PreparationTransition, ...]:
    return tuple(
        PreparationTransition.objects.filter(
            Q(recorded_at__lte=query.knowledge_cutoff_at) | Q(recorded_at__isnull=True),
            organization_id=authorization.organization_id,
        )
        .only(
            "id",
            "preparation_id",
            "preparation_revision",
            "to_status",
            "cause",
            "occurred_at",
            "recorded_at",
        )
        .order_by("preparation_id", "preparation_revision", "id")
    )


def _preparations(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> SourceMetricResult:
    acc = MetricAccumulator(query)
    rows = _transitions(authorization, query)
    references = tuple(f"transition:{r.pk}:{r.preparation_revision}:{r.recorded_at}" for r in rows)
    missing = any(row.recorded_at is None for row in rows)
    if query.source_metric_id == "operations.execution_completed_count":
        assert query.period_start is not None and query.period_end is not None
        seen: set[UUID] = set()
        for row in rows:
            if (
                row.recorded_at is None
                or row.cause != "execution_completed"
                or not query.period_start <= row.occurred_at < query.period_end
                or row.preparation_id in seen
            ):
                continue
            seen.add(row.preparation_id)
            acc.add(1, {}, at=row.occurred_at)
    else:
        assert query.as_of_at is not None
        evidence = tuple(
            PreparationAnalyticsState.objects.filter(
                organization_id=authorization.organization_id,
                recorded_at__lte=min(query.as_of_at, query.knowledge_cutoff_at),
            )
            .order_by("preparation_id", "preparation_revision")
            .only(
                "id",
                "preparation_id",
                "preparation_revision",
                "status",
                "responsible_membership_id",
                "recorded_at",
            )
        )
        state_by_preparation = {r.preparation_id: r for r in evidence}
        references += tuple(
            f"state:{r.pk}:{r.preparation_revision}:{r.recorded_at}" for r in evidence
        )
        current = {
            row.preparation_id: row
            for row in rows
            if row.recorded_at is not None and row.occurred_at <= query.as_of_at
        }
        needs_responsible = (
            "responsible_membership_id" in query.dimensions
            or query.filter_value("responsible_membership_id") is not None
        )
        for preparation_id in set(current) | set(state_by_preparation):
            historical = state_by_preparation.get(preparation_id)
            if historical:
                state, responsible = historical.status, historical.responsible_membership_id
            elif needs_responsible:
                acc.reasons.add("preparation_responsibility_history_unavailable")
                continue
            else:
                state, responsible = current[preparation_id].to_status, None
            if state in {"preparing", "ready", "in_progress"}:
                acc.add(1, {"status": state, "responsible_membership_id": responsible})
    return acc.result(
        provenance=references,
        watermark=evidence_watermark(references),
        reason="legacy_transition_recorded_at_missing" if missing else None,
        coverage_from=min(
            (row.recorded_at for row in rows if row.recorded_at is not None), default=None
        ),
    )


def _verifications(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> SourceMetricResult:
    assert query.as_of_at is not None
    acc = MetricAccumulator(query)
    verifications = tuple(
        OperationalVerification.objects.filter(
            organization_id=authorization.organization_id,
            created_at__lte=min(query.as_of_at, query.knowledge_cutoff_at),
        )
        .select_related("definition")
        .only(
            "id",
            "definition_id",
            "definition__phase",
            "definition__role_key",
            "definition__is_required",
        )
    )
    changes = tuple(
        OperationalChangeDecision.objects.filter(
            organization_id=authorization.organization_id,
            approved=True,
            decided_at__lte=query.as_of_at,
            created_at__lte=query.knowledge_cutoff_at,
            proposal__scope="verification",
            proposal__target_id__in=[r.pk for r in verifications],
            proposal__created_at__lte=query.knowledge_cutoff_at,
        )
        .select_related("proposal")
        .only(
            "id",
            "decided_at",
            "proposal_id",
            "proposal__target_id",
            "proposal__before_payload",
            "proposal__proposed_payload",
        )
        .order_by("decided_at", "id")
    )
    by_verification = {row.proposal.target_id: row for row in changes}
    events = tuple(
        OperationalVerificationEvent.objects.filter(
            organization_id=authorization.organization_id,
            verification_id__in=[r.pk for r in verifications],
            occurred_at__lte=query.as_of_at,
            created_at__lte=query.knowledge_cutoff_at,
        )
        .only("id", "verification_id", "verification_revision", "to_status")
        .order_by("verification_id", "verification_revision", "id")
    )
    current = {row.verification_id: row.to_status for row in events}
    for row in verifications:
        if row.definition is None:
            acc.reasons.add("verification_initial_definition_missing")
            continue
        required, role = row.definition.is_required, row.definition.role_key
        if row.pk in by_verification:
            proposal = by_verification[row.pk].proposal
            historical = proposal.before_payload | proposal.proposed_payload
            if not isinstance(historical.get("is_required"), bool) or not isinstance(
                historical.get("role_key"), str
            ):
                acc.reasons.add("verification_change_snapshot_incomplete")
                continue
            required, role = historical["is_required"], historical["role_key"]
        if required and current.get(row.pk, "pending") == "pending":
            acc.add(1, {"phase": row.definition.phase, "role_key": role})
    refs = tuple(f"operations.OperationalVerification:{row.pk}" for row in verifications) + tuple(
        f"operations.OperationalVerificationEvent:{row.pk}:{row.verification_revision}"
        for row in events
    )
    refs += tuple(
        f"operations.OperationalChangeDecision:{row.pk}:{row.decided_at}" for row in changes
    )
    return acc.result(provenance=refs, watermark=evidence_watermark(refs))


def _phase_duration(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> SourceMetricResult:
    assert query.period_start is not None and query.period_end is not None
    acc = MetricAccumulator(query, scale=3, average=True)
    rows = tuple(
        OperationalPhaseFact.objects.filter(
            organization_id=authorization.organization_id,
            created_at__lte=query.knowledge_cutoff_at,
        )
        .only(
            "id", "preparation_id", "phase", "fact_kind", "observed_at", "corrects_id", "created_at"
        )
        .order_by("created_at", "id")
    )
    effective: dict[tuple[UUID, str, str], OperationalPhaseFact] = {}
    for row in rows:
        effective[(row.preparation_id, row.phase, row.fact_kind)] = row
    for (_, phase, kind), completed in effective.items():
        if (
            kind != "completed"
            or not query.period_start <= completed.observed_at < query.period_end
        ):
            continue
        started = effective.get((completed.preparation_id, phase, "started"))
        duration = None if started is None else _seconds(started.observed_at, completed.observed_at)
        if duration is None or duration < 0:
            acc.reasons.add("phase_pair_incomplete_or_negative")
            duration = None
        acc.add(duration, {"phase": phase}, at=completed.observed_at)
    refs = tuple(f"operations.OperationalPhaseFact:{row.pk}:{row.created_at}" for row in rows)
    return acc.result(provenance=refs, watermark=evidence_watermark(refs))


def _incidents(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> SourceMetricResult:
    assert query.period_start is not None and query.period_end is not None
    acc = MetricAccumulator(query)
    rows = tuple(
        OperationalIncidentEvent.objects.filter(
            organization_id=authorization.organization_id,
            created_at__lte=query.knowledge_cutoff_at,
        )
        .select_related("incident")
        .only(
            "id",
            "incident_id",
            "incident__incident_type",
            "kind",
            "severity",
            "occurred_at",
            "corrects_id",
            "created_at",
        )
        .order_by("created_at", "id")
    )
    roots: dict[UUID, UUID] = {}
    opened: dict[UUID, OperationalIncidentEvent] = {}
    effective: dict[UUID, OperationalIncidentEvent] = {}
    for row in rows:
        root_id = roots.get(row.corrects_id, row.corrects_id) if row.corrects_id else row.pk
        roots[row.pk] = root_id
        if row.kind == "opened":
            opened[root_id] = row
        effective[root_id] = row
    for root_id, original in opened.items():
        if not query.period_start <= original.occurred_at < query.period_end:
            continue
        leaf = effective[root_id]
        acc.add(
            1,
            {"incident_type": leaf.incident.incident_type, "severity": leaf.severity},
            at=original.occurred_at,
        )
    refs = tuple(f"operations.OperationalIncidentEvent:{row.pk}:{row.created_at}" for row in rows)
    return acc.result(provenance=refs, watermark=evidence_watermark(refs))


def _post_close(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> SourceMetricResult:
    assert query.period_start is not None and query.period_end is not None
    acc = MetricAccumulator(query, scale=3, average=True)
    closes = tuple(
        PostEventClose.objects.filter(
            organization_id=authorization.organization_id,
            closed_at__gte=query.period_start,
            closed_at__lt=query.period_end,
            created_at__lte=query.knowledge_cutoff_at,
        ).only("id", "preparation_id", "closed_at")
    )
    transitions = _transitions(authorization, query)
    completed = {
        row.preparation_id: row
        for row in transitions
        if row.cause == "execution_completed" and row.recorded_at is not None
    }
    for close in closes:
        execution = completed.get(close.preparation_id)
        value = None if execution is None else _seconds(execution.occurred_at, close.closed_at)
        if value is None or value < 0:
            acc.reasons.add("execution_completion_knowledge_not_reconstructible")
            value = None
        acc.add(value, {}, at=close.closed_at)
    refs = tuple(f"operations.PostEventClose:{row.pk}" for row in closes) + tuple(
        f"operations.PreparationTransition:{row.pk}:{row.recorded_at}" for row in transitions
    )
    return acc.result(provenance=refs, watermark=evidence_watermark(refs))


def fetch_analytics_metrics(
    authorization: TenantAuthorization,
    queries: tuple[SourceMetricQuery, ...],
) -> tuple[SourceMetricResult, ...]:
    for item in queries:
        if item.source_metric_id not in INPUTS:
            raise ValueError("métrica fuente no soportada")
        INPUTS[item.source_metric_id].validate(item)
    handlers = {
        "operations.preparation_open_count": _preparations,
        "operations.execution_completed_count": _preparations,
        "operations.pending_required_verification_count": _verifications,
        "operations.phase_duration_seconds": _phase_duration,
        "operations.incident_opened_count": _incidents,
        "operations.post_event_close_elapsed_seconds": _post_close,
    }
    results = []
    for query in queries:
        authorization.require(
            Capability.OPERATION_INCIDENT_READ
            if query.source_metric_id == "operations.incident_opened_count"
            else Capability.OPERATION_READ
        )
        if query.source_metric_id not in handlers:
            raise ValueError("métrica Operations no soportada")
        results.append(handlers[query.source_metric_id](authorization, query))
    return tuple(results)
