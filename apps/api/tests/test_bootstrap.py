"""Pruebas del contrato técnico mínimo de la API."""

from io import StringIO

from django.conf import settings
from django.core.checks import run_checks
from django.core.management import call_command


def test_bootstrap_uses_postgresql_and_generates_approved_openapi_without_database() -> None:
    """Validar configuración y esquema sin abrir una conexión de base de datos."""
    assert run_checks() == []

    database_engine = settings.DATABASES["default"].get("ENGINE")
    assert isinstance(database_engine, str)
    assert database_engine == "django.db.backends.postgresql"
    assert "sqlite" not in database_engine

    schema_output = StringIO()
    call_command("spectacular", stdout=schema_output, validate=True, fail_on_warn=True)

    schema = schema_output.getvalue()
    assert "openapi: 3.0.3" in schema
    for path in (
        "/api/v1/auth/csrf/:",
        "/api/v1/auth/login/:",
        "/api/v1/auth/logout/:",
        "/api/v1/auth/me/:",
        "/api/v1/auth/password/change/:",
        "/api/v1/auth/password/reset/request/:",
        "/api/v1/auth/password/reset/confirm/:",
        "/api/v1/auth/email/verification/request/:",
        "/api/v1/auth/email/verification/confirm/:",
        "/api/v1/organizations/:",
        "/api/v1/organizations/context/:",
        "/api/v1/organizations/{organization_id}/settings/:",
        "/api/v1/organizations/{organization_id}/memberships/:",
    ):
        assert path in schema
    assert "cookieAuth:" in schema
