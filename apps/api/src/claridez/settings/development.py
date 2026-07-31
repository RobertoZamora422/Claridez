"""Configuración local provisional hasta la plataforma reproducible de la Iteración 2."""

import os

from .base import *  # noqa: F403

SECRET_KEY = os.environ["CLARIDEZ_SECRET_KEY"]
DEBUG = True
