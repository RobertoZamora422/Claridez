"""Contrato HTTP, CSRF y respuestas públicas de autenticación."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.conf import settings
from django.test import Client
from django.urls import get_resolver
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator

from claridez.identity.models import User

LOGIN_PATH = "/api/v1/auth/login/"
CSRF_PATH = "/api/v1/auth/csrf/"
PASSWORD = "correct-horse-battery-staple-43"


def _active_verified_user(
    email: str = "person@example.com",
    password: str = PASSWORD,
    display_name: str = "",
) -> User:
    return User.objects.create_user(
        email=email,
        password=password,
        display_name=display_name,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _csrf(client: Client) -> str:
    response = client.get(CSRF_PATH)
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def _post(client: Client, path: str, payload: dict[str, str], token: str) -> Any:
    response = client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response["Cache-Control"] == "no-store"
    return response


def test_csrf_endpoint_sets_http_only_cookie_and_is_not_cached() -> None:
    client = Client(enforce_csrf_checks=True)

    response = client.get(CSRF_PATH)

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.json()["csrf_token"]
    csrf_cookie = response.cookies[settings.CSRF_COOKIE_NAME]
    assert csrf_cookie["httponly"] is True
    assert csrf_cookie["samesite"] == "Lax"
    assert csrf_cookie["secure"] == ""


@pytest.mark.django_db
def test_csrf_is_required_rotated_on_login_and_rotated_after_logout() -> None:
    user = _active_verified_user()
    client = Client(enforce_csrf_checks=True)

    missing = client.post(
        LOGIN_PATH,
        data=json.dumps({"email": user.email, "password": PASSWORD}),
        content_type="application/json",
    )
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_failed"

    token_before_login = _csrf(client)
    cookie_before_login = client.cookies[settings.CSRF_COOKIE_NAME].value
    wrong = _post(
        client,
        LOGIN_PATH,
        {"email": user.email, "password": PASSWORD},
        "wrong-token",
    )
    assert wrong.status_code == 403

    session = client.session
    session["pre_authentication_value"] = "preserved"
    session.save()
    session_key_before_login = session.session_key

    logged_in = _post(
        client,
        LOGIN_PATH,
        {"email": "  PERSON@EXAMPLE.COM ", "password": PASSWORD},
        token_before_login,
    )
    assert logged_in.status_code == 200
    assert client.session.session_key != session_key_before_login
    assert client.cookies[settings.CSRF_COOKIE_NAME].value != cookie_before_login

    stale_logout = _post(client, "/api/v1/auth/logout/", {}, token_before_login)
    assert stale_logout.status_code == 403

    token_before_logout = _csrf(client)
    cookie_before_logout = client.cookies[settings.CSRF_COOKIE_NAME].value
    logged_out = _post(client, "/api/v1/auth/logout/", {}, token_before_logout)
    assert logged_out.status_code == 200
    assert logged_out.json() == {"status": "ok"}
    assert client.cookies[settings.CSRF_COOKIE_NAME].value != cookie_before_logout

    stale_after_logout = _post(client, "/api/v1/auth/logout/", {}, token_before_logout)
    assert stale_after_logout.status_code == 403
    assert _post(client, "/api/v1/auth/logout/", {}, _csrf(client)).status_code == 200


@pytest.mark.django_db
def test_login_me_logout_and_cookie_contract() -> None:
    user = _active_verified_user(display_name="Persona Claridez")
    client = Client(enforce_csrf_checks=True)

    response = _post(
        client,
        LOGIN_PATH,
        {"email": user.email, "password": PASSWORD},
        _csrf(client),
    )

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert set(response.json()["user"]) == {
        "id",
        "email",
        "display_name",
        "status",
        "email_verified_at",
    }
    session_cookie = response.cookies[settings.SESSION_COOKIE_NAME]
    assert session_cookie["httponly"] is True
    assert session_cookie["samesite"] == "Lax"
    assert session_cookie["secure"] == ""

    me = client.get("/api/v1/auth/me/")
    assert me.status_code == 200
    rendered = json.dumps(me.json())
    assert all(word not in rendered for word in ("organization", "membership", "capabilities"))

    token = _csrf(client)
    assert _post(client, "/api/v1/auth/logout/", {}, token).status_code == 200
    assert client.get("/api/v1/auth/me/").status_code == 401


@pytest.mark.django_db
def test_each_successful_login_rotates_even_an_existing_authenticated_session() -> None:
    user = _active_verified_user("repeat-login@example.com")
    client = Client(enforce_csrf_checks=True)

    first = _post(
        client,
        LOGIN_PATH,
        {"email": user.email, "password": PASSWORD},
        _csrf(client),
    )
    first_session_key = client.session.session_key
    second = _post(
        client,
        LOGIN_PATH,
        {"email": user.email, "password": PASSWORD},
        _csrf(client),
    )

    assert first.status_code == second.status_code == 200
    assert client.session.session_key != first_session_key


@pytest.mark.django_db
def test_every_ineligible_identity_has_the_same_login_error() -> None:
    pending = User.objects.create_user(email="pending@example.com", password=PASSWORD)
    unverified = User.objects.create_user(
        email="unverified@example.com",
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )
    suspended = User.objects.create_user(
        email="suspended@example.com",
        password=PASSWORD,
        status=User.Status.SUSPENDED,
    )
    unusable = User.objects.create_user(
        email="unusable@example.com",
        password=None,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    cases = [
        ("missing@example.com", PASSWORD),
        (pending.email, PASSWORD),
        (unverified.email, PASSWORD),
        (suspended.email, PASSWORD),
        (unusable.email, PASSWORD),
        (_active_verified_user("wrong@example.com").email, "wrong-password"),
    ]
    observed: list[tuple[int, dict[str, object]]] = []
    for email, password in cases:
        client = Client(enforce_csrf_checks=True)
        response = _post(
            client,
            LOGIN_PATH,
            {"email": email, "password": password},
            _csrf(client),
        )
        observed.append((response.status_code, response.json()))

    assert len({json.dumps(item, sort_keys=True) for item in observed}) == 1
    assert observed[0] == (
        401,
        {
            "error": {
                "code": "invalid_credentials",
                "message": "No fue posible iniciar sesión con esas credenciales.",
            }
        },
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/login/",
        "/api/v1/auth/logout/",
        "/api/v1/auth/password/change/",
        "/api/v1/auth/password/reset/request/",
        "/api/v1/auth/password/reset/confirm/",
        "/api/v1/auth/email/verification/request/",
        "/api/v1/auth/email/verification/confirm/",
    ],
)
def test_all_authentication_posts_require_csrf_and_are_not_cached(path: str) -> None:
    client = Client(enforce_csrf_checks=True)
    response = client.post(path, data="{}", content_type="application/json")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert response["Cache-Control"] == "no-store"


def test_session_cookie_and_environment_security_settings() -> None:
    assert settings.SESSION_SAVE_EVERY_REQUEST is False
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_COOKIE_SECURE is False
    assert settings.CSRF_COOKIE_HTTPONLY is True
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"
    assert settings.CSRF_COOKIE_SECURE is False


def test_openapi_contains_only_the_nine_approved_authentication_endpoints() -> None:
    schema = SchemaGenerator().get_schema(request=None, public=True)  # type: ignore[no-untyped-call]
    assert schema is not None
    auth_paths = {path for path in schema["paths"] if path.startswith("/api/v1/auth/")}
    assert auth_paths == {
        "/api/v1/auth/csrf/",
        "/api/v1/auth/login/",
        "/api/v1/auth/logout/",
        "/api/v1/auth/me/",
        "/api/v1/auth/password/change/",
        "/api/v1/auth/password/reset/request/",
        "/api/v1/auth/password/reset/confirm/",
        "/api/v1/auth/email/verification/request/",
        "/api/v1/auth/email/verification/confirm/",
    }
    rendered = json.dumps(
        {path: schema["paths"][path] for path in auth_paths},
    )
    assert all(word not in rendered for word in ("organization_id", "membership", "capability"))


def test_root_routes_keep_health_and_mount_only_the_approved_api_groups() -> None:
    routes = {str(pattern.pattern) for pattern in get_resolver().url_patterns}
    assert routes == {
        "health",
        "ready",
        "api/v1/auth/",
        "api/v1/organizations/",
        "api/v1/external/documents/",
        "api/v1/public/",
        "api/v1/portal/",
        "api/v1/webhooks/communications/",
    }
