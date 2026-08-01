"""Catálogo cerrado y matriz provisional de capacidades."""

from __future__ import annotations

import pytest

from claridez.organizations.capabilities import (
    Capability,
    capabilities_for_role,
    require_capability,
)
from claridez.organizations.exceptions import (
    AuthorizationDenied,
    UnknownCapability,
    UnknownMembershipRole,
)
from claridez.organizations.models import Membership

EXPECTED_MATRIX = {
    Membership.Role.OWNER: set(Capability),
    Membership.Role.ADMINISTRATOR: {
        Capability.ORGANIZATION_ACCESS,
        Capability.ORGANIZATION_SETTINGS_READ,
        Capability.ORGANIZATION_SETTINGS_UPDATE,
        Capability.MEMBERSHIP_READ,
        Capability.MEMBERSHIP_MANAGE_NON_OWNER,
        Capability.MEMBERSHIP_REVOKE_SESSIONS,
    },
    Membership.Role.COMMERCIAL: {
        Capability.ORGANIZATION_ACCESS,
        Capability.ORGANIZATION_SETTINGS_READ,
    },
    Membership.Role.OPERATIONS: {
        Capability.ORGANIZATION_ACCESS,
        Capability.ORGANIZATION_SETTINGS_READ,
    },
    Membership.Role.FINANCE: {
        Capability.ORGANIZATION_ACCESS,
        Capability.ORGANIZATION_SETTINGS_READ,
    },
}


def test_capability_catalog_is_exact_and_closed() -> None:
    assert {capability.value for capability in Capability} == {
        "organization:access",
        "organization_settings:read",
        "organization_settings:update",
        "membership:read",
        "membership:manage_non_owner",
        "membership:manage_owner",
        "membership:revoke_sessions",
    }


@pytest.mark.parametrize(("role", "expected"), EXPECTED_MATRIX.items())
def test_complete_role_matrix(role: Membership.Role, expected: set[Capability]) -> None:
    assert capabilities_for_role(role) == frozenset(expected)
    for capability in Capability:
        if capability in expected:
            assert require_capability(role, capability) == capability
        else:
            with pytest.raises(AuthorizationDenied):
                require_capability(role, capability)


def test_unknown_capability_and_role_are_rejected_without_hierarchy() -> None:
    with pytest.raises(UnknownCapability):
        require_capability(Membership.Role.OWNER, "future:unknown")
    with pytest.raises(UnknownMembershipRole):
        capabilities_for_role("future-role")
    with pytest.raises(AuthorizationDenied):
        require_capability(
            Membership.Role.ADMINISTRATOR,
            Capability.MEMBERSHIP_MANAGE_OWNER,
        )
