"""Política central de propósito y procedencia para Communications P14."""

from __future__ import annotations

from dataclasses import dataclass

from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.tenant_scope import TenantAuthorization

from .errors import invalid, unavailable
from .models import Purpose


@dataclass(frozen=True, slots=True)
class CommunicationSourceRule:
    purpose: str
    aggregate_type: str
    capability: Capability


_PURPOSES_BY_ROLE = {
    "owner": frozenset(
        {
            Purpose.PORTAL_AUTHENTICATION,
            Purpose.CAPTURE_ACKNOWLEDGEMENT,
            Purpose.SERVICE_UPDATE,
            Purpose.EVENT_REMINDER,
            Purpose.PAYMENT_REMINDER,
            Purpose.DOCUMENT_REMINDER,
            Purpose.CLIENT_ACTION,
        }
    ),
    "administrator": frozenset(
        {
            Purpose.PORTAL_AUTHENTICATION,
            Purpose.CAPTURE_ACKNOWLEDGEMENT,
            Purpose.SERVICE_UPDATE,
            Purpose.EVENT_REMINDER,
            Purpose.PAYMENT_REMINDER,
            Purpose.DOCUMENT_REMINDER,
            Purpose.CLIENT_ACTION,
        }
    ),
    "commercial": frozenset(
        {
            Purpose.CAPTURE_ACKNOWLEDGEMENT,
            Purpose.SERVICE_UPDATE,
            Purpose.CLIENT_ACTION,
        }
    ),
    "operations": frozenset(
        {
            Purpose.EVENT_REMINDER,
            Purpose.SERVICE_UPDATE,
            Purpose.CLIENT_ACTION,
        }
    ),
    "finance": frozenset({Purpose.PAYMENT_REMINDER, Purpose.SERVICE_UPDATE}),
}

_SOURCE_RULES = (
    CommunicationSourceRule(
        Purpose.PORTAL_AUTHENTICATION,
        "portal_challenge",
        Capability.PORTAL_GRANT_ISSUE,
    ),
    CommunicationSourceRule(
        Purpose.CAPTURE_ACKNOWLEDGEMENT,
        "event_request",
        Capability.SALES_MANAGE,
    ),
    CommunicationSourceRule(
        Purpose.SERVICE_UPDATE,
        "event_request",
        Capability.SALES_MANAGE,
    ),
    CommunicationSourceRule(
        Purpose.CLIENT_ACTION,
        "event_request",
        Capability.SALES_MANAGE,
    ),
    CommunicationSourceRule(
        Purpose.EVENT_REMINDER,
        "scheduling_reservation",
        Capability.OPERATION_MANAGE,
    ),
    CommunicationSourceRule(
        Purpose.PAYMENT_REMINDER,
        "receivable_obligation",
        Capability.RECEIVABLES_MANAGE_SCHEDULE,
    ),
    CommunicationSourceRule(
        Purpose.DOCUMENT_REMINDER,
        "issued_instrument_version",
        Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE,
    ),
)


def manageable_purposes(authorization: TenantAuthorization) -> frozenset[str]:
    """Devuelve el ámbito semántico explícito del perfil, sin jerarquías."""
    return _PURPOSES_BY_ROLE.get(authorization.role, frozenset())


def require_manageable_purpose(
    authorization: TenantAuthorization,
    purpose: str,
    *,
    opaque_resource: str | None = None,
) -> None:
    if purpose == Purpose.MARKETING or purpose not in manageable_purposes(authorization):
        if opaque_resource is not None:
            raise unavailable(opaque_resource)
        raise invalid("El propósito no corresponde al ámbito del perfil.")


def source_rule(
    authorization: TenantAuthorization,
    *,
    purpose: str,
    aggregate_type: str,
    opaque_resource: str | None = None,
) -> CommunicationSourceRule:
    require_manageable_purpose(authorization, purpose, opaque_resource=opaque_resource)
    rule = next(
        (
            candidate
            for candidate in _SOURCE_RULES
            if candidate.purpose == purpose and candidate.aggregate_type == aggregate_type
        ),
        None,
    )
    if rule is None:
        if opaque_resource is not None:
            raise unavailable(opaque_resource)
        raise invalid("La procedencia de la comunicación no está autorizada.")
    try:
        authorization.require(rule.capability)
    except AuthorizationDenied:
        if opaque_resource is not None:
            raise unavailable(opaque_resource) from None
        raise
    return rule


def manageable_source_rules(
    authorization: TenantAuthorization,
) -> tuple[CommunicationSourceRule, ...]:
    role_capabilities = capabilities_for_role(authorization.role)
    purposes = manageable_purposes(authorization)
    return tuple(
        rule
        for rule in _SOURCE_RULES
        if rule.purpose in purposes and rule.capability in role_capabilities
    )


__all__ = (
    "CommunicationSourceRule",
    "manageable_purposes",
    "manageable_source_rules",
    "require_manageable_purpose",
    "source_rule",
)
