"""Configuración común de Django independiente de credenciales."""

from pathlib import Path
from typing import Any

from pydantic import SecretStr

BASE_DIR = Path(__file__).resolve().parents[3]

DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "claridez.identity.apps.IdentityConfig",
    "claridez.organizations.apps.OrganizationsConfig",
    "rest_framework",
    "drf_spectacular",
]
MIDDLEWARE: list[str] = []
ROOT_URLCONF = "claridez.urls"
TEMPLATES: list[dict[str, object]] = []
WSGI_APPLICATION = "claridez.wsgi.application"
ASGI_APPLICATION = "claridez.asgi.application"

LANGUAGE_CODE = "es-ec"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True

AUTH_USER_MODEL = "identity.User"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Claridez API",
    "DESCRIPTION": "Esquema técnico inicial sin endpoints funcionales.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}


def build_database_configuration(
    *,
    name: str,
    user: str,
    password: SecretStr,
    host: str,
    port: int,
    connect_timeout: int,
    statement_timeout_ms: int,
    sslmode: str,
    test_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Construir una conexión PostgreSQL sin alternativas silenciosas."""
    database: dict[str, Any] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": user,
        "PASSWORD": password.get_secret_value(),
        "HOST": host,
        "PORT": port,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "OPTIONS": {
            "connect_timeout": connect_timeout,
            "options": f"-c timezone=UTC -c statement_timeout={statement_timeout_ms}",
            "sslmode": sslmode,
        },
    }
    if test_name is not None:
        database["TEST"] = {"NAME": test_name}
    return {"default": database}


def build_logging_configuration(level: str) -> dict[str, Any]:
    """Enviar logs técnicos estructurados a la salida estándar."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": "claridez.logging.SafeJsonFormatter"}},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
            }
        },
        "loggers": {
            "django": {
                "handlers": ["console"],
                "level": level,
                "propagate": False,
            }
        },
        "root": {"handlers": ["console"], "level": level},
    }
