"""Managers tenant-aware candidatos, limitados al código experimental."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import models

from .context import current_organization_id


class TenantQuerySet(models.QuerySet[Any]):
    """QuerySet con filtro organizacional explícito."""

    def for_organization(self, organization_id: UUID) -> TenantQuerySet:
        return self.filter(organization_id=organization_id)


class TenantManager(models.Manager[Any]):
    """Manager fail-closed que usa el ContextVar del scope soportado."""

    def get_queryset(self) -> TenantQuerySet:
        queryset = TenantQuerySet(self.model, using=self._db)
        organization_id = current_organization_id()
        if organization_id is None:
            return queryset.none()
        return queryset.for_organization(organization_id)

    def for_organization(self, organization_id: UUID) -> TenantQuerySet:
        return TenantQuerySet(self.model, using=self._db).for_organization(organization_id)
