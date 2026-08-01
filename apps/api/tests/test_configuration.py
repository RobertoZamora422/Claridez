"""Pruebas de validación, perfiles y configuración local."""

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from claridez.logging import SafeJsonFormatter
from claridez.organizations.management.commands.api_run import Command as ApiRunCommand
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


def test_identity_and_organizations_are_registered_without_django_admin() -> None:
    assert settings.AUTH_USER_MODEL == "identity.User"
    assert "claridez.identity.apps.IdentityConfig" in settings.INSTALLED_APPS
    assert "claridez.organizations.apps.OrganizationsConfig" in settings.INSTALLED_APPS
    assert "django.contrib.auth" in settings.INSTALLED_APPS
    assert "django.contrib.contenttypes" in settings.INSTALLED_APPS
    assert "django.contrib.sessions" in settings.INSTALLED_APPS
    assert "axes" in settings.INSTALLED_APPS
    assert "django.contrib.admin" not in settings.INSTALLED_APPS


def test_authentication_middleware_order_and_axes_backend_are_explicit() -> None:
    assert settings.MIDDLEWARE.index("django.contrib.sessions.middleware.SessionMiddleware") < (
        settings.MIDDLEWARE.index("django.middleware.csrf.CsrfViewMiddleware")
    )
    assert settings.MIDDLEWARE.index("django.middleware.csrf.CsrfViewMiddleware") < (
        settings.MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware")
    )
    assert settings.MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware") < (
        settings.MIDDLEWARE.index("claridez.identity.middleware.AbsoluteSessionExpiryMiddleware")
    )
    assert settings.MIDDLEWARE[-1] == "axes.middleware.AxesMiddleware"
    assert settings.AUTHENTICATION_BACKENDS == [
        "axes.backends.AxesStandaloneBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]


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


def test_local_api_command_does_not_require_migration_recorder_access() -> None:
    command = ApiRunCommand()

    command.check_migrations()
