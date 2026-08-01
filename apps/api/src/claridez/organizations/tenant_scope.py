"""Único límite autorizado para operaciones privadas organizacionales."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from django.db import connection, transaction

from claridez.identity.models import User

from ._tenant_context import (
    _restore_local_organization_context,
    _set_local_organization_context,
)
from .capabilities import Capability, canonical_capability, require_capability
from .exceptions import ConflictingTenantScope, TenantAccessDenied
from .models import Membership, Organization

_current_organization: ContextVar[UUID | None] = ContextVar(
    "claridez_current_organization",
    default=None,
)


@dataclass(frozen=True, slots=True)
class TenantAuthorization:
    """Valores escalares autorizados; no contiene relaciones ni objetos lazy."""

    actor_id: UUID
    organization_id: UUID
    membership_id: UUID
    role: Membership.Role
    capability: Capability

    def require(self, capability: Capability | str) -> Capability:
        return require_capability(self.role, capability)


def _organization_id(reference: Organization | UUID | str) -> UUID:
    raw_value = reference.pk if isinstance(reference, Organization) else reference
    try:
        return UUID(str(raw_value))
    except (TypeError, ValueError, AttributeError):
        raise TenantAccessDenied("La organización no está disponible.") from None


def _actor_id(actor: User) -> UUID:
    try:
        return UUID(str(actor.pk))
    except (TypeError, ValueError, AttributeError):
        raise TenantAccessDenied("La organización no está disponible.") from None


@contextmanager
def authorized_tenant_scope(
    actor: User,
    organization_reference: Organization | UUID | str,
    required_capability: Capability | str,
) -> Iterator[TenantAuthorization]:
    """Revalidar actor, tenant, membresía y capacidad dentro de una transacción."""
    organization_id = _organization_id(organization_reference)
    actor_id = _actor_id(actor)
    capability = canonical_capability(required_capability)
    active_organization = _current_organization.get()
    if active_organization is not None and active_organization != organization_id:
        raise ConflictingTenantScope("No se permite cambiar de organización dentro del scope.")

    with transaction.atomic():
        try:
            current_actor = User.objects.get(pk=actor_id)
        except User.DoesNotExist:
            raise TenantAccessDenied("La organización no está disponible.") from None
        if current_actor.status != User.Status.ACTIVE or not bool(current_actor.is_active):
            raise TenantAccessDenied("La organización no está disponible.")

        previous_context = _set_local_organization_context(str(organization_id))
        token = _current_organization.set(organization_id)
        try:
            try:
                organization = Organization.objects.get(
                    pk=organization_id,
                    status=Organization.Status.ACTIVE,
                )
                membership = Membership.objects.get(
                    organization=organization,
                    user=current_actor,
                    status=Membership.Status.ACTIVE,
                )
            except (Organization.DoesNotExist, Membership.DoesNotExist):
                raise TenantAccessDenied("La organización no está disponible.") from None

            require_capability(membership.role, capability)
            canonical_role = Membership.Role(membership.role)
            yield TenantAuthorization(
                actor_id=current_actor.pk,
                organization_id=organization.pk,
                membership_id=membership.pk,
                role=canonical_role,
                capability=capability,
            )
        finally:
            _current_organization.reset(token)
            if not connection.needs_rollback:
                _restore_local_organization_context(previous_context)
