"""Puerto público estrecho e inmutable de cuentas por cobrar."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .errors import ReceivablesError, unavailable
from .models import ReceivableObligation
from .services import adjusted_obligation_amount, obligation_balance


@dataclass(frozen=True, slots=True)
class ReceivableSummaryProjection:
    root_reservation_id: UUID
    event_request_id: UUID
    currency: str
    original_total: Decimal
    applied_total: Decimal
    balance: Decimal
    derived_status: str


def summary_for_commercial(
    authorization: TenantAuthorization, root_reservation_id: UUID
) -> ReceivableSummaryProjection:
    authorization.require(Capability.RECEIVABLES_READ_SUMMARY)
    row = ReceivableObligation.objects.filter(
        organization_id=authorization.organization_id,
        root_reservation_id=root_reservation_id,
    ).first()
    if row is None:
        raise unavailable("La obligación")
    balance = obligation_balance(row)
    applied = adjusted_obligation_amount(row) - balance
    return ReceivableSummaryProjection(
        root_reservation_id=row.root_reservation_id,
        event_request_id=row.event_request_id,
        currency=row.currency,
        original_total=row.original_total,
        applied_total=applied,
        balance=balance,
        derived_status=(
            "satisfied" if balance == Decimal("0.00") else "partial" if applied > 0 else "open"
        ),
    )


__all__ = ("ReceivableSummaryProjection", "ReceivablesError", "summary_for_commercial")
