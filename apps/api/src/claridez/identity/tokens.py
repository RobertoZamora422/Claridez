"""Tokens de un solo uso para verificar correos."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int

from .models import User


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """Separar la verificación del generador de recuperación de contraseña."""

    key_salt = "claridez.identity.tokens.EmailVerificationTokenGenerator"

    def check_token(self, user: User | None, token: str | None) -> bool:
        if user is None or not token:
            return False
        try:
            timestamp_base36, _ = token.split("-")
            timestamp = base36_to_int(timestamp_base36)
        except (TypeError, ValueError):
            return False

        for secret in [self.secret, *self.secret_fallbacks]:
            expected = self._make_token_with_timestamp(user, timestamp, secret)
            if constant_time_compare(expected, token):
                break
        else:
            return False

        age = self._num_seconds(self._now()) - timestamp
        return age <= settings.EMAIL_VERIFICATION_TIMEOUT

    def _make_hash_value(self, user: User, timestamp: int) -> str:
        verified_at = (
            ""
            if user.email_verified_at is None
            else user.email_verified_at.replace(microsecond=0, tzinfo=None)
        )
        return f"{user.pk}{timestamp}{user.email}{verified_at}{user.security_version}{user.status}"


email_verification_token_generator = EmailVerificationTokenGenerator()
