"""Snapshot económico aceptado batch para Finance, sin permisos CRM implícitos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from claridez.organizations.analytics_contracts import (
    Coverage,
    SourceCollection,
    evidence_watermark,
)
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .models import QuotationVersion


@dataclass(frozen=True, slots=True)
class AcceptedSaleEvidence:
    quotation_version_id: UUID
    total: Decimal
    currency: str
    accepted_at: datetime
    venue_id: UUID


def economic_sales_for_analytics(
    authorization: TenantAuthorization,
    quotation_version_ids: tuple[UUID, ...],
    *,
    knowledge_cutoff_at: datetime,
) -> SourceCollection[AcceptedSaleEvidence]:
    authorization.require(Capability.FINANCE_READ)
    rows = tuple(
        QuotationVersion.objects.filter(
            organization_id=authorization.organization_id,
            id__in=quotation_version_ids,
            created_at__lte=knowledge_cutoff_at,
            accepted_at__lte=knowledge_cutoff_at,
        )
        .only("id", "total", "currency", "accepted_at", "venue_snapshot_id", "created_at")
        .order_by("id")
    )
    items = tuple(
        AcceptedSaleEvidence(
            row.pk, row.total, row.currency, row.accepted_at, row.venue_snapshot_id
        )
        for row in rows
        if row.accepted_at is not None
    )
    missing = set(quotation_version_ids) - {row.quotation_version_id for row in items}
    references = tuple(
        f"accepted_quotation:{row.quotation_version_id}:{row.accepted_at.isoformat()}"
        for row in items
    )
    return SourceCollection(
        "commercial.accepted_sale_evidence",
        1,
        items,
        (Coverage.PARTIAL if items else Coverage.UNAVAILABLE) if missing else Coverage.COMPLETE,
        None,
        "accepted_sale_snapshot_missing_at_cutoff" if missing else None,
        references,
        evidence_watermark(references),
    )
