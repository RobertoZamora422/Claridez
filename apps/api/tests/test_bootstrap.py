"""Pruebas del contrato técnico mínimo de la API."""

from io import StringIO

from django.conf import settings
from django.core.checks import run_checks
from django.core.management import call_command


def test_bootstrap_uses_postgresql_and_generates_openapi_without_database() -> None:
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
    assert "paths: {}" in schema
