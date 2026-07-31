"""Configuración de la aplicación de organizaciones."""

from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "claridez.organizations"
    verbose_name = "Organizaciones"
