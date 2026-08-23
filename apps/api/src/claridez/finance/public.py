"""Puerto público inmutable de resultados financieros operativos P11."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import UUID

from claridez.organizations.tenant_scope import TenantAuthorization

from .services import _overview_authorized


@dataclass(frozen=True, slots=True)
class EventProfitabilityProjection:
    root_reservation_id: UUID
    recognized_revenue: Decimal
    direct_cost: Decimal
    variable_expense: Decimal
    recurring_expense: Decimal
    operating_result: Decimal
    profitability_percentage: Decimal | None


def event_profitability(
    authorization: TenantAuthorization, root_reservation_id: UUID
) -> EventProfitabilityProjection:
    data = _overview_authorized(authorization, root_filter=root_reservation_id)
    events = cast(list[dict[str, object]], data["events"])
    event = next(row for row in events if row["root_reservation_id"] == root_reservation_id)
    metrics = cast(dict[str, Decimal | None], event["metrics"])
    return EventProfitabilityProjection(
        root_reservation_id=root_reservation_id,
        recognized_revenue=cast(Decimal, metrics["recognized_revenue"]),
        direct_cost=cast(Decimal, metrics["direct_cost"]),
        variable_expense=cast(Decimal, metrics["variable_expense"]),
        recurring_expense=cast(Decimal, metrics["recurring_expense"]),
        operating_result=cast(Decimal, metrics["operating_result"]),
        profitability_percentage=metrics["profitability_percentage"],
    )


__all__ = ("EventProfitabilityProjection", "event_profitability")
