"""Configuración local exclusiva para migraciones de Django."""

from .base import *  # noqa: F403
from .base import build_database_configuration, build_logging_configuration
from .environment import load_migration_settings

_local = load_migration_settings()

SECRET_KEY = _local.secret_key.get_secret_value()
DEBUG = False
ALLOWED_HOSTS = []
DATABASES = build_database_configuration(
    name=_local.db_name,
    user=_local.migration_db_user,
    password=_local.migration_db_password,
    host=_local.db_host,
    port=_local.db_port,
    connect_timeout=_local.db_connect_timeout,
    statement_timeout_ms=_local.db_statement_timeout_ms,
    sslmode=_local.db_sslmode,
)
LOGGING = build_logging_configuration("INFO")

del _local
