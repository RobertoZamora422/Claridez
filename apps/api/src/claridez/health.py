"""Endpoints técnicos mínimos de proceso y disponibilidad."""

import logging

from django.db import DatabaseError, connections
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


def _response(payload: dict[str, str], *, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


@require_http_methods(["GET", "HEAD"])
def health(_request: HttpRequest) -> JsonResponse:
    """Confirmar solo que el proceso Django puede responder."""
    return _response({"status": "ok"})


@require_http_methods(["GET", "HEAD"])
def ready(_request: HttpRequest) -> JsonResponse:
    """Confirmar disponibilidad mediante una consulta mínima a PostgreSQL."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        logger.warning("postgresql_readiness_unavailable")
        return _response({"status": "unavailable"}, status=503)
    return _response({"status": "ready"})
