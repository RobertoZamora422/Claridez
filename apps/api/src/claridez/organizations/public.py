"""Proyecciones inmutables de identidad contractual organizacional."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .models import Membership, Organization, OrganizationSettings, Space, Venue
from .tenant_scope import TenantAuthorization


@dataclass(frozen=True, slots=True)
class OrganizationContractualProjection:
    id: UUID
    name: str
    currency: str
    timezone_name: str


@dataclass(frozen=True, slots=True)
class LocationContractualProjection:
    venue_id: UUID
    venue_name: str
    venue_location_reference: str | None
    space_id: UUID
    space_name: str


@dataclass(frozen=True, slots=True)
class FinanceVenueProjection:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class ResourcesVenueProjection:
    id: UUID
    name: str
    is_active: bool


def venue_for_resources(
    authorization: TenantAuthorization, venue_id: UUID
) -> ResourcesVenueProjection | None:
    row = Venue.objects.filter(
        organization_id=authorization.organization_id,
        pk=venue_id,
    ).first()
    if row is None:
        return None
    return ResourcesVenueProjection(id=row.pk, name=row.name, is_active=row.is_active)


def venue_for_finance(
    authorization: TenantAuthorization, venue_id: UUID
) -> FinanceVenueProjection | None:
    row = Venue.objects.filter(
        organization_id=authorization.organization_id,
        pk=venue_id,
        is_active=True,
    ).first()
    if row is None:
        return None
    return FinanceVenueProjection(id=row.pk, name=row.name)


def requires_operation_manage_for_finance_evidence(
    authorization: TenantAuthorization,
) -> bool:
    return authorization.role == Membership.Role.OPERATIONS


def contractual_organization(organization_id: UUID) -> OrganizationContractualProjection:
    organization = Organization.objects.get(pk=organization_id, status=Organization.Status.ACTIVE)
    settings = OrganizationSettings.objects.get(organization_id=organization_id)
    return OrganizationContractualProjection(
        id=organization.pk,
        name=organization.name,
        currency=settings.currency,
        timezone_name=settings.timezone,
    )


def contractual_location(
    organization_id: UUID, *, venue_id: UUID, space_id: UUID
) -> LocationContractualProjection:
    venue = Venue.objects.get(organization_id=organization_id, pk=venue_id)
    space = Space.objects.get(organization_id=organization_id, venue_id=venue_id, pk=space_id)
    return LocationContractualProjection(
        venue_id=venue.pk,
        venue_name=venue.name,
        venue_location_reference=venue.location_reference or None,
        space_id=space.pk,
        space_name=space.name,
    )


def active_organization_ids_for_document_worker() -> tuple[UUID, ...]:
    return tuple(
        Organization.objects.filter(status=Organization.Status.ACTIVE)
        .order_by("id")
        .values_list("id", flat=True)
    )


__all__ = (
    "LocationContractualProjection",
    "OrganizationContractualProjection",
    "FinanceVenueProjection",
    "ResourcesVenueProjection",
    "contractual_location",
    "contractual_organization",
    "venue_for_finance",
    "venue_for_resources",
    "requires_operation_manage_for_finance_evidence",
    "active_organization_ids_for_document_worker",
)
