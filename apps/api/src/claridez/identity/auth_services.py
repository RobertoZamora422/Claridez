"""Servicios transaccionales de credenciales y verificación."""

from __future__ import annotations

from uuid import UUID

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from .models import User
from .tokens import email_verification_token_generator


class InvalidCurrentPassword(Exception):
    pass


class InvalidOrExpiredToken(Exception):
    pass


def is_login_eligible(user: User) -> bool:
    return (
        user.status == User.Status.ACTIVE
        and bool(user.is_active)
        and user.email_verified_at is not None
        and user.has_usable_password()
    )


def is_password_reset_eligible(user: User) -> bool:
    return is_login_eligible(user)


def is_email_verification_eligible(user: User) -> bool:
    return user.email_verified_at is None and user.status in {
        User.Status.PENDING_VERIFICATION,
        User.Status.ACTIVE,
    }


def change_password(
    *,
    request: HttpRequest,
    user_id: UUID,
    current_password: str,
    new_password: str,
) -> User:
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if not is_login_eligible(user) or not user.check_password(current_password):
            raise InvalidCurrentPassword
        validate_password(new_password, user=user)
        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])
        update_session_auth_hash(request, user)
        return user


def _user_from_uid(uid: str, *, for_update: bool) -> User:
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        query = User.objects.select_for_update() if for_update else User.objects
        return query.get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        raise InvalidOrExpiredToken from None


def confirm_password_reset(*, uid: str, token: str, new_password: str) -> User:
    with transaction.atomic():
        user = _user_from_uid(uid, for_update=True)
        if not is_password_reset_eligible(user):
            raise InvalidOrExpiredToken
        if not default_token_generator.check_token(user, token):
            raise InvalidOrExpiredToken
        validate_password(new_password, user=user)
        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])
        return user


def confirm_email_verification(*, uid: str, token: str) -> User:
    with transaction.atomic():
        user = _user_from_uid(uid, for_update=True)
        if not is_email_verification_eligible(user):
            raise InvalidOrExpiredToken
        if not email_verification_token_generator.check_token(user, token):
            raise InvalidOrExpiredToken
        user.email_verified_at = timezone.now()
        update_fields = ["email_verified_at", "updated_at"]
        if user.status == User.Status.PENDING_VERIFICATION:
            user.set_status(User.Status.ACTIVE)
            update_fields.extend(["status", "is_active"])
        user.save(update_fields=update_fields)
        return user
