"""Entidades técnicas desechables; no definen el dominio de Claridez."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from django.db import models

from .managers import TenantManager


class TechnicalOrganization(models.Model):
    """Límite sintético de aislamiento, sin semántica productiva."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=40)

    class Meta:
        db_table = "claridez_spike_organization"

    def __str__(self) -> str:
        return "technical-organization"


class _TechnicalPrivateRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_id = models.UUIDField()
    external_key = models.CharField(max_length=80)
    payload = models.CharField(max_length=120)

    objects: ClassVar[TenantManager] = TenantManager()
    spike_unfiltered_objects: ClassVar[models.Manager[Any]] = models.Manager()  # noqa: DJ012

    class Meta:
        abstract = True


class ApplicationTechnicalRecord(_TechnicalPrivateRecord):
    """Registro protegido únicamente por la capa de aplicación."""

    class Meta:
        db_table = "claridez_spike_app_record"
        constraints = [
            models.UniqueConstraint(
                fields=("organization_id", "id"), name="spike_app_record_org_id_uniq"
            ),
            models.UniqueConstraint(
                fields=("organization_id", "external_key"),
                name="spike_app_record_org_key_uniq",
            ),
        ]

    def __str__(self) -> str:
        return "application-technical-record"


class ApplicationTechnicalChildRecord(_TechnicalPrivateRecord):
    """Hijo con parent_id explícito y FK compuesta creada por SQL."""

    parent_id = models.UUIDField()

    class Meta:
        db_table = "claridez_spike_app_child"
        constraints = [
            models.UniqueConstraint(
                fields=("organization_id", "external_key"),
                name="spike_app_child_org_key_uniq",
            )
        ]

    def __str__(self) -> str:
        return "application-technical-child"


class RlsTechnicalRecord(_TechnicalPrivateRecord):
    """Registro protegido por aplicación y RLS."""

    class Meta:
        db_table = "claridez_spike_rls_record"
        constraints = [
            models.UniqueConstraint(
                fields=("organization_id", "id"), name="spike_rls_record_org_id_uniq"
            ),
            models.UniqueConstraint(
                fields=("organization_id", "external_key"),
                name="spike_rls_record_org_key_uniq",
            ),
        ]

    def __str__(self) -> str:
        return "rls-technical-record"


class RlsTechnicalChildRecord(_TechnicalPrivateRecord):
    """Hijo RLS con integridad tenant-aware en PostgreSQL."""

    parent_id = models.UUIDField()

    class Meta:
        db_table = "claridez_spike_rls_child"
        constraints = [
            models.UniqueConstraint(
                fields=("organization_id", "external_key"),
                name="spike_rls_child_org_key_uniq",
            )
        ]

    def __str__(self) -> str:
        return "rls-technical-child"


class RlsDefaultDenyRecord(_TechnicalPrivateRecord):
    """Tabla RLS sin política para comprobar default-deny."""

    class Meta:
        db_table = "claridez_spike_rls_default_deny"

    def __str__(self) -> str:
        return "rls-default-deny-record"
