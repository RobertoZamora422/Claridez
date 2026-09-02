"""Configuración de pruebas con PostgreSQL real y rol local dedicado."""

from .base import *  # noqa: F403
from .base import build_database_configuration, build_logging_configuration
from .environment import load_test_settings

_local = load_test_settings()

SECRET_KEY = _local.secret_key.get_secret_value()
DEBUG = False
ALLOWED_HOSTS = ["testserver"]
DATABASES = build_database_configuration(
    name=_local.postgres_admin_db,
    user=_local.test_db_user,
    password=_local.test_db_password,
    host=_local.db_host,
    port=_local.db_port,
    connect_timeout=_local.db_connect_timeout,
    statement_timeout_ms=_local.db_statement_timeout_ms,
    sslmode=_local.db_sslmode,
    test_name=_local.test_db_name,
)
LOGGING = build_logging_configuration("WARNING")
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
PORTAL_EXPOSE_TEST_CHALLENGE_CODE = True

del _local
