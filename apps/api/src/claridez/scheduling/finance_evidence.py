"""Identidad de raíz y sede histórica de cada reserva, sin exponer agenda mutable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .models import Reservation


@dataclass(frozen=True, slots=True)
class ReservationFinanceIdentity:
    reservation_id: UUID
    root_reservation_id: UUID
    venue_id: UUID
    recorded_at: datetime


def reservation_identities_for_analytics(
    authorization: TenantAuthorization,
    *,
    knowledge_cutoff_at: datetime,
) -> tuple[ReservationFinanceIdentity, ...]:
    authorization.require(Capability.FINANCE_READ)
    return tuple(
        ReservationFinanceIdentity(row.pk, row.root_id, row.space.venue_id, row.created_at)
        for row in Reservation.objects.select_related("space")
        .filter(
            organization_id=authorization.organization_id,
            created_at__lte=knowledge_cutoff_at,
        )
        .only("id", "root_id", "space_id", "space__venue_id", "created_at")
        .order_by("id")
    )
