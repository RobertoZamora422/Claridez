"""Rutas soportadas de acceso tenant-aware para el experimento."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from .context import require_current_organization_id


class TenantObjectNotFound(LookupError):
    """Respuesta indistinguible para identificadores ajenos o inexistentes."""


def tenant_queryset[PrivateRecord: models.Model](
    model: type[PrivateRecord], *, using: str = "default"
) -> models.QuerySet[Any]:
    """Construir una consulta explícitamente limitada al tenant validado."""
    organization_id = require_current_organization_id()
    manager = model._default_manager
    return manager.using(using).filter(organization_id=organization_id)


def get_private_record[PrivateRecord: models.Model](
    model: type[PrivateRecord], record_id: object, *, using: str = "default"
) -> PrivateRecord:
    """Obtener un registro sin revelar si un UUID ajeno existe."""
    try:
        return cast(PrivateRecord, tenant_queryset(model, using=using).get(id=record_id))
    except ObjectDoesNotExist:
        raise TenantObjectNotFound("El registro no existe en el contexto activo.") from None


def create_private_record[PrivateRecord: models.Model](
    model: type[PrivateRecord], *, using: str = "default", **values: object
) -> PrivateRecord:
    """Forzar organization_id desde el contexto y no desde el llamador."""
    values["organization_id"] = require_current_organization_id()
    manager = model._default_manager
    return manager.using(using).create(**values)


def bulk_create_private_records[PrivateRecord: models.Model](
    model: type[PrivateRecord],
    rows: Iterable[dict[str, object]],
    *,
    using: str = "default",
) -> list[PrivateRecord]:
    """Aplicar el tenant validado a todas las filas de una operación masiva."""
    organization_id = require_current_organization_id()
    objects = [model(organization_id=organization_id, **row) for row in rows]
    manager = model._default_manager
    return manager.using(using).bulk_create(objects)


def bulk_update_payload[PrivateRecord: models.Model](
    model: type[PrivateRecord], *, payload: str, using: str = "default"
) -> int:
    """Actualizar solo filas visibles mediante el servicio soportado."""
    return tenant_queryset(model, using=using).update(payload=payload)
