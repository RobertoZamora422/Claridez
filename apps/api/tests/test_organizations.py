"""Pruebas del modelo y servicios de organizaciones."""

from __future__ import annotations

import uuid

import pytest

from claridez.identity.models import User
from claridez.organizations.exceptions import (
    InvalidOrganizationTransition,
    LastActiveOwnerRequired,
    OrganizationSlugConflict,
    UserNotActive,
)
from claridez.organizations.models import Membership, Organization
from claridez.organizations.normalization import (
    canonicalize_organization_name,
    canonicalize_organization_slug,
)
from claridez.organizations.services import (
    create_organization,
    rename_organization,
    transition_organization,
)

PASSWORD = "correct-horse-battery-staple-42"


def _active_user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("  Mi Salón & Eventos__Quito  ", "mi-salon-eventos__quito"),
        ("Árbol---Azul", "arbol-azul"),
        ("ACME Ecuador", "acme-ecuador"),
    ],
)
def test_slug_normalization_uses_django_ascii_rules(source: str, expected: str) -> None:
    assert canonicalize_organization_slug(source) == expected


def test_organization_normalizers_reject_empty_and_do_not_truncate() -> None:
    assert canonicalize_organization_name("  Salón Central  ") == "Salón Central"
    with pytest.raises(ValueError, match="obligatorio"):
        canonicalize_organization_name("   ")
    with pytest.raises(ValueError, match="obligatorio"):
        canonicalize_organization_slug("---")
    with pytest.raises(ValueError, match="longitud máxima"):
        canonicalize_organization_slug("a" * 64)


@pytest.mark.django_db
def test_create_organization_is_active_and_has_first_owner() -> None:
    owner = _active_user("owner@example.com")

    creation = create_organization(
        owner_user_id=owner.pk,
        name="  Mi Salón  ",
        slug="  MI SALÓN  ",
    )

    organization = creation.organization
    membership = creation.owner_membership
    assert isinstance(organization.pk, uuid.UUID)
    assert organization.pk.version == 4
    assert organization.name == "Mi Salón"
    assert organization.slug == "mi-salon"
    assert organization.status == Organization.Status.ACTIVE
    assert membership.organization == organization
    assert membership.user == owner
    assert membership.role == Membership.Role.OWNER
    assert membership.status == Membership.Status.ACTIVE
    assert membership.joined_at is not None
    assert membership.suspended_at is None
    assert membership.revoked_at is None
    assert "country_code" not in {field.name for field in Organization._meta.get_fields()}


@pytest.mark.django_db
def test_create_organization_derives_slug_and_rejects_inactive_owner() -> None:
    pending = User.objects.create_user(email="pending-owner@example.com", password=PASSWORD)

    with pytest.raises(UserNotActive):
        create_organization(owner_user_id=pending.pk, name="No creada")

    assert not Organization.objects.exists()


@pytest.mark.django_db
def test_slug_collision_rolls_back_without_automatic_suffix() -> None:
    owner = _active_user("slug-owner@example.com")
    create_organization(owner_user_id=owner.pk, name="Mi Salón")

    with pytest.raises(OrganizationSlugConflict):
        create_organization(owner_user_id=owner.pk, name="Otro nombre", slug="MI SALÓN")

    assert list(Organization.objects.values_list("slug", flat=True)) == ["mi-salon"]
    assert Membership.objects.count() == 1


@pytest.mark.django_db
def test_name_can_change_without_changing_slug() -> None:
    owner = _active_user("rename-owner@example.com")
    organization = create_organization(owner_user_id=owner.pk, name="Nombre inicial").organization

    renamed = rename_organization(organization_id=organization.pk, name="  Nombre final  ")

    assert renamed.name == "Nombre final"
    assert renamed.slug == "nombre-inicial"


@pytest.mark.django_db
def test_organization_transitions_are_explicit_and_reversible() -> None:
    owner = _active_user("transition-owner@example.com")
    organization = create_organization(owner_user_id=owner.pk, name="Transiciones").organization

    suspended = transition_organization(
        organization_id=organization.pk,
        target_status=Organization.Status.SUSPENDED,
    )
    assert suspended.status == Organization.Status.SUSPENDED

    active = transition_organization(
        organization_id=organization.pk,
        target_status=Organization.Status.ACTIVE,
    )
    assert active.status == Organization.Status.ACTIVE

    with pytest.raises(InvalidOrganizationTransition):
        transition_organization(
            organization_id=organization.pk,
            target_status=Organization.Status.ACTIVE,
        )


@pytest.mark.django_db
def test_organization_transition_fails_closed_without_active_owner() -> None:
    owner = _active_user("corrupt-owner@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Sin propietario")
    Membership.objects.filter(pk=creation.owner_membership.pk).update(
        status=Membership.Status.REVOKED,
        revoked_at=creation.owner_membership.joined_at,
    )

    with pytest.raises(LastActiveOwnerRequired):
        transition_organization(
            organization_id=creation.organization.pk,
            target_status=Organization.Status.SUSPENDED,
        )
