"""Puerto público estrecho e inmutable de Resources P12."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from claridez.organizations.tenant_scope import TenantAuthorization

from . import services as _services
from .errors import ResourcesError


@dataclass(frozen=True, slots=True)
class ReceiptLineProjection:
    id: UUID
    organization_id: UUID
    kind: str
    resource_id: UUID
    quantity: Decimal
    confirmed_at: datetime
    purchase_id: UUID
    supplier_id: UUID
    root_reservation_id: UUID | None
    venue_id: UUID | None


def receipt_line_for_finance(
    authorization: TenantAuthorization, receipt_line_id: UUID
) -> ReceiptLineProjection:
    value = _services.receipt_line_for_finance(authorization, receipt_line_id)
    return ReceiptLineProjection(**value)  # type: ignore[arg-type]


transfer_assignments_authorized = _services.transfer_assignments_authorized

__all__ = (
    "ReceiptLineProjection",
    "ResourcesError",
    "receipt_line_for_finance",
    "transfer_assignments_authorized",
)
