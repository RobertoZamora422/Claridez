"""Scope transaccional experimental para un tenant previamente validado."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from django.db import connections, transaction

ORGANIZATION_GUC = "claridez.organization_id"
_current_organization: ContextVar[UUID | None] = ContextVar(
    "claridez_spike_organization", default=None
)


class TenantScopeError(RuntimeError):
    """El scope solicitado contradice el contexto ya validado."""


class TenantContextRequired(RuntimeError):
    """Una operación tenant-aware se intentó sin contexto validado."""


@dataclass(frozen=True, slots=True)
class ValidatedTechnicalOrganization:
    """Representa una autorización previa que el spike no implementa."""

    id: UUID


def current_organization_id() -> UUID | None:
    """Obtener el tenant del flujo Python actual, sin consultar PostgreSQL."""
    return _current_organization.get()


def require_current_organization_id() -> UUID:
    """Fallar antes de escribir cuando la aplicación no validó un tenant."""
    organization_id = current_organization_id()
    if organization_id is None:
        raise TenantContextRequired("La operación requiere un contexto organizacional validado.")
    return organization_id


@contextmanager
def tenant_scope(
    organization: ValidatedTechnicalOrganization,
    *,
    using: str = "default",
) -> Iterator[None]:
    """Aplicar un GUC local dentro de una transacción atómica exterior."""
    existing = current_organization_id()
    if existing is not None:
        if existing != organization.id:
            raise TenantScopeError("No se permite cambiar de tenant dentro de un scope activo.")
        yield
        return

    with transaction.atomic(using=using):
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT set_config(%s, %s, true)",
                (ORGANIZATION_GUC, str(organization.id)),
            )
        token = _current_organization.set(organization.id)
        try:
            yield
        finally:
            _current_organization.reset(token)
