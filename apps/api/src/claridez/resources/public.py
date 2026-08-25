"""Puerto público estrecho e inmutable de Resources P12."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from claridez.identity.models import User
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


@dataclass(frozen=True, slots=True)
class OperationalAssignmentProjection:
    id: UUID
    requirement_id: UUID | None
    resource_id: UUID
    resource_name: str
    status: str
    quantity: Decimal
    starts_at: datetime
    ends_at: datetime | None


@dataclass(frozen=True, slots=True)
class OperationalRequirementProjection:
    id: UUID
    reservation_id: UUID
    root_reservation_id: UUID
    resource_id: UUID
    resource_name: str
    resource_nature: str
    status: str
    quantity: Decimal
    starts_at: datetime
    ends_at: datetime
    temporal_source: str
    operational_window_id: UUID | None
    supplier_names: tuple[str, ...]
    assignments: tuple[OperationalAssignmentProjection, ...]


@dataclass(frozen=True, slots=True)
class OperationalResourceProjection:
    id: UUID
    name: str
    nature: str
    is_active: bool


def resource_for_operations(
    authorization: TenantAuthorization, resource_id: UUID
) -> OperationalResourceProjection | None:
    from .models import Resource

    row = Resource.objects.filter(
        organization_id=authorization.organization_id, pk=resource_id
    ).first()
    if row is None:
        return None
    return OperationalResourceProjection(
        id=row.pk, name=row.name, nature=row.nature, is_active=row.is_active
    )


def resources_for_operations(
    authorization: TenantAuthorization,
) -> tuple[OperationalResourceProjection, ...]:
    from .models import Resource

    return tuple(
        OperationalResourceProjection(
            id=row.pk, name=row.name, nature=row.nature, is_active=row.is_active
        )
        for row in Resource.objects.filter(
            organization_id=authorization.organization_id, is_active=True
        ).order_by("name", "id")
    )


def operational_resource_state(
    authorization: TenantAuthorization, reservation_id: UUID
) -> tuple[OperationalRequirementProjection, ...]:
    from .models import ResourceRequirement, SupplierOffering

    rows = (
        ResourceRequirement.objects.select_related("resource")
        .prefetch_related("assignments")
        .filter(
            organization_id=authorization.organization_id,
            reservation_id=reservation_id,
        )
    )
    result: list[OperationalRequirementProjection] = []
    for row in rows.order_by("created_at", "id"):
        supplier_names = tuple(
            SupplierOffering.objects.filter(
                organization_id=authorization.organization_id,
                resource_id=row.resource_id,
                is_active=True,
            )
            .select_related("supplier")
            .order_by("supplier__legal_name", "supplier_id")
            .values_list("supplier__legal_name", flat=True)
        )
        assignments = tuple(
            OperationalAssignmentProjection(
                id=item.pk,
                requirement_id=item.requirement_id,
                resource_id=item.resource_id,
                resource_name=row.resource.name,
                status=item.status,
                quantity=item.quantity,
                starts_at=item.resource_interval.lower,
                ends_at=item.resource_interval.upper,
            )
            for item in row.assignments.order_by("created_at", "id")
        )
        result.append(
            OperationalRequirementProjection(
                id=row.pk,
                reservation_id=row.reservation_id,
                root_reservation_id=row.root_reservation_id,
                resource_id=row.resource_id,
                resource_name=row.resource.name,
                resource_nature=row.resource.nature,
                status=row.status,
                quantity=row.quantity,
                starts_at=row.resource_interval.lower,
                ends_at=row.resource_interval.upper,
                temporal_source=row.temporal_source,
                operational_window_id=row.operational_window_id,
                supplier_names=supplier_names,
                assignments=assignments,
            )
        )
    return tuple(result)


def create_requirement_for_window(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID,
    resource_id: UUID,
    quantity: Decimal,
    reason: str,
    idempotency_key: UUID,
    operational_window_id: UUID,
) -> UUID:
    row = _services.create_requirement(
        actor,
        organization_reference,
        reservation_id=reservation_id,
        resource_id=resource_id,
        quantity=quantity,
        reason=reason,
        idempotency_key=idempotency_key,
        operational_window_id=operational_window_id,
    )
    return row.pk


def receipt_line_for_finance(
    authorization: TenantAuthorization, receipt_line_id: UUID
) -> ReceiptLineProjection:
    value = _services.receipt_line_for_finance(authorization, receipt_line_id)
    return ReceiptLineProjection(**value)  # type: ignore[arg-type]


transfer_assignments_authorized = _services.transfer_assignments_authorized

__all__ = (
    "ReceiptLineProjection",
    "OperationalAssignmentProjection",
    "OperationalRequirementProjection",
    "OperationalResourceProjection",
    "ResourcesError",
    "receipt_line_for_finance",
    "resource_for_operations",
    "resources_for_operations",
    "operational_resource_state",
    "create_requirement_for_window",
    "transfer_assignments_authorized",
)
