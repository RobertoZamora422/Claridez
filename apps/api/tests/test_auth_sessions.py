"""Expiración absoluta y seguridad de cambios de contraseña."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone

from claridez.identity.models import User
from claridez.identity.sessions import SESSION_ABSOLUTE_EXPIRY_KEY

PASSWORD = "correct-horse-battery-staple-43"
NEW_PASSWORD = "another-correct-horse-battery-43"


def _user(email: str = "session@example.com") -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _csrf(client: Client) -> str:
    return str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])


def _post(client: Client, path: str, payload: dict[str, str], token: str) -> Any:
    response = client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response["Cache-Control"] == "no-store"
    return response


def _login(client: Client, user: User) -> None:
    response = _post(
        client,
        "/api/v1/auth/login/",
        {"email": user.email, "password": PASSWORD},
        _csrf(client),
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_login_sets_exact_eight_hour_absolute_expiry() -> None:
    user = _user()
    client = Client(enforce_csrf_checks=True)
    authenticated_at = datetime(2026, 7, 31, 18, 0, tzinfo=UTC)

    with patch("claridez.identity.sessions.timezone.now", return_value=authenticated_at):
        _login(client, user)

    absolute_timestamp = client.session[SESSION_ABSOLUTE_EXPIRY_KEY]
    assert datetime.fromtimestamp(absolute_timestamp, tz=UTC) == authenticated_at + timedelta(
        hours=8
    )
    assert client.session.get_expiry_date() == authenticated_at + timedelta(hours=8)


@pytest.mark.django_db
def test_session_activity_and_later_writes_do_not_renew_absolute_expiry() -> None:
    user = _user("non-sliding@example.com")
    client = Client(enforce_csrf_checks=True)
    _login(client, user)
    original_session = client.session
    original_absolute = original_session[SESSION_ABSOLUTE_EXPIRY_KEY]
    original_django_expiry = original_session.get("_session_expiry")

    original_session["last_organization_id"] = "00000000-0000-4000-8000-000000000043"
    original_session.save()
    response = client.get("/api/v1/auth/me/")

    assert response.status_code == 200
    assert SESSION_ABSOLUTE_EXPIRY_KEY not in response.cookies
    assert client.session[SESSION_ABSOLUTE_EXPIRY_KEY] == original_absolute
    assert client.session.get("_session_expiry") == original_django_expiry
    assert client.session["last_organization_id"] == "00000000-0000-4000-8000-000000000043"


@pytest.mark.django_db
def test_expired_missing_or_corrupt_authenticated_session_is_closed() -> None:
    for corruption in ("expired", "missing", "corrupt"):
        user = _user(f"{corruption}@example.com")
        client = Client(enforce_csrf_checks=True)
        _login(client, user)
        session = client.session
        if corruption == "expired":
            expiry = datetime.fromtimestamp(session[SESSION_ABSOLUTE_EXPIRY_KEY], tz=UTC)
            now = expiry + timedelta(seconds=1)
        elif corruption == "missing":
            del session[SESSION_ABSOLUTE_EXPIRY_KEY]
            session.save()
            now = timezone.now()
        else:
            session[SESSION_ABSOLUTE_EXPIRY_KEY] = "not-an-instant"
            session.save()
            now = timezone.now()

        with patch("claridez.identity.middleware.timezone.now", return_value=now):
            response = client.get("/api/v1/auth/me/")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_required"
        assert response["Cache-Control"] == "no-store"
        assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_anonymous_request_is_not_affected_by_corrupt_absolute_value() -> None:
    client = Client()
    session = client.session
    session[SESSION_ABSOLUTE_EXPIRY_KEY] = "corrupt-but-anonymous"
    session.save()

    assert client.get("/api/v1/auth/csrf/").status_code == 200


@pytest.mark.django_db
def test_password_change_preserves_current_session_and_invalidates_other_sessions() -> None:
    user = _user("password-change-http@example.com")
    current = Client(enforce_csrf_checks=True)
    other = Client(enforce_csrf_checks=True)
    _login(current, user)
    _login(other, user)
    absolute_expiry = current.session[SESSION_ABSOLUTE_EXPIRY_KEY]
    django_expiry = current.session.get("_session_expiry")
    session_key = current.session.session_key

    changed = _post(
        current,
        "/api/v1/auth/password/change/",
        {
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "new_password_confirmation": NEW_PASSWORD,
        },
        _csrf(current),
    )

    assert changed.status_code == 200
    assert current.session.session_key != session_key
    assert current.session[SESSION_ABSOLUTE_EXPIRY_KEY] == absolute_expiry
    assert current.session.get("_session_expiry") == django_expiry
    assert current.get("/api/v1/auth/me/").status_code == 200
    assert other.get("/api/v1/auth/me/").status_code == 401
    user.refresh_from_db()
    assert not user.check_password(PASSWORD)
    assert user.check_password(NEW_PASSWORD)


@pytest.mark.django_db
def test_password_change_rejects_wrong_current_mismatch_and_weak_password() -> None:
    user = _user("password-errors@example.com")
    cases = [
        {
            "current_password": "wrong",
            "new_password": NEW_PASSWORD,
            "new_password_confirmation": NEW_PASSWORD,
        },
        {
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "new_password_confirmation": "different-password-43",
        },
        {
            "current_password": PASSWORD,
            "new_password": "123456789012",
            "new_password_confirmation": "123456789012",
        },
    ]
    for payload in cases:
        client = Client(enforce_csrf_checks=True)
        _login(client, user)
        response = _post(
            client,
            "/api/v1/auth/password/change/",
            payload,
            _csrf(client),
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "password_change_failed"

    user.refresh_from_db()
    assert user.check_password(PASSWORD)
