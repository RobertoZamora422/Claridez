"""Worker canónico privado de Analytics con el rol limitado claridez_app."""

from .base import *  # noqa: F403
from .base import build_database_configuration, build_logging_configuration
from .environment import load_analytics_worker_settings

_worker = load_analytics_worker_settings()
SECRET_KEY = _worker.secret_key.get_secret_value()
DEBUG = False
ALLOWED_HOSTS = []
DATABASES = build_database_configuration(
    name=_worker.db_name,
    user=_worker.db_user,
    password=_worker.db_password,
    host=_worker.db_host,
    port=_worker.db_port,
    connect_timeout=_worker.db_connect_timeout,
    statement_timeout_ms=_worker.db_statement_timeout_ms,
    sslmode=_worker.db_sslmode,
)
LOGGING = build_logging_configuration(_worker.log_level)
del _worker
