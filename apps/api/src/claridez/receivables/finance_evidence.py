"""Evidencia económica P10 batch y minimizada para la autoridad Finance P15."""

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

from .models import LegacyEvidenceReview, ReceivableObligation


@dataclass(frozen=True, slots=True)
class ObligationSaleEvidence:
    obligation_id: UUID
    root_reservation_id: UUID
    event_request_id: UUID
    quotation_version_id: UUID
    original_total: Decimal
    currency: str
    confirmed_at: datetime
    recorded_at: datetime


def obligation_sales_for_analytics(
    authorization: TenantAuthorization,
    *,
    knowledge_cutoff_at: datetime,
) -> SourceCollection[ObligationSaleEvidence]:
    authorization.require(Capability.FINANCE_READ)
    rows = tuple(
        ReceivableObligation.objects.filter(
            organization_id=authorization.organization_id,
            created_at__lte=knowledge_cutoff_at,
        )
        .only(
            "id",
            "root_reservation_id",
            "event_request_id",
            "quotation_version_id",
            "original_total",
            "currency",
            "confirmed_at",
            "created_at",
        )
        .order_by("id")
    )
    items = tuple(
        ObligationSaleEvidence(
            row.pk,
            row.root_reservation_id,
            row.event_request_id,
            row.quotation_version_id,
            row.original_total,
            row.currency,
            row.confirmed_at,
            row.created_at,
        )
        for row in rows
    )
    legacy = LegacyEvidenceReview.objects.filter(
        organization_id=authorization.organization_id,
        created_at__lte=knowledge_cutoff_at,
    ).exists()
    references = tuple(f"obligation:{row.pk}:{row.created_at.isoformat()}" for row in rows)
    return SourceCollection(
        "receivables.obligation_sale_evidence",
        1,
        items,
        (Coverage.PARTIAL if items else Coverage.UNAVAILABLE) if legacy else Coverage.COMPLETE,
        min((row.recorded_at for row in items), default=None) if legacy else None,
        "legacy_economic_evidence_without_confirmed_sale" if legacy else None,
        references,
        evidence_watermark(references),
    )
