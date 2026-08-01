"""Casos de uso organizacionales con autorización backend-first."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction

from claridez.identity.models import User

from .capabilities import Capability, require_capability
from .exceptions import TenantAccessDenied
from .models import Membership, Organization, OrganizationSettings
from .normalization import canonicalize_currency, canonicalize_timezone
from .services import (
    add_membership,
    change_membership_role,
    revoke_membership_sessions,
    transition_membership,
)
from .tenant_scope import TenantAuthorization, authorized_tenant_scope


@dataclass(frozen=True, slots=True)
class OrganizationData:
    id: UUID
    name: str
    slug: str


@dataclass(frozen=True, slots=True)
class OrganizationSettingsData:
    organization_id: UUID
    currency: str
    timezone: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MembershipUserData:
    id: UUID
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class MembershipData:
    id: UUID
    user: MembershipUserData
    role: str
    status: str
    joined_at: datetime
    suspended_at: datetime | None
    revoked_at: datetime | None


def _active_actor(actor: User) -> User:
    try:
        current = User.objects.get(pk=actor.pk)
    except (User.DoesNotExist, ValueError, TypeError):
        raise TenantAccessDenied("La organización no está disponible.") from None
    if current.status != User.Status.ACTIVE or not bool(current.is_active):
        raise TenantAccessDenied("La organización no está disponible.")
    return current


def _organization_data(organization: Organization) -> OrganizationData:
    return OrganizationData(
        id=organization.pk,
        name=organization.name,
        slug=organization.slug,
    )


def _settings_data(settings: OrganizationSettings) -> OrganizationSettingsData:
    return OrganizationSettingsData(
        organization_id=settings.organization_id,
        currency=settings.currency,
        timezone=settings.timezone,
        created_at=settings.created_at,
        updated_at=settings.updated_at,
    )


def _membership_data(membership: Membership) -> MembershipData:
    user = membership.user
    return MembershipData(
        id=membership.pk,
        user=MembershipUserData(
            id=user.pk,
            email=user.email,
            display_name=user.display_name,
        ),
        role=membership.role,
        status=membership.status,
        joined_at=membership.joined_at,
        suspended_at=membership.suspended_at,
        revoked_at=membership.revoked_at,
    )


def list_actor_organizations(actor: User) -> tuple[OrganizationData, ...]:
    """Materializar solo organizaciones activas accesibles por el actor."""
    current = _active_actor(actor)
    rows = Membership.objects.select_related("organization").filter(
        user=current,
        status=Membership.Status.ACTIVE,
        organization__status=Organization.Status.ACTIVE,
    )
    materialized: list[OrganizationData] = []
    for membership in rows.order_by("organization__name", "organization_id"):
        require_capability(membership.role, Capability.ORGANIZATION_ACCESS)
        materialized.append(_organization_data(membership.organization))
    return tuple(materialized)


def read_organization_context(
    actor: User,
    organization_reference: Organization | UUID | str,
) -> OrganizationData:
    with authorized_tenant_scope(
        actor,
        organization_reference,
        Capability.ORGANIZATION_ACCESS,
    ) as authorization:
        organization = Organization.objects.get(pk=authorization.organization_id)
        return _organization_data(organization)


def read_organization_settings(
    actor: User,
    organization_reference: Organization | UUID | str,
) -> OrganizationSettingsData:
    with authorized_tenant_scope(
        actor,
        organization_reference,
        Capability.ORGANIZATION_SETTINGS_READ,
    ) as authorization:
        settings = OrganizationSettings.objects.get(organization_id=authorization.organization_id)
        return _settings_data(settings)


def update_organization_settings(
    actor: User,
    organization_reference: Organization | UUID | str,
    *,
    currency: str,
    timezone: str,
) -> OrganizationSettingsData:
    with authorized_tenant_scope(
        actor,
        organization_reference,
        Capability.ORGANIZATION_SETTINGS_UPDATE,
    ) as authorization:
        canonical_currency = canonicalize_currency(currency)
        canonical_timezone = canonicalize_timezone(timezone)
        settings = OrganizationSettings.objects.select_for_update().get(
            organization_id=authorization.organization_id
        )
        settings.currency = canonical_currency
        settings.timezone = canonical_timezone
        settings.full_clean(validate_unique=False, validate_constraints=False)
        settings.save(update_fields=["currency", "timezone", "updated_at"])
        return _settings_data(settings)


def read_memberships(
    actor: User,
    organization_reference: Organization | UUID | str,
) -> tuple[MembershipData, ...]:
    with authorized_tenant_scope(
        actor,
        organization_reference,
        Capability.MEMBERSHIP_READ,
    ) as authorization:
        rows = Membership.objects.select_related("user").filter(
            organization_id=authorization.organization_id
        )
        return tuple(_membership_data(row) for row in rows.order_by("created_at", "id"))


def _target_membership(authorization: TenantAuthorization, membership_id: UUID) -> Membership:
    try:
        return Membership.objects.select_related("user").get(
            pk=membership_id,
            organization_id=authorization.organization_id,
        )
    except Membership.DoesNotExist:
        raise TenantAccessDenied("La membresía no está disponible.") from None


def _require_owner_management(
    authorization: TenantAuthorization,
    membership: Membership,
) -> None:
    if membership.role == Membership.Role.OWNER:
        authorization.require(Capability.MEMBERSHIP_MANAGE_OWNER)


def authorized_add_membership(
    actor: User,
    organization_reference: Organization | UUID | str,
    *,
    user_id: UUID,
    role: Membership.Role | str,
) -> MembershipData:
    try:
        canonical_role = Membership.Role(role)
    except ValueError:
        raise TenantAccessDenied("La operación no está autorizada.") from None
    required = (
        Capability.MEMBERSHIP_MANAGE_OWNER
        if canonical_role == Membership.Role.OWNER
        else Capability.MEMBERSHIP_MANAGE_NON_OWNER
    )
    with authorized_tenant_scope(actor, organization_reference, required) as authorization:
        membership = add_membership(
            organization_id=authorization.organization_id,
            user_id=user_id,
            role=canonical_role,
        )
        return _membership_data(Membership.objects.select_related("user").get(pk=membership.pk))


def authorized_change_membership_role(
    actor: User,
    organization_reference: Organization | UUID | str,
    *,
    membership_id: UUID,
    target_role: Membership.Role | str,
) -> MembershipData:
    try:
        canonical_role = Membership.Role(target_role)
    except ValueError:
        raise TenantAccessDenied("La operación no está autorizada.") from None
    required = (
        Capability.MEMBERSHIP_MANAGE_OWNER
        if canonical_role == Membership.Role.OWNER
        else Capability.MEMBERSHIP_MANAGE_NON_OWNER
    )
    with authorized_tenant_scope(actor, organization_reference, required) as authorization:
        target = _target_membership(authorization, membership_id)
        _require_owner_management(authorization, target)
        changed = change_membership_role(
            organization_id=authorization.organization_id,
            membership_id=target.pk,
            target_role=canonical_role,
        )
        return _membership_data(Membership.objects.select_related("user").get(pk=changed.pk))


def authorized_transition_membership(
    actor: User,
    organization_reference: Organization | UUID | str,
    *,
    membership_id: UUID,
    target_status: Membership.Status | str,
) -> MembershipData:
    with authorized_tenant_scope(
        actor,
        organization_reference,
        Capability.MEMBERSHIP_MANAGE_NON_OWNER,
    ) as authorization:
        target = _target_membership(authorization, membership_id)
        _require_owner_management(authorization, target)
        transitioned = transition_membership(
            organization_id=authorization.organization_id,
            membership_id=target.pk,
            target_status=target_status,
        )
        return _membership_data(Membership.objects.select_related("user").get(pk=transitioned.pk))


def authorized_revoke_membership_sessions(
    actor: User,
    organization_reference: Organization | UUID | str,
    *,
    membership_id: UUID,
) -> MembershipData:
    with authorized_tenant_scope(
        actor,
        organization_reference,
        Capability.MEMBERSHIP_REVOKE_SESSIONS,
    ) as authorization:
        target = _target_membership(authorization, membership_id)
        _require_owner_management(authorization, target)
        with transaction.atomic():
            revoked = revoke_membership_sessions(
                organization_id=authorization.organization_id,
                membership_id=target.pk,
            )
        return _membership_data(Membership.objects.select_related("user").get(pk=revoked.pk))


def authorized_suspend_membership(
    actor: User,
    organization_reference: Organization | UUID | str,
    *,
    membership_id: UUID,
) -> MembershipData:
    return authorized_transition_membership(
        actor,
        organization_reference,
        membership_id=membership_id,
        target_status=Membership.Status.SUSPENDED,
    )


def authorized_revoke_membership(
    actor: User,
    organization_reference: Organization | UUID | str,
    *,
    membership_id: UUID,
) -> MembershipData:
    return authorized_transition_membership(
        actor,
        organization_reference,
        membership_id=membership_id,
        target_status=Membership.Status.REVOKED,
    )


def authorized_reactivate_membership(
    actor: User,
    organization_reference: Organization | UUID | str,
    *,
    membership_id: UUID,
) -> MembershipData:
    return authorized_transition_membership(
        actor,
        organization_reference,
        membership_id=membership_id,
        target_status=Membership.Status.ACTIVE,
    )
