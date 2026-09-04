"""Puertos métricos batch source-owned de Commercial, sin ORM en el contrato público."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from claridez.organizations.analytics_contracts import (
    CohortMember,
    Coverage,
    SourceCollection,
    SourceMetricQuery,
    SourceMetricResult,
    SourceStateMember,
    TemporalMode,
    dimension_values,
    evidence_watermark,
)
from claridez.organizations.analytics_values import MetricAccumulator, time_bucket
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .metric_inputs import INPUTS
from .models import EventRequestHistory, QuotationVersion


@dataclass(frozen=True, slots=True)
class _Batch:
    history: tuple[EventRequestHistory, ...]
    quotes: tuple[QuotationVersion, ...]


def _history(
    authorization: TenantAuthorization, cutoff: datetime
) -> tuple[EventRequestHistory, ...]:
    return tuple(
        EventRequestHistory.objects.filter(
            organization_id=authorization.organization_id,
            created_at__lte=cutoff,
        )
        .only(
            "id",
            "kind",
            "status",
            "request_revision",
            "origin",
            "responsible_membership_id",
            "occurred_at",
            "created_at",
            "event_request_id",
            "analytics_person_id",
        )
        .order_by("event_request_id", "request_revision", "created_at", "id")
    )


def _load(authorization: TenantAuthorization, cutoff: datetime) -> _Batch:
    return _Batch(
        _history(authorization, cutoff),
        tuple(
            QuotationVersion.objects.filter(
                organization_id=authorization.organization_id,
                created_at__lte=cutoff,
            )
            .select_related("quotation")
            .only(
                "id",
                "quotation_id",
                "quotation__event_request_id",
                "version",
                "status",
                "issued_at",
                "accepted_at",
                "acceptance_channel",
                "valid_until",
                "currency",
                "total",
                "event_type_definition_snapshot_id",
                "venue_snapshot_id",
                "space_snapshot_id",
                "updated_at",
            )
            .order_by("quotation_id", "version", "id")
        ),
    )


def _request_dims(row: EventRequestHistory) -> dict[str, object]:
    return {"origin": row.origin, "responsible_membership_id": row.responsible_membership_id}


def _quote_dims(row: QuotationVersion) -> dict[str, object]:
    return {
        "currency": row.currency,
        "event_type_id": row.event_type_definition_snapshot_id,
        "venue_id": row.venue_snapshot_id,
        "space_id": row.space_snapshot_id,
        "acceptance_channel": row.acceptance_channel,
    }


def _metric(query: SourceMetricQuery, batch: _Batch) -> SourceMetricResult:
    metric = query.source_metric_id.removeprefix("commercial.")
    monetary = metric.endswith("_amount")
    acc = MetricAccumulator(query, scale=2 if monetary else 0)
    legacy = any(row.kind == "cutover_state" for row in batch.history)
    if metric in {
        "request_created_count",
        "closed_lost_request_count",
        "closed_lost_latest_issued_quote_amount",
    }:
        assert query.period_start is not None and query.period_end is not None
        is_created = metric == "request_created_count"
        events: dict[UUID, EventRequestHistory] = {}
        for event in batch.history:
            if event.occurred_at is None:
                continue
            if not query.period_start <= event.occurred_at < query.period_end:
                continue
            if (is_created and event.kind == "created") or (
                not is_created and event.kind == "status_changed" and event.status == "closed_lost"
            ):
                events.setdefault(event.event_request_id, event)
        quotes: dict[UUID, list[QuotationVersion]] = defaultdict(list)
        for quote in batch.quotes:
            quotes[quote.quotation.event_request_id].append(quote)
        for event in events.values():
            if monetary:
                eligible = [
                    quote
                    for quote in quotes[event.event_request_id]
                    if quote.issued_at is not None
                    and quote.issued_at <= cast(datetime, event.occurred_at)
                    and quote.issued_at <= query.knowledge_cutoff_at
                ]
                if not eligible:
                    # Sin versión emitida no hay importe: exclusión, no historia fabricada.
                    continue
                last = eligible[-1]
                acc.add(
                    last.total, {**_quote_dims(last), "origin": event.origin}, at=event.occurred_at
                )
            else:
                acc.add(1, _request_dims(event), at=event.occurred_at)
        if legacy:
            acc.reasons.add("commercial_legacy_history_incomplete")
    elif metric in {"quote_issued_count", "quote_accepted_count", "accepted_quote_amount"}:
        assert query.period_start is not None and query.period_end is not None
        accepted = metric != "quote_issued_count"
        for quote in batch.quotes:
            at = quote.accepted_at if accepted else quote.issued_at
            if at is None:
                if (accepted and quote.status == "accepted") or (
                    not accepted and quote.status not in {"draft", "withdrawn"}
                ):
                    acc.reasons.add("commercial_quote_timestamp_missing")
                continue
            if at > query.knowledge_cutoff_at or not query.period_start <= at < query.period_end:
                continue
            acc.add(quote.total if monetary else 1, _quote_dims(quote), at=at)
    elif metric == "open_issued_quote_amount":
        assert query.as_of_at is not None
        states = {
            row.event_request_id: row
            for row in batch.history
            if row.kind != "cutover_state"
            and row.occurred_at is not None
            and row.occurred_at <= query.as_of_at
        }
        latest: dict[UUID, QuotationVersion] = {}
        for quote in batch.quotes:
            if quote.issued_at is not None and quote.issued_at <= query.as_of_at:
                latest[quote.quotation.event_request_id] = quote
        for request_id, state in states.items():
            if state.status != "quoted":
                continue
            selected = latest.get(request_id)
            if selected is None:
                acc.reasons.add("issued_version_not_reconstructible")
                continue
            if selected.status == "withdrawn":
                # No hay evento source-owned de retirada: nunca inferir su fecha desde updated_at.
                acc.reasons.add("withdrawal_time_not_reconstructible")
                continue
            if selected.valid_until <= query.as_of_at:
                continue
            if selected.accepted_at is not None and selected.accepted_at <= query.as_of_at:
                continue
            acc.add(selected.total, {**_quote_dims(selected), "origin": state.origin})
        if legacy:
            acc.reasons.add("commercial_legacy_history_incomplete")
    else:
        raise ValueError("métrica Commercial no soportada")
    refs = tuple(
        f"commercial.EventRequestHistory:{row.pk}:{row.request_revision}:{row.created_at}"
        for row in batch.history
    ) + tuple(
        f"commercial.QuotationVersion:{row.pk}:{row.version}:{row.status}:{row.issued_at}:{row.accepted_at}"
        for row in batch.quotes
    )
    return acc.result(
        provenance=refs,
        watermark=evidence_watermark(refs),
        coverage_from=min(
            (
                row.occurred_at
                for row in batch.history
                if row.kind == "created" and row.occurred_at is not None
            ),
            default=None,
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
    authorization.require(Capability.SALES_READ)
    batches: dict[datetime, _Batch] = {}
    results = []
    for query in queries:
        if query.knowledge_cutoff_at not in batches:
            batches[query.knowledge_cutoff_at] = _load(authorization, query.knowledge_cutoff_at)
        results.append(_metric(query, batches[query.knowledge_cutoff_at]))
    return tuple(results)


def request_cohort(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> SourceCollection[CohortMember]:
    authorization.require(Capability.SALES_READ)
    if (
        query.source_metric_id
        not in {"commercial.request_created_cohort", "commercial.request_person_cohort"}
        or query.mode is not TemporalMode.COHORT
    ):
        raise ValueError("invalid_commercial_cohort_contract")
    assert query.period_start is not None and query.period_end is not None
    rows = _history(authorization, query.knowledge_cutoff_at)
    items: dict[UUID, CohortMember] = {}
    for row in rows:
        if row.kind != "created" or row.occurred_at is None:
            continue
        if not query.period_start <= row.occurred_at < query.period_end:
            continue
        items.setdefault(
            row.event_request_id,
            CohortMember(
                row.event_request_id,
                row.analytics_person_id,
                row.occurred_at,
                dimension_values(
                    origin=row.origin, time_bucket=time_bucket(row.occurred_at, query)
                ),
            ),
        )
    missing_creation = any(row.kind == "cutover_state" for row in rows)
    missing_identity = query.source_metric_id == "commercial.request_person_cohort" and any(
        item.related_id is None for item in items.values()
    )
    missing = missing_creation or missing_identity
    usable = (
        any(item.related_id is not None for item in items.values())
        if missing_identity
        else bool(items)
    )
    coverage = (
        Coverage.PARTIAL
        if missing and usable
        else Coverage.UNAVAILABLE
        if missing
        else Coverage.COMPLETE
    )
    return SourceCollection(
        query.source_metric_id,
        1,
        tuple(items.values()),
        coverage,
        min((item.occurred_at for item in items.values()), default=None),
        "commercial_person_history_missing"
        if missing_identity
        else "commercial_legacy_creation_missing"
        if missing_creation
        else None,
        ("commercial.EventRequestHistory@1",),
        evidence_watermark(
            tuple(f"{row.pk}:{row.request_revision}:{row.created_at.isoformat()}" for row in rows)
        ),
    )


def request_states_as_of(
    authorization: TenantAuthorization,
    query: SourceMetricQuery,
) -> SourceCollection[SourceStateMember]:
    authorization.require(Capability.SALES_READ)
    if (
        query.source_metric_id != "commercial.request_state_as_of"
        or query.mode is not TemporalMode.STATE
    ):
        raise ValueError("invalid_commercial_state_contract")
    assert query.as_of_at is not None
    history = _history(authorization, query.knowledge_cutoff_at)
    states = {
        row.event_request_id: row
        for row in history
        if row.kind != "cutover_state"
        and row.occurred_at is not None
        and row.occurred_at <= query.as_of_at
    }
    items = tuple(
        SourceStateMember(
            request_id,
            row.status,
            dimension_values(**_request_dims(row)),
            row.created_at,
        )
        for request_id, row in states.items()
    )
    missing = any(row.kind == "cutover_state" for row in history)
    coverage = (
        Coverage.PARTIAL
        if missing and items
        else Coverage.UNAVAILABLE
        if missing
        else Coverage.COMPLETE
    )
    return SourceCollection(
        "commercial.request_state_as_of",
        1,
        items,
        coverage,
        min((row.created_at for row in states.values()), default=None),
        "commercial_state_history_incomplete" if missing else None,
        ("commercial.EventRequestHistory@1",),
        evidence_watermark(
            tuple(
                f"{row.pk}:{row.request_revision}:{row.created_at.isoformat()}" for row in history
            )
        ),
    )
