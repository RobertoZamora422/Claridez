"""Hechos de ejecución batch, distinguiendo registro de ocurrencia económica."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from claridez.organizations.analytics_contracts import (
    Coverage,
    SourceCollection,
    evidence_watermark,
)
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .models import PreparationTransition


@dataclass(frozen=True, slots=True)
class FinanceExecutionFact:
    transition_id: UUID
    reservation_id: UUID
    kind: str
    occurred_at: datetime
    recorded_at: datetime


def execution_facts_for_analytics(
    authorization: TenantAuthorization,
    *,
    as_of_at: datetime,
    knowledge_cutoff_at: datetime,
) -> SourceCollection[FinanceExecutionFact]:
    authorization.require(Capability.FINANCE_READ)
    scoped = PreparationTransition.objects.filter(
        organization_id=authorization.organization_id,
        cause__in=["execution_started", "execution_completed"],
        occurred_at__lte=as_of_at,
    )
    rows = tuple(
        scoped.filter(recorded_at__lte=knowledge_cutoff_at)
        .only(
            "id",
            "preparation_id",
            "cause",
            "occurred_at",
            "recorded_at",
        )
        .order_by("occurred_at", "id")
    )
    items = tuple(
        FinanceExecutionFact(
            row.pk, row.preparation_id, row.cause, row.occurred_at, row.recorded_at
        )
        for row in rows
        if row.recorded_at is not None
    )
    unknown = scoped.filter(recorded_at__isnull=True).exists()
    refs = tuple(f"execution:{row.transition_id}:{row.recorded_at.isoformat()}" for row in items)
    return SourceCollection(
        "operations.finance_execution_facts",
        1,
        items,
        (Coverage.PARTIAL if items else Coverage.UNAVAILABLE) if unknown else Coverage.COMPLETE,
        min((row.recorded_at for row in items), default=None) if unknown else None,
        "execution_registration_history_unavailable" if unknown else None,
        refs,
        evidence_watermark(refs),
    )
