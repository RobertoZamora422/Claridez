"""Pruebas de validación, perfiles y configuración local."""

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from claridez.logging import SafeJsonFormatter
from claridez.settings.environment import (
    BootstrapSettings,
    MigrationSettings,
    RuntimeSettings,
    load_runtime_settings,
)
from claridez.settings.environment import (
    TestSettings as LocalTestSettings,
)


def test_django_uses_only_postgresql_with_localization_and_no_cors() -> None:
    database = settings.DATABASES["default"]

    assert database["ENGINE"] == "django.db.backends.postgresql"
    assert database["USER"] == "claridez_test_runner"
    assert database["TEST"]["NAME"] == "claridez_test"
    assert settings.TIME_ZONE == "America/Guayaquil"
    assert settings.USE_TZ is True
    assert settings.LANGUAGE_CODE == "es-ec"
    assert all("cors" not in app.lower() for app in settings.INSTALLED_APPS)
    assert all("cors" not in middleware.lower() for middleware in settings.MIDDLEWARE)


def test_profiles_load_only_their_own_credentials() -> None:
    runtime_fields = set(RuntimeSettings.model_fields)
    migration_fields = set(MigrationSettings.model_fields)
    test_fields = set(LocalTestSettings.model_fields)
    bootstrap_fields = set(BootstrapSettings.model_fields)

    assert "postgres_admin_password" not in runtime_fields
    assert "migration_db_password" not in runtime_fields
    assert "db_password" not in migration_fields
    assert "postgres_admin_password" not in test_fields
    assert {
        "postgres_admin_password",
        "migration_db_password",
        "db_password",
        "test_db_password",
    } <= bootstrap_fields


def test_invalid_configuration_fails_without_echoing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker_secret = "not-visible-configuration-secret-1234567890"
    monkeypatch.setenv("CLARIDEZ_DB_PASSWORD", marker_secret)
    monkeypatch.setenv("CLARIDEZ_DB_PORT", "invalid-port")

    with pytest.raises(ImproperlyConfigured) as captured:
        load_runtime_settings()

    message = str(captured.value)
    assert "db_port" in message
    assert marker_secret not in message
    assert "invalid-port" not in message


def test_structured_formatter_emits_valid_minimal_json() -> None:
    import logging

    record = logging.LogRecord(
        name="claridez.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="technical_event",
        args=(),
        exc_info=None,
    )

    payload = json.loads(SafeJsonFormatter().format(record))

    assert payload["message"] == "technical_event"
    assert set(payload) == {"timestamp", "level", "logger", "message"}


def test_no_executable_setting_mentions_sqlite() -> None:
    settings_directory = Path(__file__).resolve().parents[1] / "src" / "claridez" / "settings"

    for path in settings_directory.glob("*.py"):
        assert "sqlite" not in path.read_text(encoding="utf-8").lower(), path.name
