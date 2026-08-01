"""Protección PostgreSQL de intentos de login mediante django-axes."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from axes.models import AccessAttempt  # type: ignore[import-untyped]
from django.conf import settings
from django.db import connection
from django.test import Client
from django.utils import timezone

from claridez.identity.models import User

pytestmark = [pytest.mark.integration, pytest.mark.django_db]
PASSWORD = "correct-horse-battery-staple-43"


def _user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _csrf(client: Client, *, remote_addr: str = "127.0.0.1") -> str:
    response = client.get("/api/v1/auth/csrf/", REMOTE_ADDR=remote_addr)
    return str(response.json()["csrf_token"])


def _login(
    client: Client,
    *,
    email: str,
    password: str,
    token: str,
    remote_addr: str,
    forwarded_for: str = "203.0.113.100",
) -> Any:
    return client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": email, "password": password}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
        REMOTE_ADDR=remote_addr,
        HTTP_X_FORWARDED_FOR=forwarded_for,
    )


def test_axes_configuration_is_database_backed_combination_only() -> None:
    assert settings.AXES_HANDLER == "axes.handlers.database.AxesDatabaseHandler"
    assert settings.AXES_FAILURE_LIMIT == 5
    assert timedelta(minutes=15) == settings.AXES_COOLOFF_TIME
    assert settings.AXES_USE_ATTEMPT_EXPIRATION is True
    assert settings.AXES_LOCKOUT_PARAMETERS == [["username", "ip_address"]]
    assert settings.AXES_RESET_ON_SUCCESS is True
    assert settings.AXES_HTTP_RESPONSE_CODE == 429
    assert settings.AXES_CLIENT_IP_CALLABLE.endswith("client_ip_from_remote_addr")

    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
    assert {"axes_accessattempt", "axes_accessfailurelog", "axes_accesslog"} <= set(tables)


def test_axes_locks_only_canonical_email_and_remote_addr_combination() -> None:
    user = _user("axes-combination@example.com")
    other = _user("axes-other@example.com")
    client = Client(enforce_csrf_checks=True)
    token = _csrf(client)

    responses = [
        _login(
            client,
            email="  AXES-COMBINATION@EXAMPLE.COM ",
            password="wrong-password",
            token=token,
            remote_addr="127.0.0.1",
            forwarded_for=f"198.51.100.{index}",
        )
        for index in range(1, 6)
    ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401, 429]
    assert responses[-1].json()["error"]["code"] == "too_many_attempts"
    assert responses[-1]["Retry-After"] == "900"
    assert responses[-1]["Cache-Control"] == "no-store"
    attempt = AccessAttempt.objects.get(username=user.email)
    assert attempt.ip_address == "127.0.0.1"
    assert attempt.failures_since_start == 5

    same_email_other_ip = _login(
        client,
        email=user.email,
        password="wrong-password",
        token=token,
        remote_addr="127.0.0.2",
    )
    other_email_same_ip = _login(
        client,
        email=other.email,
        password="wrong-password",
        token=token,
        remote_addr="127.0.0.1",
    )
    assert same_email_other_ip.status_code == 401
    assert other_email_same_ip.status_code == 401


def test_axes_resets_after_success_and_unlocks_after_cooloff() -> None:
    user = _user("axes-reset@example.com")
    client = Client(enforce_csrf_checks=True)
    token = _csrf(client)

    for _ in range(4):
        assert (
            _login(
                client,
                email=user.email,
                password="wrong-password",
                token=token,
                remote_addr="127.0.0.3",
            ).status_code
            == 401
        )
    assert (
        _login(
            client,
            email=user.email,
            password=PASSWORD,
            token=token,
            remote_addr="127.0.0.3",
        ).status_code
        == 200
    )
    assert not AccessAttempt.objects.filter(username=user.email, ip_address="127.0.0.3").exists()

    token = _csrf(client, remote_addr="127.0.0.3")
    logout = client.post(
        "/api/v1/auth/logout/",
        data="{}",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
        REMOTE_ADDR="127.0.0.3",
    )
    assert logout.status_code == 200
    token = _csrf(client, remote_addr="127.0.0.3")
    for _ in range(5):
        locked = _login(
            client,
            email=user.email,
            password="wrong-password",
            token=token,
            remote_addr="127.0.0.3",
        )
    assert locked.status_code == 429

    AccessAttempt.objects.filter(username=user.email, ip_address="127.0.0.3").update(
        attempt_time=timezone.now() - timedelta(minutes=16)
    )
    unlocked = _login(
        client,
        email=user.email,
        password=PASSWORD,
        token=token,
        remote_addr="127.0.0.3",
    )
    assert unlocked.status_code == 200
