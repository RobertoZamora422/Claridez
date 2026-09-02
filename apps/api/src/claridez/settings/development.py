"""Configuración de ejecución local con el rol limitado de aplicación."""

from urllib.parse import urlsplit

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
AUTH_LINK_BASE_URL = _local.auth_link_base_url
PORTAL_CHALLENGE_TTL_SECONDS = _local.portal_challenge_ttl_seconds
PORTAL_SESSION_IDLE_TTL_SECONDS = _local.portal_session_idle_ttl_seconds
PORTAL_SESSION_ABSOLUTE_TTL_SECONDS = _local.portal_session_absolute_ttl_seconds
PORTAL_EPHEMERAL_LOCATOR_TTL_SECONDS = _local.portal_ephemeral_locator_ttl_seconds
COMMUNICATIONS_WORKER_LEASE_SECONDS = _local.communications_worker_lease_seconds
COMMUNICATIONS_WEBHOOK_REPLAY_SECONDS = _local.communications_webhook_replay_seconds
COMMUNICATIONS_PROVIDER = _local.communications_provider
PORTAL_EXPOSE_TEST_CHALLENGE_CODE = COMMUNICATIONS_PROVIDER == "deterministic"
COMMUNICATIONS_RESEND_API_KEY = _local.communications_resend_api_key.get_secret_value()
COMMUNICATIONS_RESEND_API_URL = _local.communications_resend_api_url
COMMUNICATIONS_WEBHOOK_SECRET = _local.communications_webhook_secret.get_secret_value()
PORTAL_ANTIABUSE_PROVIDER = _local.portal_antiabuse_provider
PORTAL_TURNSTILE_SECRET_KEY = _local.portal_turnstile_secret_key.get_secret_value()
PORTAL_TURNSTILE_SITE_KEY = _local.portal_turnstile_site_key
PORTAL_TURNSTILE_EXPECTED_HOSTNAMES = [
    item.strip() for item in _local.portal_turnstile_expected_hostnames.split(",") if item.strip()
]
_frontend_url = urlsplit(AUTH_LINK_BASE_URL)
CSRF_TRUSTED_ORIGINS = [f"{_frontend_url.scheme}://{_frontend_url.netloc}"]
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

del _frontend_url, _local
