"""Pruebas del usuario local y de su seguridad de sesión."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.contrib.auth import HASH_SESSION_KEY, authenticate, get_user
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.test import Client, override_settings

from claridez.identity.managers import canonicalize_email
from claridez.identity.models import User

PASSWORD = "correct-horse-battery-staple-41"


class _SessionRequest(HttpRequest):
    session: Any


def _active_user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )


def _request_with_client_session(client: Client) -> _SessionRequest:
    request = _SessionRequest()
    request.session = client.session
    return request


@pytest.mark.django_db
def test_user_schema_and_manager_defaults_are_canonical() -> None:
    user = User.objects.create_user(
        email="  PERSONA.Prueba@EXAMPLE.COM  ",
        password=PASSWORD,
        display_name="Persona de prueba",
    )
    field_names = {field.name for field in User._meta.get_fields()}

    assert isinstance(user.id, uuid.UUID)
    assert user.id.version == 4
    assert user.email == "persona.prueba@example.com"
    assert user.display_name == "Persona de prueba"
    assert user.status == User.Status.PENDING_VERIFICATION
    assert user.is_active is False
    assert user.security_version == 1
    assert user.check_password(PASSWORD)
    assert user.created_at is not None
    assert user.updated_at is not None
    assert User.USERNAME_FIELD == "email"
    assert User.REQUIRED_FIELDS == []
    assert {"username", "first_name", "last_name", "date_joined", "organization_id"}.isdisjoint(
        field_names
    )


@pytest.mark.django_db
def test_manager_supports_unusable_password_and_technical_superuser() -> None:
    unusable = User.objects.create_user(email="without-password@example.com")
    superuser = User.objects.create_superuser(
        email="  TECHNICAL@EXAMPLE.COM ",
        password=PASSWORD,
    )

    assert unusable.has_usable_password() is False
    assert authenticate(email=unusable.email, password=PASSWORD) is None
    assert superuser.email == "technical@example.com"
    assert superuser.status == User.Status.ACTIVE
    assert superuser.is_active is True
    assert superuser.is_staff is True
    assert superuser.is_superuser is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("extra_fields", "message"),
    [
        ({"is_staff": False}, "is_staff=True"),
        ({"is_superuser": False}, "is_superuser=True"),
        ({"status": User.Status.SUSPENDED}, "status=active"),
    ],
)
def test_superuser_manager_rejects_incoherent_technical_flags(
    extra_fields: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        User.objects.create_superuser(
            email=f"invalid-{message.split('=')[0]}@example.com",
            password=PASSWORD,
            **extra_fields,
        )


def test_email_canonicalizer_rejects_empty_values() -> None:
    assert canonicalize_email("  Mixed.Local@EXAMPLE.COM ") == "mixed.local@example.com"
    with pytest.raises(ValueError, match="obligatorio"):
        canonicalize_email("   ")
    with pytest.raises(ValueError, match="obligatorio"):
        canonicalize_email(None)


@pytest.mark.parametrize("display_name", ["Roberto Zamora", ""])
def test_name_methods_use_display_name_exclusively(display_name: str) -> None:
    user = User(email="roberto@example.com", display_name=display_name)

    assert user.get_full_name() == display_name
    assert user.get_short_name() == display_name


@pytest.mark.django_db
def test_username_and_natural_key_use_canonical_email() -> None:
    user = User.objects.create_user(
        email="  PERSONA.NATURAL@EXAMPLE.COM  ",
        password=PASSWORD,
    )

    assert user.get_username() == "persona.natural@example.com"
    assert User.objects.get_by_natural_key("persona.natural@example.com") == user
    assert User.objects.get_by_natural_key("  PERSONA.NATURAL@EXAMPLE.COM  ") == user


@pytest.mark.django_db
def test_manager_and_transition_keep_status_and_is_active_together() -> None:
    active_user = _active_user("active@example.com")
    assert bool(active_user.is_active)

    active_user.set_status(User.Status.SUSPENDED)
    assert active_user.status == User.Status.SUSPENDED
    assert not bool(active_user.is_active)

    active_user.set_status(User.Status.PENDING_VERIFICATION)
    assert active_user.status == User.Status.PENDING_VERIFICATION
    assert not bool(active_user.is_active)

    with pytest.raises(ValueError, match="no reconocido"):
        active_user.set_status("unknown")
    with pytest.raises(ValueError, match="contradictorios"):
        User.objects.create_user(
            email="contradictory@example.com",
            password=PASSWORD,
            status=User.Status.ACTIVE,
            is_active=False,
        )


@pytest.mark.django_db(transaction=True)
def test_postgresql_enforces_email_status_and_security_constraints() -> None:
    user = User.objects.create_user(email="canonical@example.com", password=PASSWORD)

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(email="")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(email=" NOT-CANONICAL@EXAMPLE.COM ")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(status=User.Status.ACTIVE, is_active=False)

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(
            status=User.Status.PENDING_VERIFICATION,
            is_active=True,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(status=User.Status.SUSPENDED, is_active=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(status="arbitrary", is_active=False)

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(security_version=0)

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(email="CANONICAL@EXAMPLE.COM")


@pytest.mark.django_db
def test_session_hash_is_user_specific_versioned_and_opaque() -> None:
    first = _active_user("first@example.com")
    second = _active_user("second@example.com")
    second.password = first.password
    second.security_version = first.security_version

    first_hash = first.get_session_auth_hash()
    second_hash = second.get_session_auth_hash()

    assert first_hash != second_hash

    first.security_version = 987_654_321
    versioned_hash = first.get_session_auth_hash()
    assert versioned_hash != first_hash
    assert versioned_hash != first.password
    assert PASSWORD not in versioned_hash
    assert first.password not in versioned_hash
    assert str(first.security_version) not in versioned_hash


@pytest.mark.django_db
def test_security_version_invalidates_an_existing_session() -> None:
    user = _active_user("versioned-session@example.com")
    client = Client()
    client.force_login(user)
    assert get_user(_request_with_client_session(client)).pk == user.pk

    user.security_version += 1
    user.save(update_fields=["security_version", "updated_at"])

    assert get_user(_request_with_client_session(client)).is_anonymous


@pytest.mark.django_db
def test_password_change_invalidates_an_existing_session() -> None:
    user = _active_user("password-change@example.com")
    client = Client()
    client.force_login(user)
    assert get_user(_request_with_client_session(client)).pk == user.pk

    user.set_password("another-secure-password-41")
    user.save(update_fields=["password", "updated_at"])

    assert get_user(_request_with_client_session(client)).is_anonymous


@pytest.mark.django_db
def test_suspended_user_cannot_authenticate_or_keep_a_session() -> None:
    user = _active_user("suspended@example.com")
    client = Client()
    client.force_login(user)
    assert authenticate(email=user.email, password=PASSWORD) is not None

    user.set_status(User.Status.SUSPENDED)
    user.save(update_fields=["status", "is_active", "updated_at"])

    assert authenticate(email=user.email, password=PASSWORD) is None
    assert get_user(_request_with_client_session(client)).is_anonymous


@pytest.mark.django_db
@override_settings(
    SECRET_KEY="current-secret-key-for-session-fallback-tests",
    SECRET_KEY_FALLBACKS=["previous-secret-key-for-session-fallback-tests"],
)
def test_session_hash_preserves_secret_key_fallbacks() -> None:
    user = _active_user("fallback@example.com")
    client = Client()
    client.force_login(user)
    session = client.session
    session[HASH_SESSION_KEY] = user._get_session_auth_hash(
        secret="previous-secret-key-for-session-fallback-tests"
    )
    session.save()

    request = _request_with_client_session(client)
    loaded_user = get_user(request)
    assert loaded_user.pk == user.pk
    assert request.session[HASH_SESSION_KEY] == user.get_session_auth_hash()
