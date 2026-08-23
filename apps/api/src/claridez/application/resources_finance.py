"""Coordinación neutral y atómica entre Resources P12 y Finance P11."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db import transaction

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope


def materialize_resources_receipt(
    actor: User,
    organization_reference: UUID | str,
    *,
    receipt_line_id: UUID,
    target_kind: str,
    category_id: UUID,
    amount: Decimal,
    currency: str,
    economic_date: date,
    description: str,
    evidence_reference: str,
    root_reservation_id: UUID | None,
    venue_id: UUID | None,
    expense_type: str | None,
    allocations: tuple[dict[str, object], ...],
    idempotency_key: UUID,
) -> dict[str, object]:
    import claridez.finance.public as finance_port
    import claridez.resources.public as resources_port

    with (
        transaction.atomic(),
        authorized_tenant_scope(
            actor,
            organization_reference,
            Capability.PURCHASE_MATERIALIZE_FINANCE,
        ) as authorization,
    ):
        source = resources_port.receipt_line_for_finance(authorization, receipt_line_id)
        if target_kind == "actual_direct_cost" and (
            source.root_reservation_id is None
            or source.venue_id is None
            or root_reservation_id != source.root_reservation_id
            or venue_id != source.venue_id
        ):
            raise resources_port.ResourcesError(
                "receipt_event_scope_mismatch",
                "El costo directo debe usar la raíz y sede históricas de la compra recibida.",
                status=409,
            )
        try:
            result = finance_port.materialize_resources_receipt(
                authorization,
                finance_port.ResourcesReceiptFinancialCommand(
                    source_id=source.id,
                    source_kind="resources_receipt_line",
                    target_kind=target_kind,
                    category_id=category_id,
                    amount=amount,
                    currency=currency,
                    economic_date=economic_date,
                    description=description,
                    evidence_reference=evidence_reference,
                    root_reservation_id=root_reservation_id,
                    venue_id=venue_id,
                    expense_type=expense_type,
                    allocations=allocations,
                ),
                idempotency_key=idempotency_key,
            )
        except finance_port.FinanceError as error:
            raise resources_port.ResourcesError(
                error.code, error.message, status=error.status
            ) from error
        return {
            "source_kind": "resources_receipt_line",
            "source_id": source.id,
            "target_kind": result.target_kind,
            "target_id": result.target_id,
        }


__all__ = ("materialize_resources_receipt",)
