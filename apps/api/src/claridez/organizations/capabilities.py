"""Catálogo cerrado y matriz provisional de capacidades organizacionales."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .exceptions import AuthorizationDenied, UnknownCapability, UnknownMembershipRole
from .models import Membership


class Capability(StrEnum):
    ORGANIZATION_ACCESS = "organization:access"
    ORGANIZATION_SETTINGS_READ = "organization_settings:read"
    ORGANIZATION_SETTINGS_UPDATE = "organization_settings:update"
    MEMBERSHIP_READ = "membership:read"
    MEMBERSHIP_MANAGE_NON_OWNER = "membership:manage_non_owner"
    MEMBERSHIP_MANAGE_OWNER = "membership:manage_owner"
    MEMBERSHIP_REVOKE_SESSIONS = "membership:revoke_sessions"


ROLE_CAPABILITIES: Final = MappingProxyType(
    {
        Membership.Role.OWNER: frozenset(Capability),
        Membership.Role.ADMINISTRATOR: frozenset(
            {
                Capability.ORGANIZATION_ACCESS,
                Capability.ORGANIZATION_SETTINGS_READ,
                Capability.ORGANIZATION_SETTINGS_UPDATE,
                Capability.MEMBERSHIP_READ,
                Capability.MEMBERSHIP_MANAGE_NON_OWNER,
                Capability.MEMBERSHIP_REVOKE_SESSIONS,
            }
        ),
        Membership.Role.COMMERCIAL: frozenset(
            {
                Capability.ORGANIZATION_ACCESS,
                Capability.ORGANIZATION_SETTINGS_READ,
            }
        ),
        Membership.Role.OPERATIONS: frozenset(
            {
                Capability.ORGANIZATION_ACCESS,
                Capability.ORGANIZATION_SETTINGS_READ,
            }
        ),
        Membership.Role.FINANCE: frozenset(
            {
                Capability.ORGANIZATION_ACCESS,
                Capability.ORGANIZATION_SETTINGS_READ,
            }
        ),
    }
)


def canonical_capability(value: Capability | str) -> Capability:
    try:
        return Capability(value)
    except ValueError as error:
        raise UnknownCapability("Capacidad no reconocida.") from error


def capabilities_for_role(role: Membership.Role | str) -> frozenset[Capability]:
    try:
        canonical_role = Membership.Role(role)
    except ValueError as error:
        raise UnknownMembershipRole("Rol no reconocido.") from error
    try:
        return ROLE_CAPABILITIES[canonical_role]
    except KeyError as error:
        raise UnknownMembershipRole("Rol no reconocido.") from error


def require_capability(
    role: Membership.Role | str,
    capability: Capability | str,
) -> Capability:
    canonical = canonical_capability(capability)
    if canonical not in capabilities_for_role(role):
        raise AuthorizationDenied("La operación no está autorizada.")
    return canonical
