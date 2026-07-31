"""Pruebas del ciclo de vida y la protección de membresías."""

from __future__ import annotations

import pytest

from claridez.identity.models import User
from claridez.organizations.exceptions import (
    InvalidMembershipRoleChange,
    InvalidMembershipTransition,
    LastActiveOwnerRequired,
    MembershipAlreadyExists,
    UserNotActive,
)
from claridez.organizations.models import Membership, Organization
from claridez.organizations.services import (
    add_membership,
    change_membership_role,
    create_organization,
    transition_membership,
)

PASSWORD = "correct-horse-battery-staple-42"


def _active_user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )


def _organization(email: str = "owner@example.com") -> tuple[Organization, Membership]:
    owner = _active_user(email)
    creation = create_organization(owner_user_id=owner.pk, name=f"Organización {email}")
    return creation.organization, creation.owner_membership


def test_role_catalog_has_the_approved_spanish_mapping() -> None:
    assert dict(Membership.Role.choices) == {
        "owner": "Propietario",
        "administrator": "Administrador",
        "commercial": "Comercial",
        "operations": "Operaciones",
        "finance": "Finanzas",
    }


@pytest.mark.django_db
def test_add_membership_is_active_unique_and_requires_active_user() -> None:
    organization, _ = _organization()
    member_user = _active_user("member@example.com")
    membership = add_membership(
        organization_id=organization.pk,
        user_id=member_user.pk,
        role=Membership.Role.COMMERCIAL,
    )

    assert membership.status == Membership.Status.ACTIVE
    assert membership.role == Membership.Role.COMMERCIAL
    assert membership.suspended_at is None
    assert membership.revoked_at is None

    with pytest.raises(MembershipAlreadyExists):
        add_membership(
            organization_id=organization.pk,
            user_id=member_user.pk,
            role=Membership.Role.FINANCE,
        )

    pending = User.objects.create_user(email="pending-member@example.com", password=PASSWORD)
    with pytest.raises(UserNotActive):
        add_membership(
            organization_id=organization.pk,
            user_id=pending.pk,
            role=Membership.Role.OPERATIONS,
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "operation",
    ["change_role", "suspend", "revoke"],
)
def test_last_active_owner_cannot_be_removed(operation: str) -> None:
    organization, owner = _organization(f"last-{operation}@example.com")

    with pytest.raises(LastActiveOwnerRequired):
        if operation == "change_role":
            change_membership_role(
                organization_id=organization.pk,
                membership_id=owner.pk,
                target_role=Membership.Role.ADMINISTRATOR,
            )
        else:
            transition_membership(
                organization_id=organization.pk,
                membership_id=owner.pk,
                target_status=(
                    Membership.Status.SUSPENDED
                    if operation == "suspend"
                    else Membership.Status.REVOKED
                ),
            )

    owner.refresh_from_db()
    assert owner.role == Membership.Role.OWNER
    assert owner.status == Membership.Status.ACTIVE


@pytest.mark.django_db
def test_multiple_owners_allow_demotion_and_suspension() -> None:
    organization, first_owner = _organization("first-owner@example.com")
    second_user = _active_user("second-owner@example.com")
    second_owner = add_membership(
        organization_id=organization.pk,
        user_id=second_user.pk,
        role=Membership.Role.OWNER,
    )

    demoted = change_membership_role(
        organization_id=organization.pk,
        membership_id=first_owner.pk,
        target_role=Membership.Role.ADMINISTRATOR,
    )
    assert demoted.role == Membership.Role.ADMINISTRATOR

    with pytest.raises(LastActiveOwnerRequired):
        transition_membership(
            organization_id=organization.pk,
            membership_id=second_owner.pk,
            target_status=Membership.Status.SUSPENDED,
        )


@pytest.mark.django_db
def test_persistent_membership_supports_suspend_revoke_and_reactivate() -> None:
    organization, _ = _organization("cycle-owner@example.com")
    user = _active_user("cycle-member@example.com")
    membership = add_membership(
        organization_id=organization.pk,
        user_id=user.pk,
        role=Membership.Role.OPERATIONS,
    )
    original_id = membership.pk
    original_joined_at = membership.joined_at

    suspended = transition_membership(
        organization_id=organization.pk,
        membership_id=membership.pk,
        target_status=Membership.Status.SUSPENDED,
    )
    assert suspended.suspended_at is not None
    assert suspended.revoked_at is None

    active = transition_membership(
        organization_id=organization.pk,
        membership_id=membership.pk,
        target_status=Membership.Status.ACTIVE,
    )
    assert active.suspended_at is None
    assert active.revoked_at is None

    revoked = transition_membership(
        organization_id=organization.pk,
        membership_id=membership.pk,
        target_status=Membership.Status.REVOKED,
    )
    assert revoked.revoked_at is not None

    reactivated = transition_membership(
        organization_id=organization.pk,
        membership_id=membership.pk,
        target_status=Membership.Status.ACTIVE,
    )
    assert reactivated.pk == original_id
    assert reactivated.joined_at == original_joined_at
    assert reactivated.suspended_at is None
    assert reactivated.revoked_at is None
    assert Membership.objects.filter(organization=organization, user=user).count() == 1


@pytest.mark.django_db
def test_reactivation_requires_active_user_and_role_change_rejects_revoked() -> None:
    organization, _ = _organization("reactivation-owner@example.com")
    user = _active_user("reactivation-member@example.com")
    membership = add_membership(
        organization_id=organization.pk,
        user_id=user.pk,
        role=Membership.Role.FINANCE,
    )
    transition_membership(
        organization_id=organization.pk,
        membership_id=membership.pk,
        target_status=Membership.Status.REVOKED,
    )

    with pytest.raises(InvalidMembershipRoleChange):
        change_membership_role(
            organization_id=organization.pk,
            membership_id=membership.pk,
            target_role=Membership.Role.COMMERCIAL,
        )

    user.set_status(User.Status.SUSPENDED)
    user.save(update_fields=["status", "is_active", "updated_at"])
    with pytest.raises(UserNotActive):
        transition_membership(
            organization_id=organization.pk,
            membership_id=membership.pk,
            target_status=Membership.Status.ACTIVE,
        )


@pytest.mark.django_db
def test_membership_transitions_are_explicit_and_do_not_revoke_global_sessions() -> None:
    organization, _ = _organization("session-owner@example.com")
    user = _active_user("session-member@example.com")
    membership = add_membership(
        organization_id=organization.pk,
        user_id=user.pk,
        role=Membership.Role.COMMERCIAL,
    )
    security_version = user.security_version

    transition_membership(
        organization_id=organization.pk,
        membership_id=membership.pk,
        target_status=Membership.Status.REVOKED,
    )
    user.refresh_from_db()
    assert user.security_version == security_version

    with pytest.raises(InvalidMembershipTransition):
        transition_membership(
            organization_id=organization.pk,
            membership_id=membership.pk,
            target_status=Membership.Status.REVOKED,
        )
