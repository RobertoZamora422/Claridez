"""Puerto batch de Scheduling: replay de eventos y snapshots, no estado vigente retroactivo."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from django.db.models import Q

from claridez.commercial.public import AnalyticsScheduleContext, schedule_context_for_analytics
from claridez.organizations.analytics_contracts import (
    SourceMetricQuery,
    SourceMetricResult,
    evidence_watermark,
)
from claridez.organizations.analytics_values import MetricAccumulator, interval_slices
from claridez.organizations.capabilities import Capability
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.models import Membership
from claridez.organizations.tenant_scope import TenantAuthorization

from .metric_inputs import INPUTS
from .models import ScheduleBlockTarget, ScheduleEvent


@dataclass(frozen=True, slots=True)
class _Batch:
    events: tuple[ScheduleEvent, ...]
    venues: Mapping[str, str]
    targets: tuple[ScheduleBlockTarget, ...]


def _context_digest(context: AnalyticsScheduleContext) -> str:
    return evidence_watermark(
        tuple(f"request:{pk}" for pk in context.request_ids)
        + tuple(f"space:{pk}" for pk in context.space_ids)
    )


def analytics_scope_fingerprint(authorization: TenantAuthorization) -> str | None:
    """Revalida el ámbito actual, sin conceder acceso por poseer un resultado persistido."""
    authorization.require(Capability.SCHEDULE_READ_ANALYTICS)
    return (
        _context_digest(schedule_context_for_analytics(authorization))
        if authorization.role is Membership.Role.COMMERCIAL
        else None
    )


def _load(
    authorization: TenantAuthorization,
    cutoff: datetime,
    context: AnalyticsScheduleContext | None = None,
) -> _Batch:
    oid = authorization.organization_id
    targets = ScheduleBlockTarget.objects.filter(organization_id=oid, created_at__lte=cutoff)
    events = ScheduleEvent.objects.filter(organization_id=oid, recorded_at__lte=cutoff)
    if context is not None:
        targets = targets.filter(space_id__in=context.space_ids)
    materialized_targets = tuple(targets.only("id", "block_id", "space_id", "created_at"))
    if context is not None:
        events = events.filter(
            Q(event_request_id__in=context.request_ids)
            | Q(block_id__in=tuple({row.block_id for row in materialized_targets}))
        )
    return _Batch(
        tuple(
            events.only(
                "id",
                "kind",
                "source",
                "root_reservation_id",
                "event_request_id",
                "block_id",
                "previous_snapshot",
                "new_snapshot",
                "occurred_at",
                "recorded_at",
                "aggregate_revision",
                "analytics_previous_venue_id",
                "analytics_new_venue_id",
            ).order_by("occurred_at", "recorded_at", "id")
        ),
        {},
        materialized_targets,
    )


def _snapshot(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError("snapshot no válido")
    return cast(Mapping[str, object], value)


def _instant(snapshot: Mapping[str, object], key: str) -> datetime:
    value = snapshot.get(key)
    if not isinstance(value, str):
        raise ValueError("timestamp de snapshot ausente")
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.utcoffset() is None:
        raise ValueError("snapshot sin zona temporal")
    return instant.astimezone(UTC)


def _buffer(snapshot: Mapping[str, object], key: str) -> int:
    value = snapshot.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("snapshot de buffer ausente")
    return value


def _metric(query: SourceMetricQuery, batch: _Batch) -> SourceMetricResult:
    metric = query.source_metric_id.removeprefix("scheduling.")
    is_count = metric.endswith("_count")
    acc = MetricAccumulator(query, scale=0 if is_count else 3)
    legacy = any(event.kind == "cutover_snapshot" for event in batch.events)
    if metric in {"reservation_cancelled_count", "reservation_rescheduled_count"}:
        assert query.period_start is not None and query.period_end is not None
        target_kind = metric.removesuffix("_count")
        for event in batch.events:
            if (
                event.kind != target_kind
                or not query.period_start <= event.occurred_at < query.period_end
            ):
                continue
            previous = _snapshot(event.previous_snapshot)
            current = _snapshot(event.new_snapshot)
            prior_space = previous.get("space_id")
            next_space = current.get("space_id")
            values = {
                "space_id": prior_space,
                "from_space_id": prior_space,
                "to_space_id": next_space,
            }
            if event.analytics_previous_venue_id is not None:
                values.update(
                    venue_id=event.analytics_previous_venue_id,
                    from_venue_id=event.analytics_previous_venue_id,
                )
            if event.analytics_new_venue_id is not None:
                values["to_venue_id"] = event.analytics_new_venue_id
            if prior_space is None or (
                target_kind == "reservation_rescheduled" and next_space is None
            ):
                acc.reasons.add("schedule_event_snapshot_incomplete")
                continue
            acc.add(1, values, at=event.occurred_at)
    elif metric == "blocked_minutes":
        assert query.as_of_at is not None
        blocks = {
            row.block_id: row
            for row in batch.events
            if row.block_id is not None and row.occurred_at <= query.as_of_at
        }
        for target in batch.targets:
            if target.created_at > query.as_of_at:
                continue
            block_event = blocks.get(target.block_id)
            if block_event is None:
                acc.reasons.add("block_creation_event_missing")
                continue
            if block_event.kind in {"block_released", "block_cancelled"}:
                continue
            snapshot = _snapshot(block_event.new_snapshot)
            block_venue = snapshot.get("venue_id")
            try:
                slices = interval_slices(
                    _instant(snapshot, "starts_at"),
                    _instant(snapshot, "ends_at"),
                    query,
                )
            except ValueError:
                acc.reasons.add("block_interval_snapshot_missing")
                continue
            for at, seconds in slices:
                acc.add(
                    seconds / Decimal(60),
                    {
                        "space_id": target.space_id,
                        **({"venue_id": block_venue} if block_venue else {}),
                    },
                    at=at,
                )
    elif metric in {
        "confirmed_event_minutes",
        "confirmed_occupied_minutes",
        "confirmed_reservation_count",
    }:
        assert query.as_of_at is not None
        current_by_root: dict[UUID, ScheduleEvent] = {
            row.root_reservation_id: row
            for row in batch.events
            if row.root_reservation_id is not None and row.occurred_at <= query.as_of_at
        }
        for event in current_by_root.values():
            snapshot = _snapshot(event.new_snapshot)
            if snapshot.get("status") != "confirmed":
                continue
            try:
                start, end = _instant(snapshot, "starts_at"), _instant(snapshot, "ends_at")
                if metric == "confirmed_occupied_minutes":
                    start -= timedelta(
                        minutes=_buffer(snapshot, "setup_minutes")
                        + _buffer(snapshot, "buffer_before_minutes")
                    )
                    end += timedelta(
                        minutes=_buffer(snapshot, "teardown_minutes")
                        + _buffer(snapshot, "buffer_after_minutes")
                    )
                slices = interval_slices(start, end, query)
            except ValueError:
                acc.reasons.add("reservation_interval_snapshot_incomplete")
                continue
            if not slices:
                continue
            values = {
                "space_id": snapshot.get("space_id"),
            }
            if event.analytics_new_venue_id is not None:
                values["venue_id"] = event.analytics_new_venue_id
            if is_count:
                # Una raíz, no un conteo por día atravesado por el intervalo.
                acc.add(1, values, at=slices[0][0])
            else:
                for at, seconds in slices:
                    acc.add(seconds / Decimal(60), values, at=at)
    else:
        raise ValueError("métrica Scheduling no soportada")
    references = tuple(
        f"schedule:{r.pk}:{r.aggregate_revision}:{r.recorded_at.isoformat()}" for r in batch.events
    )
    return acc.result(
        provenance=references,
        watermark=evidence_watermark(references),
        reason="scheduling_legacy_history_incomplete" if legacy else None,
        coverage_from=min(
            (r.recorded_at for r in batch.events if r.kind != "cutover_snapshot"), default=None
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
    authorization.require(Capability.SCHEDULE_READ_ANALYTICS)
    context = (
        schedule_context_for_analytics(authorization)
        if authorization.role is Membership.Role.COMMERCIAL
        else None
    )
    if context is not None:
        for query in queries:
            # Bloqueos solo en el espacio explícito de una solicitud del actor.
            # La lectura Analytics no concede inventario global de bloqueos.
            if query.source_metric_id == "scheduling.blocked_minutes" and query.filter_value(
                "space_id"
            ) not in {str(pk) for pk in context.space_ids}:
                raise AuthorizationDenied("El contexto de agenda no está disponible.")
    batches: dict[datetime, _Batch] = {}
    results = []
    for query in queries:
        if query.knowledge_cutoff_at not in batches:
            batches[query.knowledge_cutoff_at] = _load(
                authorization, query.knowledge_cutoff_at, context
            )
        result = _metric(query, batches[query.knowledge_cutoff_at])
        results.append(
            replace(result, authorization_scope_sha256=_context_digest(context))
            if context is not None
            else result
        )
    return tuple(results)
