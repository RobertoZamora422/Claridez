"""Configuración de la aplicación de identidad."""

from django.apps import AppConfig


class IdentityConfig(AppConfig):
    """Registrar el usuario local productivo."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "claridez.identity"
    label = "identity"
    verbose_name = "Identidad"
