"""Configuración común mínima de Django para la Iteración 1."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]

SECRET_KEY = ""
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "rest_framework",
    "drf_spectacular",
]
MIDDLEWARE: list[str] = []
ROOT_URLCONF = "claridez.urls"
TEMPLATES: list[dict[str, object]] = []
WSGI_APPLICATION = "claridez.wsgi.application"
ASGI_APPLICATION = "claridez.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("CLARIDEZ_DB_NAME", "claridez"),
        "USER": os.environ.get("CLARIDEZ_DB_USER", "claridez"),
        "PASSWORD": os.environ.get("CLARIDEZ_DB_PASSWORD", ""),
        "HOST": os.environ.get("CLARIDEZ_DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("CLARIDEZ_DB_PORT", "5432"),
        "CONN_MAX_AGE": 0,
    }
}

LANGUAGE_CODE = "es-ec"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Claridez API",
    "DESCRIPTION": "Esquema técnico inicial sin endpoints funcionales.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
