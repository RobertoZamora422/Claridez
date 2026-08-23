"""Puerto público inmutable de resultados financieros operativos P11."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

from claridez.organizations.tenant_scope import TenantAuthorization

from .errors import FinanceError
from .services import _materialize_resources_receipt_authorized, _overview_authorized


@dataclass(frozen=True, slots=True)
class EventProfitabilityProjection:
    root_reservation_id: UUID
    recognized_revenue: Decimal
    direct_cost: Decimal
    variable_expense: Decimal
    recurring_expense: Decimal
    operating_result: Decimal
    profitability_percentage: Decimal | None


@dataclass(frozen=True, slots=True)
class ResourcesReceiptFinancialCommand:
    source_id: UUID
    source_kind: str
    target_kind: str
    category_id: UUID
    amount: Decimal
    currency: str
    economic_date: date
    description: str
    evidence_reference: str
    root_reservation_id: UUID | None = None
    venue_id: UUID | None = None
    expense_type: str | None = None
    allocations: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class FinancialMaterializationProjection:
    target_kind: str
    target_id: UUID


def materialize_resources_receipt(
    authorization: TenantAuthorization,
    command: ResourcesReceiptFinancialCommand,
    *,
    idempotency_key: UUID,
) -> FinancialMaterializationProjection:
    target_kind, target_id = _materialize_resources_receipt_authorized(
        authorization,
        source_id=command.source_id,
        source_kind=command.source_kind,
        target_kind=command.target_kind,
        category_id=command.category_id,
        amount_value=command.amount,
        currency_value=command.currency,
        economic_date=command.economic_date,
        description=command.description,
        evidence_reference=command.evidence_reference,
        root_reservation_id=command.root_reservation_id,
        venue_id=command.venue_id,
        expense_type=command.expense_type,
        allocations=list(command.allocations),
        idempotency_key=idempotency_key,
    )
    return FinancialMaterializationProjection(target_kind=target_kind, target_id=target_id)


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


__all__ = (
    "EventProfitabilityProjection",
    "FinancialMaterializationProjection",
    "FinanceError",
    "ResourcesReceiptFinancialCommand",
    "event_profitability",
    "materialize_resources_receipt",
)
