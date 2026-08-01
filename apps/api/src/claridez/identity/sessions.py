"""Contrato de sesión absoluta de Claridez."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

SESSION_ABSOLUTE_EXPIRY_KEY = "claridez_absolute_expires_at"


def start_absolute_session(request: HttpRequest) -> datetime:
    """Fijar una única expiración absoluta sin renovación por actividad."""
    authenticated_at = timezone.now().replace(microsecond=0)
    expires_at = authenticated_at + timedelta(seconds=settings.SESSION_ABSOLUTE_AGE_SECONDS)
    request.session[SESSION_ABSOLUTE_EXPIRY_KEY] = int(expires_at.timestamp())
    request.session.set_expiry(expires_at)
    return expires_at
