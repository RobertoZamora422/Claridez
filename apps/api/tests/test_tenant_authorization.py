"""Scope tenant y wrappers de autorización organizacional."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from claridez.identity.models import User
from claridez.organizations.application_services import (
    authorized_add_membership,
    authorized_change_membership_role,
    authorized_reactivate_membership,
    authorized_revoke_membership,
    authorized_revoke_membership_sessions,
    authorized_suspend_membership,
    read_memberships,
    read_organization_settings,
    update_organization_settings,
)
from claridez.organizations.capabilities import Capability
from claridez.organizations.exceptions import (
    AuthorizationDenied,
    ConflictingTenantScope,
    LastActiveOwnerRequired,
    TenantAccessDenied,
)
from claridez.organizations.models import Membership, Organization
from claridez.organizations.services import add_membership, create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope

PASSWORD = "correct-horse-battery-staple-tenant-42"


def _active_user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )


def _organization(prefix: str) -> tuple[User, Organization, Membership]:
    owner = _active_user(f"{prefix}-owner@example.com")
    creation = create_organization(owner_user_id=owner.pk, name=f"Organization {prefix}")
    return owner, creation.organization, creation.owner_membership


@pytest.mark.django_db
def test_settings_defaults_validation_and_authorized_update() -> None:
    owner, organization, _ = _organization("settings")

    defaults = read_organization_settings(owner, organization.pk)
    updated = update_organization_settings(
        owner,
        organization.pk,
        currency=" eur ",
        timezone=" Europe/Madrid ",
    )

    assert defaults.currency == "USD"
    assert defaults.timezone == "America/Guayaquil"
    assert updated.currency == "EUR"
    assert updated.timezone == "Europe/Madrid"
    with pytest.raises((ValueError, ValidationError)):
        update_organization_settings(
            owner,
            organization.pk,
            currency="US",
            timezone="America/Guayaquil",
        )
    with pytest.raises((ValueError, ValidationError)):
        update_organization_settings(
            owner,
            organization.pk,
            currency="USD",
            timezone="Not/A-Timezone",
        )


@pytest.mark.django_db
def test_scope_revalidates_actor_organization_and_membership_states() -> None:
    actor, organization, membership = _organization("states")

    actor.set_status(User.Status.SUSPENDED)
    actor.save(update_fields=["status", "is_active", "updated_at"])
    with pytest.raises(TenantAccessDenied):
        read_organization_settings(actor, organization.pk)

    actor.set_status(User.Status.ACTIVE)
    actor.save(update_fields=["status", "is_active", "updated_at"])
    organization.status = Organization.Status.SUSPENDED
    organization.save(update_fields=["status", "updated_at"])
    with pytest.raises(TenantAccessDenied):
        read_organization_settings(actor, organization.pk)

    organization.status = Organization.Status.ACTIVE
    organization.save(update_fields=["status", "updated_at"])
    Membership.objects.filter(pk=membership.pk).update(
        status=Membership.Status.SUSPENDED,
        suspended_at=membership.joined_at,
    )
    with pytest.raises(TenantAccessDenied):
        read_organization_settings(actor, organization.pk)


@pytest.mark.django_db
def test_equal_nested_scope_is_allowed_and_cross_tenant_nesting_is_rejected() -> None:
    actor, first, _ = _organization("nested-first")
    _, second, _ = _organization("nested-second")

    with authorized_tenant_scope(actor, first.pk, Capability.ORGANIZATION_ACCESS):
        with authorized_tenant_scope(actor, first.pk, Capability.ORGANIZATION_SETTINGS_READ):
            assert read_organization_settings(actor, first.pk).organization_id == first.pk
        with (
            pytest.raises(ConflictingTenantScope),
            authorized_tenant_scope(actor, second.pk, Capability.ORGANIZATION_ACCESS),
        ):
            pass

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('claridez.organization_id', true)")
        assert cursor.fetchone()[0] in (None, "")


@pytest.mark.django_db
def test_owner_and_administrator_boundaries_are_explicit() -> None:
    owner, organization, owner_membership = _organization("roles")
    administrator = _active_user("roles-administrator@example.com")
    administrator_membership = add_membership(
        organization_id=organization.pk,
        user_id=administrator.pk,
        role=Membership.Role.ADMINISTRATOR,
    )
    commercial = _active_user("roles-commercial@example.com")
    commercial_membership = authorized_add_membership(
        owner,
        organization.pk,
        user_id=commercial.pk,
        role=Membership.Role.COMMERCIAL,
    )

    assert len(read_memberships(administrator, organization.pk)) == 3
    authorized_change_membership_role(
        administrator,
        organization.pk,
        membership_id=commercial_membership.id,
        target_role=Membership.Role.OPERATIONS,
    )
    with pytest.raises(AuthorizationDenied):
        authorized_change_membership_role(
            administrator,
            organization.pk,
            membership_id=commercial_membership.id,
            target_role=Membership.Role.OWNER,
        )
    with pytest.raises(AuthorizationDenied):
        authorized_suspend_membership(
            administrator,
            organization.pk,
            membership_id=owner_membership.pk,
        )
    with pytest.raises(AuthorizationDenied):
        authorized_revoke_membership_sessions(
            administrator,
            organization.pk,
            membership_id=owner_membership.pk,
        )

    original_version = commercial.security_version
    authorized_revoke_membership_sessions(
        administrator,
        organization.pk,
        membership_id=commercial_membership.id,
    )
    commercial.refresh_from_db()
    assert commercial.security_version == original_version + 1

    suspended = authorized_suspend_membership(
        administrator,
        organization.pk,
        membership_id=commercial_membership.id,
    )
    assert suspended.status == Membership.Status.SUSPENDED
    reactivated = authorized_reactivate_membership(
        administrator,
        organization.pk,
        membership_id=commercial_membership.id,
    )
    assert reactivated.status == Membership.Status.ACTIVE
    revoked = authorized_revoke_membership(
        administrator,
        organization.pk,
        membership_id=commercial_membership.id,
    )
    assert revoked.status == Membership.Status.REVOKED
    assert administrator_membership.role == Membership.Role.ADMINISTRATOR


@pytest.mark.django_db
def test_authorized_owner_changes_keep_last_owner_protection() -> None:
    owner, organization, owner_membership = _organization("last-owner-authorized")

    with pytest.raises(LastActiveOwnerRequired):
        authorized_revoke_membership(
            owner,
            organization.pk,
            membership_id=owner_membership.pk,
        )


def test_private_guc_helper_has_no_forbidden_imports() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "claridez"
    package = source_root / "organizations"
    allowed_low_level_importer = package / "tenant_scope.py"
    for module in source_root.rglob("*.py"):
        if module in {package / "_tenant_context.py", allowed_low_level_importer}:
            continue
        assert "_tenant_context" not in module.read_text(encoding="utf-8"), module.name

    for module_name in ("views.py", "serializers.py", "urls.py"):
        tree = ast.parse((package / module_name).read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not any(
            name.endswith(".services") or name == "services" for name in imported_modules
        )
