"""Proyecciones inmutables de identidad contractual organizacional."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .analytics_contracts import (
    CohortMember,
    Coverage,
    DimensionValues,
    MetricPoint,
    MetricValueStatus,
    SourceCollection,
    SourceInputContract,
    SourceMetricQuery,
    SourceMetricResult,
    TemporalMode,
    dimension_values,
    evidence_watermark,
    worst_coverage,
)
from .analytics_values import MetricAccumulator
from .capabilities import Capability, capabilities_for_role
from .exceptions import AuthorizationDenied, TenantAccessDenied
from .models import Membership, Organization, OrganizationSettings, Space, Venue
from .tenant_scope import TenantAuthorization


@dataclass(frozen=True, slots=True)
class OrganizationContractualProjection:
    id: UUID
    name: str
    currency: str
    timezone_name: str


@dataclass(frozen=True, slots=True)
class AnalyticsOrganizationSettings:
    currency: str
    timezone_name: str


def settings_for_analytics(authorization: TenantAuthorization) -> AnalyticsOrganizationSettings:
    authorization.require(Capability.ORGANIZATION_SETTINGS_READ)
    row = OrganizationSettings.objects.only("currency", "timezone").get(
        organization_id=authorization.organization_id
    )
    return AnalyticsOrganizationSettings(row.currency, row.timezone)


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


@dataclass(frozen=True, slots=True)
class OperationalMembershipProjection:
    id: UUID
    display_name: str
    role: str
    is_active: bool
    can_manage_operations: bool


@dataclass(frozen=True, slots=True)
class PublicOrganizationProjection:
    id: UUID
    name: str
    timezone_name: str


@dataclass(frozen=True, slots=True)
class PublicLocationProjection:
    venue_id: UUID
    venue_name: str
    venue_revision: int
    space_id: UUID
    space_name: str
    space_revision: int
    is_active: bool


@dataclass(frozen=True, slots=True)
class PublicResponsibleProjection:
    membership_id: UUID
    display_name: str
    role: str
    is_active: bool
    can_manage_sales: bool


def membership_for_operations(
    organization_id: UUID, membership_id: UUID
) -> OperationalMembershipProjection | None:
    row = (
        Membership.objects.select_related("user")
        .filter(organization_id=organization_id, pk=membership_id)
        .first()
    )
    if row is None:
        return None
    return OperationalMembershipProjection(
        id=row.pk,
        display_name=row.user.display_name or "Miembro del equipo",
        role=row.role,
        is_active=row.status == Membership.Status.ACTIVE,
        can_manage_operations=Capability.OPERATION_MANAGE in capabilities_for_role(row.role),
    )


def memberships_for_operations(
    organization_id: UUID,
) -> tuple[OperationalMembershipProjection, ...]:
    return tuple(
        value
        for row in Membership.objects.select_related("user")
        .filter(organization_id=organization_id)
        .order_by("user__display_name", "id")
        if (
            value := OperationalMembershipProjection(
                id=row.pk,
                display_name=row.user.display_name or "Miembro del equipo",
                role=row.role,
                is_active=row.status == Membership.Status.ACTIVE,
                can_manage_operations=Capability.OPERATION_MANAGE
                in capabilities_for_role(row.role),
            )
        ).is_active
        and value.can_manage_operations
    )


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


def organization_is_active_for_external_entry(organization_id: UUID) -> bool:
    """Proyección global mínima; confirma estado pero nunca acuña autorización."""
    return Organization.objects.filter(
        pk=organization_id, status=Organization.Status.ACTIVE
    ).exists()


def public_organization(organization_id: UUID) -> PublicOrganizationProjection:
    organization = Organization.objects.filter(
        pk=organization_id, status=Organization.Status.ACTIVE
    ).first()
    settings = OrganizationSettings.objects.filter(organization_id=organization_id).first()
    if organization is None or settings is None:
        raise TenantAccessDenied("La organización no está disponible.")
    return PublicOrganizationProjection(
        id=organization.pk,
        name=organization.name,
        timezone_name=settings.timezone,
    )


def public_location(organization_id: UUID, *, space_id: UUID) -> PublicLocationProjection | None:
    row = (
        Space.objects.select_related("venue")
        .filter(
            organization_id=organization_id,
            pk=space_id,
        )
        .first()
    )
    if row is None:
        return None
    return PublicLocationProjection(
        venue_id=row.venue_id,
        venue_name=row.venue.name,
        venue_revision=row.venue.revision,
        space_id=row.pk,
        space_name=row.name,
        space_revision=row.revision,
        is_active=row.is_active and row.venue.is_active,
    )


def public_responsible(
    organization_id: UUID, *, membership_id: UUID
) -> PublicResponsibleProjection | None:
    row = (
        Membership.objects.select_related("user")
        .filter(
            organization_id=organization_id,
            pk=membership_id,
        )
        .first()
    )
    if row is None:
        return None
    try:
        can_manage_sales = Capability.SALES_MANAGE in capabilities_for_role(row.role)
    except AuthorizationDenied:
        can_manage_sales = False
    return PublicResponsibleProjection(
        membership_id=row.pk,
        display_name=row.user.display_name or "Miembro del equipo",
        role=row.role,
        is_active=row.status == Membership.Status.ACTIVE and row.user.is_active,
        can_manage_sales=can_manage_sales,
    )


def active_organization_ids_for_communications_worker() -> tuple[UUID, ...]:
    return tuple(
        Organization.objects.filter(status=Organization.Status.ACTIVE)
        .order_by("id")
        .values_list("id", flat=True)
    )


def active_organization_ids_for_analytics_worker() -> tuple[UUID, ...]:
    """Control global mínimo: el worker reclama después únicamente dentro de cada tenant."""
    return tuple(
        Organization.objects.filter(status=Organization.Status.ACTIVE)
        .order_by("id")
        .values_list("id", flat=True)
    )


def analytics_requester_actor_id(organization_id: UUID, membership_id: UUID) -> UUID | None:
    """Revalidación source-owned de la membresía solicitante, sin exportar su ORM ni PII."""
    return (
        Membership.objects.filter(
            organization_id=organization_id,
            pk=membership_id,
            status=Membership.Status.ACTIVE,
            organization__status=Organization.Status.ACTIVE,
            user__is_active=True,
        )
        .values_list("user_id", flat=True)
        .first()
    )


__all__ = (
    "CohortMember",
    "Coverage",
    "DimensionValues",
    "MetricPoint",
    "MetricValueStatus",
    "MetricAccumulator",
    "SourceCollection",
    "SourceInputContract",
    "SourceMetricQuery",
    "SourceMetricResult",
    "TemporalMode",
    "dimension_values",
    "evidence_watermark",
    "worst_coverage",
    "AnalyticsOrganizationSettings",
    "settings_for_analytics",
    "active_organization_ids_for_analytics_worker",
    "analytics_requester_actor_id",
    "LocationContractualProjection",
    "OrganizationContractualProjection",
    "FinanceVenueProjection",
    "ResourcesVenueProjection",
    "OperationalMembershipProjection",
    "PublicLocationProjection",
    "PublicOrganizationProjection",
    "PublicResponsibleProjection",
    "contractual_location",
    "contractual_organization",
    "venue_for_finance",
    "venue_for_resources",
    "membership_for_operations",
    "memberships_for_operations",
    "requires_operation_manage_for_finance_evidence",
    "active_organization_ids_for_document_worker",
    "active_organization_ids_for_communications_worker",
    "organization_is_active_for_external_entry",
    "public_location",
    "public_organization",
    "public_responsible",
)
