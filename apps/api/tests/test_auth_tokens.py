"""Recuperación de contraseña, verificación y correo local."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from claridez.identity.models import User
from claridez.identity.tokens import email_verification_token_generator

PASSWORD = "correct-horse-battery-staple-43"
NEW_PASSWORD = "new-correct-horse-battery-staple-43"


def _csrf(client: Client) -> str:
    return str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])


def _post(client: Client, path: str, payload: dict[str, str]) -> Any:
    response = client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=_csrf(client),
    )
    assert response["Cache-Control"] == "no-store"
    return response


def _active_verified_user(email: str, *, password: str | None = PASSWORD) -> User:
    return User.objects.create_user(
        email=email,
        password=password,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _token_parts(message_body: str) -> tuple[str, str]:
    match = re.search(r"https?://\S+", message_body)
    assert match is not None
    values = parse_qs(urlsplit(match.group(0)).query)
    return values["uid"][0], values["token"][0]


def _uid(user: User) -> str:
    return urlsafe_base64_encode(force_bytes(user.pk))


@pytest.mark.django_db
def test_password_reset_request_is_generic_and_sends_only_for_eligible_user() -> None:
    eligible = _active_verified_user("eligible-reset@example.com")
    pending = User.objects.create_user(email="pending-reset@example.com", password=PASSWORD)
    unverified = User.objects.create_user(
        email="unverified-reset@example.com",
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )
    suspended = User.objects.create_user(
        email="suspended-reset@example.com",
        password=PASSWORD,
        status=User.Status.SUSPENDED,
    )
    unusable = _active_verified_user("unusable-reset@example.com", password=None)
    cases = [
        "missing-reset@example.com",
        pending.email,
        unverified.email,
        suspended.email,
        unusable.email,
        "",
    ]
    client = Client(enforce_csrf_checks=True)
    expected = None
    for email in cases:
        response = _post(
            client,
            "/api/v1/auth/password/reset/request/",
            {"email": email},
        )
        observed = (response.status_code, response.json())
        expected = expected or observed
        assert observed == expected == (202, {"status": "accepted"})
    assert mail.outbox == []

    response = _post(
        client,
        "/api/v1/auth/password/reset/request/",
        {"email": "  ELIGIBLE-RESET@EXAMPLE.COM "},
    )
    assert response.status_code == 202
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [eligible.email]
    assert "Recuperación" in message.subject
    assert PASSWORD not in message.body
    assert settings.AUTH_LINK_BASE_URL in message.body


@pytest.mark.django_db
def test_password_reset_confirmation_is_one_use_and_invalidates_sessions() -> None:
    user = _active_verified_user("confirm-reset@example.com")
    authenticated = Client(enforce_csrf_checks=True)
    login_response = authenticated.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": user.email, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=_csrf(authenticated),
    )
    assert login_response.status_code == 200

    anonymous = Client(enforce_csrf_checks=True)
    _post(
        anonymous,
        "/api/v1/auth/password/reset/request/",
        {"email": user.email},
    )
    uid, token = _token_parts(str(mail.outbox[0].body))
    confirmation = {
        "uid": uid,
        "token": token,
        "new_password": NEW_PASSWORD,
        "new_password_confirmation": NEW_PASSWORD,
    }

    valid = _post(anonymous, "/api/v1/auth/password/reset/confirm/", confirmation)
    used = _post(anonymous, "/api/v1/auth/password/reset/confirm/", confirmation)
    altered = _post(
        anonymous,
        "/api/v1/auth/password/reset/confirm/",
        {**confirmation, "token": f"{token}altered"},
    )

    assert valid.status_code == 200
    assert valid.json() == {"status": "ok"}
    assert used.status_code == altered.status_code == 400
    assert (
        used.json()
        == altered.json()
        == {"error": {"code": "invalid_or_expired_token", "message": "El enlace no es válido."}}
    )
    assert authenticated.get("/api/v1/auth/me/").status_code == 401
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)


@pytest.mark.django_db
def test_password_reset_token_expires_and_does_not_activate_suspended_user() -> None:
    user = _active_verified_user("expired-reset@example.com")
    issued_at = datetime(2026, 7, 31, 12, 0)
    with patch.object(default_token_generator, "_now", return_value=issued_at):
        token = default_token_generator.make_token(user)
    payload = {
        "uid": _uid(user),
        "token": token,
        "new_password": NEW_PASSWORD,
        "new_password_confirmation": NEW_PASSWORD,
    }
    client = Client(enforce_csrf_checks=True)
    with patch.object(
        default_token_generator,
        "_now",
        return_value=issued_at + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 1),
    ):
        expired = _post(client, "/api/v1/auth/password/reset/confirm/", payload)
    assert expired.status_code == 400

    fresh_token = default_token_generator.make_token(user)
    user.set_status(User.Status.SUSPENDED)
    user.save(update_fields=["status", "is_active", "updated_at"])
    suspended = _post(
        client,
        "/api/v1/auth/password/reset/confirm/",
        {**payload, "token": fresh_token},
    )
    user.refresh_from_db()
    assert suspended.status_code == 400
    assert user.status == User.Status.SUSPENDED
    assert user.check_password(PASSWORD)


@pytest.mark.django_db
def test_email_verification_activates_pending_and_supports_active_unverified() -> None:
    pending = User.objects.create_user(email="pending-verify@example.com", password=PASSWORD)
    client = Client(enforce_csrf_checks=True)
    request_response = _post(
        client,
        "/api/v1/auth/email/verification/request/",
        {"email": "  PENDING-VERIFY@EXAMPLE.COM "},
    )
    uid, token = _token_parts(str(mail.outbox[0].body))
    verified = _post(
        client,
        "/api/v1/auth/email/verification/confirm/",
        {"uid": uid, "token": token},
    )

    pending.refresh_from_db()
    assert request_response.status_code == 202
    assert verified.status_code == 200
    assert pending.status == User.Status.ACTIVE
    assert pending.is_active is True
    assert pending.email_verified_at is not None
    reused = _post(
        client,
        "/api/v1/auth/email/verification/confirm/",
        {"uid": uid, "token": token},
    )
    assert reused.status_code == 400

    active = User.objects.create_user(
        email="active-unverified@example.com",
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )
    active_token = email_verification_token_generator.make_token(active)
    active_response = _post(
        client,
        "/api/v1/auth/email/verification/confirm/",
        {"uid": _uid(active), "token": active_token},
    )
    active.refresh_from_db()
    assert active_response.status_code == 200
    assert active.status == User.Status.ACTIVE
    assert active.email_verified_at is not None


@pytest.mark.django_db
def test_email_verification_never_reactivates_suspended_user() -> None:
    user = User.objects.create_user(
        email="suspended-verify@example.com",
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )
    token = email_verification_token_generator.make_token(user)
    user.set_status(User.Status.SUSPENDED)
    user.save(update_fields=["status", "is_active", "updated_at"])

    response = _post(
        Client(enforce_csrf_checks=True),
        "/api/v1/auth/email/verification/confirm/",
        {"uid": _uid(user), "token": token},
    )

    user.refresh_from_db()
    assert response.status_code == 400
    assert user.status == User.Status.SUSPENDED
    assert user.is_active is False
    assert user.email_verified_at is None


@pytest.mark.django_db
def test_email_verification_token_tracks_email_security_version_and_timeout() -> None:
    issued_at = datetime(2026, 7, 31, 10, 0)
    first = User.objects.create_user(email="token-email@example.com", password=PASSWORD)
    with patch.object(email_verification_token_generator, "_now", return_value=issued_at):
        token = email_verification_token_generator.make_token(first)
        assert email_verification_token_generator.check_token(first, token)

        first.email = "changed-token-email@example.com"
        first.save(update_fields=["email", "updated_at"])
        assert not email_verification_token_generator.check_token(first, token)

        second = User.objects.create_user(email="token-version@example.com", password=PASSWORD)
        version_token = email_verification_token_generator.make_token(second)
        second.security_version += 1
        second.save(update_fields=["security_version", "updated_at"])
        assert not email_verification_token_generator.check_token(second, version_token)

        third = User.objects.create_user(email="token-expiry@example.com", password=PASSWORD)
        expiry_token = email_verification_token_generator.make_token(third)
    with patch.object(
        email_verification_token_generator,
        "_now",
        return_value=issued_at + timedelta(seconds=settings.EMAIL_VERIFICATION_TIMEOUT + 1),
    ):
        assert not email_verification_token_generator.check_token(third, expiry_token)


@pytest.mark.django_db
def test_verification_request_is_generic_and_messages_are_distinct_without_passwords() -> None:
    pending = User.objects.create_user(email="message-verify@example.com", password=PASSWORD)
    verified = _active_verified_user("already-verified@example.com")
    client = Client(enforce_csrf_checks=True)

    missing = _post(
        client,
        "/api/v1/auth/email/verification/request/",
        {"email": "missing-verify@example.com"},
    )
    already = _post(
        client,
        "/api/v1/auth/email/verification/request/",
        {"email": verified.email},
    )
    eligible = _post(
        client,
        "/api/v1/auth/email/verification/request/",
        {"email": pending.email},
    )

    assert missing.status_code == already.status_code == eligible.status_code == 202
    assert missing.json() == already.json() == eligible.json() == {"status": "accepted"}
    assert len(mail.outbox) == 1
    verification_message = mail.outbox[0]
    assert "Verificación" in verification_message.subject
    assert "Recuperación" not in verification_message.subject
    assert PASSWORD not in verification_message.body
