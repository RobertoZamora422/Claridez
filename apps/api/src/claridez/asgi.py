"""Punto de entrada ASGI técnico de Claridez."""

import os

from django.core.asgi import get_asgi_application
from django.core.handlers.asgi import ASGIHandler

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "claridez.settings.development")

application: ASGIHandler = get_asgi_application()
