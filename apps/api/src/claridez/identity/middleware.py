"""Middleware de seguridad para las rutas de autenticación y sus sesiones."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from .errors import AUTH_API_PREFIX, error_response
from .sessions import SESSION_ABSOLUTE_EXPIRY_KEY

PROTECTED_AUTH_PATHS = frozenset(
    {
        "/api/v1/auth/me/",
        "/api/v1/auth/password/change/",
    }
)


class AuthenticationNoStoreMiddleware:
    """Impedir almacenamiento intermedio de toda respuesta de autenticación."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.path_info.startswith(AUTH_API_PREFIX):
            response["Cache-Control"] = "no-store"
        return response


class AbsoluteSessionExpiryMiddleware:
    """Cerrar sesiones autenticadas sin un límite absoluto válido."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.user.is_authenticated and not self._has_valid_expiry(request):
            logout(request)
            if request.path_info in PROTECTED_AUTH_PATHS:
                return error_response(
                    "authentication_required",
                    "Se requiere una sesión válida.",
                    status=401,
                )
        return self.get_response(request)

    @staticmethod
    def _has_valid_expiry(request: HttpRequest) -> bool:
        raw_expiry = request.session.get(SESSION_ABSOLUTE_EXPIRY_KEY)
        if isinstance(raw_expiry, bool) or not isinstance(raw_expiry, int):
            return False
        try:
            expires_at = datetime.fromtimestamp(raw_expiry, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return False
        return expires_at > timezone.now()
