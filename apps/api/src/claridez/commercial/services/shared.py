from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from django.utils import timezone

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from ..errors import invalid, unavailable
from ..models import ContactOrigin

COMMERCIAL_CAPABILITIES = frozenset(
    {
        Capability.PERSON_READ,
        Capability.PERSON_MANAGE,
        Capability.SALES_READ,
        Capability.SALES_MANAGE,
        Capability.AVAILABILITY_READ,
        Capability.RESERVATION_CONFIRM,
        Capability.RESERVATION_CANCEL,
        Capability.RESERVATION_WAIVE_DEPOSIT,
    }
)


def _uuid(value: UUID | str, resource: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise unavailable(resource) from None


def _aware(value: datetime, field: str) -> datetime:
    if timezone.is_naive(value):
        raise invalid(f"{field} debe incluir zona horaria.")
    return value.astimezone(UTC)


def _origin(value: str) -> str:
    try:
        return ContactOrigin(value)
    except ValueError:
        raise invalid("El origen no es válido.") from None


def _can(authorization: TenantAuthorization, capability: Capability) -> bool:
    return capability in capabilities_for_role(authorization.role)


def _validate_interval(starts_at: datetime, ends_at: datetime) -> tuple[datetime, datetime]:
    start = _aware(starts_at, "La hora inicial")
    end = _aware(ends_at, "La hora final")
    if start >= end:
        raise invalid("La hora final debe ser posterior a la inicial.")
    return start, end


def commercial_capabilities(actor: User, organization_reference: UUID | str) -> tuple[str, ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.ORGANIZATION_ACCESS
    ) as authorization:
        available = capabilities_for_role(authorization.role) & COMMERCIAL_CAPABILITIES
        return tuple(sorted(capability.value for capability in available))
