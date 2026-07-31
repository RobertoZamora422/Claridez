"""Configuración aislada que apunta solo a la base desechable del spike."""

from typing import Any

from pydantic import SecretStr

from claridez.settings.base import *  # noqa: F403
from claridez.settings.base import build_database_configuration, build_logging_configuration
from claridez.settings.environment import (
    BootstrapSettings,
    load_bootstrap_settings,
    load_runtime_settings,
)
from spikes.tenancy import SPIKE_DATABASE_NAME

_bootstrap = load_bootstrap_settings()
_runtime = load_runtime_settings()

SECRET_KEY = _runtime.secret_key.get_secret_value()
DEBUG = False
ALLOWED_HOSTS = ["testserver"]
INSTALLED_APPS = [*INSTALLED_APPS, "spikes.tenancy"]  # noqa: F405


def _database(
    *, user: str, password: SecretStr, max_age: int, bootstrap: BootstrapSettings
) -> dict[str, Any]:
    configuration = build_database_configuration(
        name=SPIKE_DATABASE_NAME,
        user=user,
        password=password,
        host=bootstrap.db_host,
        port=bootstrap.db_port,
        connect_timeout=bootstrap.db_connect_timeout,
        statement_timeout_ms=bootstrap.db_statement_timeout_ms,
        sslmode=bootstrap.db_sslmode,
    )["default"]
    configuration["CONN_MAX_AGE"] = max_age
    return configuration


DATABASES = {
    "default": _database(
        user=_bootstrap.db_user,
        password=_bootstrap.db_password,
        max_age=0,
        bootstrap=_bootstrap,
    ),
    "persistent": _database(
        user=_bootstrap.db_user,
        password=_bootstrap.db_password,
        max_age=60,
        bootstrap=_bootstrap,
    ),
    "migrator": _database(
        user=_bootstrap.migration_db_user,
        password=_bootstrap.migration_db_password,
        max_age=0,
        bootstrap=_bootstrap,
    ),
    "test_runner": _database(
        user=_bootstrap.test_db_user,
        password=_bootstrap.test_db_password,
        max_age=0,
        bootstrap=_bootstrap,
    ),
}

LOGGING = build_logging_configuration("WARNING")

del _bootstrap
del _runtime
