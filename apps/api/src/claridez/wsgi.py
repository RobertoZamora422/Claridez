"""Punto de entrada WSGI técnico de Claridez."""

import os

from django.core.handlers.wsgi import WSGIHandler
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "claridez.settings.development")

application: WSGIHandler = get_wsgi_application()
