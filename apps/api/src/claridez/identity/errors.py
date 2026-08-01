"""Respuestas de error JSON coherentes para autenticación."""

from __future__ import annotations

from typing import Any

from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework.views import exception_handler

AUTH_API_PREFIX = "/api/v1/auth/"


def error_response(code: str, message: str, *, status: int) -> JsonResponse:
    """Construir el contrato público mínimo de error."""
    response = JsonResponse(
        {"error": {"code": code, "message": message}},
        status=status,
    )
    response["Cache-Control"] = "no-store"
    return response


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Ocultar detalles internos de excepciones DRF en rutas de autenticación."""
    response = exception_handler(exc, context)
    request = context.get("request")
    path = getattr(request, "path_info", "")
    if response is not None and isinstance(path, str) and path.startswith(AUTH_API_PREFIX):
        response.data = {
            "error": {
                "code": "invalid_request",
                "message": "La solicitud no es válida.",
            }
        }
        response["Cache-Control"] = "no-store"
    return response
