"""Puerto P15 Resources: ledger físico y evidencia histórica source-owned."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from claridez.organizations.analytics_contracts import (
    SourceMetricQuery,
    SourceMetricResult,
    evidence_watermark,
)
from claridez.organizations.analytics_values import MetricAccumulator
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .metric_inputs import INPUTS
from .models import (
    Resource,
    ResourceAssignment,
    ResourceEvent,
    ResourceRequirement,
    ResourceUnavailability,
    StockMovement,
)


def _stock(authorization: TenantAuthorization, query: SourceMetricQuery) -> SourceMetricResult:
    rows = (
        StockMovement.objects.filter(
            organization_id=authorization.organization_id,
            created_at__lte=query.knowledge_cutoff_at,
        )
        .select_related("resource")
        .only(
            "id",
            "resource_id",
            "resource__base_unit_id",
            "location_id",
            "quantity",
            "effect",
            "direction",
            "kind",
            "occurred_at",
            "created_at",
        )
    )
    if query.as_of_at is not None:
        rows = rows.filter(occurred_at__lte=query.as_of_at)
    else:
        assert query.period_start is not None and query.period_end is not None
        rows = rows.filter(occurred_at__gte=query.period_start, occurred_at__lt=query.period_end)
    acc = MetricAccumulator(query, scale=6)
    for movement in rows:
        acc.add(
            movement.effect if query.as_of_at is not None else movement.quantity,
            {
                "resource_id": movement.resource_id,
                "unit_id": movement.resource.base_unit_id,
                "location_id": movement.location_id,
                "kind": movement.kind,
                "direction": movement.direction,
            },
            at=movement.occurred_at,
        )
    references = tuple(f"resources.StockMovement:{r.pk}:{r.created_at}" for r in rows)
    return acc.result(provenance=references, watermark=evidence_watermark(references))


def _payload(event: ResourceEvent) -> Mapping[str, object]:
    return cast(Mapping[str, object], event.payload)


def _intersects(payload: Mapping[str, object], query: SourceMetricQuery) -> bool:
    start = datetime.fromisoformat(str(payload["starts_at"]))
    end = datetime.fromisoformat(str(payload["ends_at"])) if payload.get("ends_at") else None
    if query.period_start is None:
        assert query.as_of_at is not None
        return start <= query.as_of_at and (end is None or query.as_of_at < end)
    assert query.period_end is not None
    return start < query.period_end and (end is None or end > query.period_start)


def _state(authorization: TenantAuthorization, query: SourceMetricQuery) -> SourceMetricResult:
    assert query.as_of_at is not None
    oid = authorization.organization_id
    acc = MetricAccumulator(query, scale=6)
    events = tuple(
        ResourceEvent.objects.filter(
            organization_id=oid,
            kind="analytics_state_recorded",
            created_at__lte=query.knowledge_cutoff_at,
            occurred_at__lte=query.as_of_at,
        )
        .only("id", "aggregate_kind", "aggregate_id", "payload", "created_at", "occurred_at")
        .order_by("created_at", "id")
    )
    latest: dict[tuple[str, UUID], ResourceEvent] = {}
    for event in events:
        key = (event.aggregate_kind, event.aggregate_id)
        previous = latest.get(key)
        if previous is None or int(str(_payload(event)["source_revision"])) > int(
            str(_payload(previous)["source_revision"])
        ):
            latest[key] = event
    snapshots = {key: _payload(event) for key, event in latest.items()}
    requirements = {
        key[1]: val for key, val in snapshots.items() if key[0] == "resources_resourcerequirement"
    }
    assignments = {
        key[1]: val for key, val in snapshots.items() if key[0] == "resources_resourceassignment"
    }
    unavailable = {
        key[1]: val
        for key, val in snapshots.items()
        if key[0] == "resources_resourceunavailability"
    }
    # Filas previas sin captura no se reconstruyen desde su status actual.
    model_ids = (
        ((ResourceUnavailability, unavailable),)
        if query.source_metric_id == "resources.resource_unavailability_quantity"
        else ((ResourceAssignment, assignments),)
        if query.source_metric_id == "resources.event_allocated_quantity"
        else ((ResourceRequirement, requirements),)
        if query.source_metric_id == "resources.event_required_quantity"
        else ((ResourceRequirement, requirements), (ResourceAssignment, assignments))
    )
    for model, known in model_ids:
        existing = model.objects.filter(
            organization_id=oid, created_at__lte=min(query.as_of_at, query.knowledge_cutoff_at)
        )
        resource_filter = query.filter_value("resource_id")
        if resource_filter is not None:
            existing = existing.filter(resource_id=resource_filter)
        if existing.exclude(pk__in=known).exists():
            acc.reasons.add("resources_state_history_not_recorded")
    replaced_requirements = {
        str(p["predecessor_id"]) for p in requirements.values() if p.get("predecessor_id")
    }
    replaced_assignments = {
        str(p["predecessor_id"]) for p in assignments.values() if p.get("predecessor_id")
    }
    allocated: dict[str, Decimal] = defaultdict(Decimal)
    active_states = {"reserved", "issued", "custody", "fulfilled"}
    for assignment_id, payload in assignments.items():
        if (
            str(assignment_id) in replaced_assignments
            or payload["status"] not in active_states
            or not _intersects(payload, query)
        ):
            continue
        allocated[str(payload.get("requirement_id"))] += Decimal(str(payload["quantity"]))
        if query.source_metric_id == "resources.event_allocated_quantity":
            acc.add(
                Decimal(str(payload["quantity"])),
                {
                    **payload,
                    "assignment_status": payload["status"],
                },
            )
    if query.source_metric_id in {
        "resources.event_required_quantity",
        "resources.event_shortage_quantity",
    }:
        for requirement_id, payload in requirements.items():
            if (
                str(requirement_id) in replaced_requirements
                or payload["status"] == "cancelled"
                or not _intersects(payload, query)
            ):
                continue
            value = Decimal(str(payload["quantity"]))
            if query.source_metric_id == "resources.event_shortage_quantity":
                value = (
                    max(value - allocated[str(requirement_id)], Decimal(0))
                    if (payload["status"] in {"open", "shortage"})
                    else Decimal(0)
                )
            acc.add(value, payload)
    elif query.source_metric_id == "resources.resource_unavailability_quantity":
        replaced = {str(p["corrects_id"]) for p in unavailable.values() if p.get("corrects_id")}
        for unavailability_id, payload in unavailable.items():
            if (
                str(unavailability_id) not in replaced
                and payload["is_active"] is True
                and _intersects(payload, query)
            ):
                acc.add(Decimal(str(payload["quantity"])), payload)
    return acc.result(
        provenance=tuple(f"resources.ResourceEvent:{r.pk}:{r.created_at}" for r in events),
        watermark=evidence_watermark(tuple(f"{r.pk}:{r.created_at}" for r in events)),
        coverage_from=min((e.created_at for e in events), default=None),
    )


def fetch_analytics_metrics(
    authorization: TenantAuthorization,
    queries: tuple[SourceMetricQuery, ...],
) -> tuple[SourceMetricResult, ...]:
    authorization.require(Capability.RESOURCE_READ)
    for query in queries:
        if query.source_metric_id not in INPUTS:
            raise ValueError("métrica Resources no soportada")
        INPUTS[query.source_metric_id].validate(query)
    resource_ids = {UUID(value) for q in queries if (value := q.filter_value("resource_id"))}
    if resource_ids:
        units = dict(
            Resource.objects.filter(
                organization_id=authorization.organization_id,
                pk__in=resource_ids,
            ).values_list("id", "base_unit_id")
        )
        for q in queries:
            resource_id, unit_id = q.filter_value("resource_id"), q.filter_value("unit_id")
            if resource_id and (
                UUID(resource_id) not in units
                or (unit_id and UUID(unit_id) != units[UUID(resource_id)])
            ):
                raise ValueError("resource_unit_partition_unavailable")
    return tuple(
        _stock(authorization, q)
        if q.source_metric_id
        in {
            "resources.stock_on_hand_quantity",
            "resources.stock_movement_quantity",
        }
        else _state(authorization, q)
        for q in queries
    )
