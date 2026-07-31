"""Registro Django exclusivo del spike de tenancy."""

from django.apps import AppConfig


class TenancySpikeConfig(AppConfig):
    """Aplicación técnica que nunca debe cargarse en Claridez normal."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "spikes.tenancy"
    label = "tenancy_spike"
    verbose_name = "Spike técnico de tenancy"
