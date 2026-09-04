"""Metadata mínima de periodos: la pertenencia y la moneda siguen bajo Finance."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .models import OperationalPeriod


@dataclass(frozen=True, slots=True)
class AnalyticsPeriod:
    id: UUID
    starts_on: date
    ends_on: date
    currency: str
    closed: bool


def periods_for_analytics(authorization: TenantAuthorization) -> tuple[AnalyticsPeriod, ...]:
    authorization.require(Capability.FINANCE_READ)
    return tuple(
        AnalyticsPeriod(
            row["id"],
            row["starts_on"],
            row["ends_on"],
            row["currency"],
            row["close_snapshot__id"] is not None,
        )
        for row in OperationalPeriod.objects.filter(organization_id=authorization.organization_id)
        .order_by("-starts_on", "id")
        .values("id", "starts_on", "ends_on", "currency", "close_snapshot__id")[:120]
    )
