"""Configuración de ejecución local con el rol limitado de aplicación."""

from .base import *  # noqa: F403
from .base import build_database_configuration, build_logging_configuration
from .environment import load_runtime_settings

_local = load_runtime_settings()

SECRET_KEY = _local.secret_key.get_secret_value()
DEBUG = True
ALLOWED_HOSTS = _local.allowed_hosts_list()
DATABASES = build_database_configuration(
    name=_local.db_name,
    user=_local.db_user,
    password=_local.db_password,
    host=_local.db_host,
    port=_local.db_port,
    connect_timeout=_local.db_connect_timeout,
    statement_timeout_ms=_local.db_statement_timeout_ms,
    sslmode=_local.db_sslmode,
)
LOGGING = build_logging_configuration(_local.log_level)

del _local
