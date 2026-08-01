"""Integración mínima y prudente con django-axes."""

from __future__ import annotations

import ipaddress
from typing import Any

from django.http import HttpRequest, JsonResponse

from .errors import error_response

LOGIN_RETRY_AFTER_SECONDS = 15 * 60


def client_ip_from_remote_addr(request: HttpRequest) -> str | None:
    """Usar solo la dirección observada por Django, nunca cabeceras proxy."""
    raw_address = request.META.get("REMOTE_ADDR")
    if not isinstance(raw_address, str):
        return None
    try:
        return str(ipaddress.ip_address(raw_address))
    except ValueError:
        return None


def json_lockout_response(
    request: HttpRequest,
    response: Any = None,
    credentials: Any = None,
    *args: Any,
    **kwargs: Any,
) -> JsonResponse:
    """Responder un bloqueo temporal sin exponer la identidad evaluada."""
    del request, response, credentials, args, kwargs
    locked = error_response(
        "too_many_attempts",
        "Demasiados intentos. Inténtalo nuevamente más tarde.",
        status=429,
    )
    locked["Retry-After"] = str(LOGIN_RETRY_AFTER_SECONDS)
    return locked
