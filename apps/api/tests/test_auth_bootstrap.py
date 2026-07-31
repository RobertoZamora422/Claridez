"""Pruebas del bootstrap local de usuario, organización y propietario."""

from __future__ import annotations

from io import StringIO
from typing import Any, cast
from unittest.mock import Mock

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from claridez.identity.models import User
from claridez.organizations.exceptions import BootstrapConflict
from claridez.organizations.models import Membership, Organization
from claridez.organizations.services import bootstrap_organization

PASSWORD = "A-strong-bootstrap-password-42!"


def test_four_django_password_validators_are_configured() -> None:
    validators = cast(list[dict[str, Any]], settings.AUTH_PASSWORD_VALIDATORS)
    names = [validator["NAME"].rsplit(".", maxsplit=1)[-1] for validator in validators]
    assert names == [
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    ]
    assert validators[1]["OPTIONS"] == {"min_length": 12}


@pytest.mark.django_db
def test_bootstrap_creates_active_verified_nontechnical_user_and_owner() -> None:
    result = bootstrap_organization(
        email="  FIRST.OWNER@EXAMPLE.COM ",
        display_name="Primera propietaria",
        password=PASSWORD,
        organization_name="  Salón Inicial  ",
        organization_slug=None,
    )

    assert result.created is True
    assert result.user.email == "first.owner@example.com"
    assert result.user.status == User.Status.ACTIVE
    assert result.user.is_active is True
    assert result.user.email_verified_at is not None
    assert result.user.is_staff is False
    assert result.user.is_superuser is False
    assert result.user.check_password(PASSWORD)
    assert result.organization.status == Organization.Status.ACTIVE
    assert result.owner_membership.role == Membership.Role.OWNER
    assert result.owner_membership.status == Membership.Status.ACTIVE


@pytest.mark.django_db
def test_bootstrap_reuses_technical_user_and_can_create_multiple_organizations() -> None:
    user = User.objects.create_superuser(email="technical@example.com", password=PASSWORD)
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at", "updated_at"])

    first = bootstrap_organization(
        email=user.email,
        organization_name="Primera organización",
        organization_slug="primera",
    )
    repeated = bootstrap_organization(
        email=user.email,
        organization_name="Nombre que puede haber cambiado",
        organization_slug="primera",
    )
    second = bootstrap_organization(
        email=user.email,
        organization_name="Segunda organización",
        organization_slug="segunda",
    )

    user.refresh_from_db()
    assert first.created is True
    assert repeated.created is False
    assert repeated.organization == first.organization
    assert second.created is True
    assert Organization.objects.count() == 2
    assert Membership.objects.filter(user=user, role=Membership.Role.OWNER).count() == 2
    assert user.is_staff is True
    assert user.is_superuser is True


@pytest.mark.django_db
@pytest.mark.parametrize("user_problem", ["pending", "unverified", "unusable"])
def test_bootstrap_rejects_existing_user_without_reusable_identity(user_problem: str) -> None:
    if user_problem == "pending":
        user = User.objects.create_user(email="problem@example.com", password=PASSWORD)
    else:
        user = User.objects.create_user(
            email="problem@example.com",
            password=None if user_problem == "unusable" else PASSWORD,
            status=User.Status.ACTIVE,
            email_verified_at=None if user_problem == "unverified" else timezone.now(),
        )

    with pytest.raises(BootstrapConflict):
        bootstrap_organization(
            email=user.email,
            organization_name="No creada",
            organization_slug="no-creada",
        )

    assert not Organization.objects.exists()


@pytest.mark.django_db
def test_bootstrap_rejects_weak_new_password_without_partial_writes() -> None:
    with pytest.raises(ValidationError):
        bootstrap_organization(
            email="weak@example.com",
            display_name="Weak",
            password="123456789012",
            organization_name="No creada",
            organization_slug=None,
        )

    assert not User.objects.filter(email="weak@example.com").exists()
    assert not Organization.objects.exists()


@pytest.mark.django_db
def test_bootstrap_rejects_existing_slug_with_another_owner() -> None:
    first = bootstrap_organization(
        email="first@example.com",
        display_name="Primera",
        password=PASSWORD,
        organization_name="Compartida",
        organization_slug="compartida",
    )
    assert first.created
    other = User.objects.create_user(
        email="other@example.com",
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )

    with pytest.raises(BootstrapConflict):
        bootstrap_organization(
            email=other.email,
            organization_name="Compartida",
            organization_slug="compartida",
        )


@pytest.mark.django_db
def test_management_command_uses_hidden_password_and_does_not_echo_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    prompts: list[str] = []

    def hidden_input(prompt: str) -> str:
        prompts.append(prompt)
        return PASSWORD

    monkeypatch.setattr(
        "claridez.organizations.management.commands.auth_bootstrap.getpass.getpass",
        hidden_input,
    )
    call_command(
        "auth_bootstrap",
        email="command@example.com",
        display_name="Propietaria comando",
        organization_name="Organización comando",
        stdout=output,
    )

    rendered = output.getvalue()
    assert "status=created" in rendered
    assert PASSWORD not in rendered
    assert prompts == ["Contraseña: ", "Confirmar contraseña: "]


@pytest.mark.django_db
def test_management_command_rejects_password_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "claridez.organizations.management.commands.auth_bootstrap.getpass.getpass",
        Mock(side_effect=[PASSWORD, "different-password-42!"]),
    )
    with pytest.raises(CommandError, match="no coinciden"):
        call_command(
            "auth_bootstrap",
            email="mismatch@example.com",
            display_name="Propietaria",
            organization_name="No creada",
        )
