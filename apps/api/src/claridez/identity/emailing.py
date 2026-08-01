"""Entrega local de mensajes de autenticación."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import User
from .tokens import email_verification_token_generator

logger = logging.getLogger(__name__)


def _uid(user: User) -> str:
    return urlsafe_base64_encode(force_bytes(user.pk))


def _link(path: str, *, uid: str, token: str) -> str:
    query = urlencode({"uid": uid, "token": token})
    return f"{settings.AUTH_LINK_BASE_URL}{path}?{query}"


def _deliver(*, subject: str, body: str, recipient: str) -> bool:
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
    except Exception:
        logger.warning("authentication_email_delivery_failed")
        return False
    return True


def send_password_reset_email(user: User) -> bool:
    token = default_token_generator.make_token(user)
    link = _link(
        "/auth/password-reset/confirm",
        uid=_uid(user),
        token=token,
    )
    return _deliver(
        subject="Recuperación de contraseña de Claridez",
        body=(
            "Se solicitó restablecer tu contraseña de Claridez.\n\n"
            f"Continúa mediante este enlace:\n{link}\n\n"
            "Si no realizaste la solicitud, ignora este mensaje."
        ),
        recipient=user.email,
    )


def send_email_verification(user: User) -> bool:
    token = email_verification_token_generator.make_token(user)
    link = _link(
        "/auth/email-verification/confirm",
        uid=_uid(user),
        token=token,
    )
    return _deliver(
        subject="Verificación de correo de Claridez",
        body=(
            "Verifica tu correo para completar tu identidad en Claridez.\n\n"
            f"Continúa mediante este enlace:\n{link}\n\n"
            "Si no esperabas este mensaje, puedes ignorarlo."
        ),
        recipient=user.email,
    )
