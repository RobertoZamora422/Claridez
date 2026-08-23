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
    Membership.Role.OWNER: {
        Capability.ORGANIZATION_ACCESS,
        Capability.ORGANIZATION_SETTINGS_READ,
        Capability.ORGANIZATION_SETTINGS_UPDATE,
        Capability.MEMBERSHIP_READ,
        Capability.MEMBERSHIP_MANAGE_NON_OWNER,
        Capability.MEMBERSHIP_MANAGE_OWNER,
        Capability.MEMBERSHIP_REVOKE_SESSIONS,
        Capability.PERSON_READ,
        Capability.PERSON_MANAGE,
        Capability.PERSON_MERGE,
        Capability.SALES_READ,
        Capability.SALES_MANAGE,
        Capability.INTERACTION_READ,
        Capability.INTERACTION_RECORD,
        Capability.TASK_MANAGE,
        Capability.CONSENT_READ,
        Capability.CONSENT_MANAGE,
        Capability.AVAILABILITY_READ,
        Capability.RESERVATION_CONFIRM,
        Capability.RESERVATION_CANCEL,
        Capability.RESERVATION_WAIVE_DEPOSIT,
        Capability.RESERVATION_RESCHEDULE,
        Capability.SCHEDULE_BLOCK,
        Capability.SCHEDULE_EXPORT,
        Capability.OPERATION_READ,
        Capability.OPERATION_MANAGE,
        Capability.OPERATION_EXECUTE,
        Capability.BUSINESS_CONFIGURATION_READ,
        Capability.BUSINESS_CONFIGURATION_MANAGE,
        Capability.VENUE_READ,
        Capability.VENUE_MANAGE,
        Capability.CATALOG_READ,
        Capability.CATALOG_PRICE_READ,
        Capability.CATALOG_MANAGE,
        Capability.CATALOG_PRICE_MANAGE,
        Capability.DOCUMENT_TEMPLATE_READ,
        Capability.DOCUMENT_TEMPLATE_MANAGE,
        Capability.CONTRACTUAL_RECORD_READ,
        Capability.CONTRACTUAL_INSTRUMENT_ISSUE,
        Capability.DOCUMENT_ARTIFACT_DOWNLOAD,
        Capability.DOCUMENT_EXTERNAL_FILE_MANAGE,
        Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE,
        Capability.DOCUMENT_RETENTION_READ,
        Capability.DOCUMENT_RETENTION_MANAGE,
    },
    Membership.Role.ADMINISTRATOR: {
        Capability.ORGANIZATION_ACCESS,
        Capability.ORGANIZATION_SETTINGS_READ,
        Capability.ORGANIZATION_SETTINGS_UPDATE,
        Capability.MEMBERSHIP_READ,
        Capability.MEMBERSHIP_MANAGE_NON_OWNER,
        Capability.MEMBERSHIP_REVOKE_SESSIONS,
        Capability.PERSON_READ,
        Capability.PERSON_MANAGE,
        Capability.PERSON_MERGE,
        Capability.SALES_READ,
        Capability.SALES_MANAGE,
        Capability.INTERACTION_READ,
        Capability.INTERACTION_RECORD,
        Capability.TASK_MANAGE,
        Capability.CONSENT_READ,
        Capability.CONSENT_MANAGE,
        Capability.AVAILABILITY_READ,
        Capability.RESERVATION_CONFIRM,
        Capability.RESERVATION_CANCEL,
        Capability.RESERVATION_WAIVE_DEPOSIT,
        Capability.RESERVATION_RESCHEDULE,
        Capability.SCHEDULE_BLOCK,
        Capability.SCHEDULE_EXPORT,
        Capability.OPERATION_READ,
        Capability.OPERATION_MANAGE,
        Capability.OPERATION_EXECUTE,
        Capability.BUSINESS_CONFIGURATION_READ,
        Capability.BUSINESS_CONFIGURATION_MANAGE,
        Capability.VENUE_READ,
        Capability.VENUE_MANAGE,
        Capability.CATALOG_READ,
        Capability.CATALOG_PRICE_READ,
        Capability.CATALOG_MANAGE,
        Capability.CATALOG_PRICE_MANAGE,
        Capability.DOCUMENT_TEMPLATE_READ,
        Capability.DOCUMENT_TEMPLATE_MANAGE,
        Capability.CONTRACTUAL_RECORD_READ,
        Capability.CONTRACTUAL_INSTRUMENT_ISSUE,
        Capability.DOCUMENT_ARTIFACT_DOWNLOAD,
        Capability.DOCUMENT_EXTERNAL_FILE_MANAGE,
        Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE,
        Capability.DOCUMENT_RETENTION_READ,
        Capability.DOCUMENT_RETENTION_MANAGE,
    },
    Membership.Role.COMMERCIAL: {
        Capability.ORGANIZATION_ACCESS,
        Capability.ORGANIZATION_SETTINGS_READ,
        Capability.PERSON_READ,
        Capability.PERSON_MANAGE,
        Capability.SALES_READ,
        Capability.SALES_MANAGE,
        Capability.INTERACTION_READ,
        Capability.INTERACTION_RECORD,
        Capability.TASK_MANAGE,
        Capability.CONSENT_READ,
        Capability.CONSENT_MANAGE,
        Capability.AVAILABILITY_READ,
        Capability.RESERVATION_CONFIRM,
        Capability.RESERVATION_RESCHEDULE,
        Capability.SCHEDULE_EXPORT,
        Capability.OPERATION_READ,
        Capability.BUSINESS_CONFIGURATION_READ,
        Capability.VENUE_READ,
        Capability.CATALOG_READ,
        Capability.CATALOG_PRICE_READ,
        Capability.DOCUMENT_TEMPLATE_READ,
        Capability.CONTRACTUAL_RECORD_READ,
        Capability.CONTRACTUAL_INSTRUMENT_ISSUE,
        Capability.DOCUMENT_ARTIFACT_DOWNLOAD,
        Capability.DOCUMENT_EXTERNAL_FILE_MANAGE,
        Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE,
    },
    Membership.Role.OPERATIONS: {
        Capability.ORGANIZATION_ACCESS,
        Capability.ORGANIZATION_SETTINGS_READ,
        Capability.SALES_READ,
        Capability.AVAILABILITY_READ,
        Capability.SCHEDULE_BLOCK,
        Capability.SCHEDULE_EXPORT,
        Capability.OPERATION_READ,
        Capability.OPERATION_MANAGE,
        Capability.OPERATION_EXECUTE,
        Capability.BUSINESS_CONFIGURATION_READ,
        Capability.VENUE_READ,
        Capability.CATALOG_READ,
        Capability.CONTRACTUAL_RECORD_READ,
        Capability.DOCUMENT_ARTIFACT_DOWNLOAD,
    },
    Membership.Role.FINANCE: {
        Capability.ORGANIZATION_ACCESS,
        Capability.ORGANIZATION_SETTINGS_READ,
        Capability.SALES_READ,
        Capability.AVAILABILITY_READ,
        Capability.RESERVATION_CONFIRM,
        Capability.BUSINESS_CONFIGURATION_READ,
        Capability.VENUE_READ,
        Capability.CATALOG_READ,
        Capability.CATALOG_PRICE_READ,
    },
}

P10_CAPABILITIES = {
    Capability.RECEIVABLES_READ,
    Capability.RECEIVABLES_READ_SUMMARY,
    Capability.RECEIVABLES_MANAGE_SCHEDULE,
    Capability.RECEIVABLES_RECORD_PAYMENT,
    Capability.RECEIVABLES_APPLY_PAYMENT,
    Capability.RECEIVABLES_RECORD_ADJUSTMENT,
    Capability.RECEIVABLES_REVERSE_MOVEMENT,
    Capability.RECEIVABLES_RECORD_REFUND,
    Capability.RECEIVABLES_ISSUE_RECEIPT,
}
EXPECTED_MATRIX[Membership.Role.OWNER].update(P10_CAPABILITIES)
EXPECTED_MATRIX[Membership.Role.ADMINISTRATOR].update(P10_CAPABILITIES)
EXPECTED_MATRIX[Membership.Role.FINANCE].update(P10_CAPABILITIES)
EXPECTED_MATRIX[Membership.Role.COMMERCIAL].add(Capability.RECEIVABLES_READ_SUMMARY)

P11_CAPABILITIES = {
    Capability.FINANCE_READ,
    Capability.FINANCE_MANAGE_CATEGORIES,
    Capability.FINANCE_PLAN_COSTS,
    Capability.FINANCE_RECORD_ACTUALS,
    Capability.FINANCE_SUBMIT_EVIDENCE,
    Capability.FINANCE_ALLOCATE_EXPENSES,
    Capability.FINANCE_MANAGE_RECURRING,
    Capability.FINANCE_RECORD_CASH,
    Capability.FINANCE_MANAGE_BUDGETS,
    Capability.FINANCE_ADJUST_RECOGNITION,
    Capability.FINANCE_CLOSE_PERIOD,
    Capability.FINANCE_EXPORT,
}
EXPECTED_MATRIX[Membership.Role.OWNER].update(P11_CAPABILITIES)
EXPECTED_MATRIX[Membership.Role.ADMINISTRATOR].update(P11_CAPABILITIES)
EXPECTED_MATRIX[Membership.Role.FINANCE].update(P11_CAPABILITIES)
EXPECTED_MATRIX[Membership.Role.OPERATIONS].add(Capability.FINANCE_SUBMIT_EVIDENCE)

P12_OWNER_ADMIN = {
    Capability.RESOURCE_READ_AVAILABILITY,
    Capability.SUPPLIER_READ,
    Capability.SUPPLIER_MANAGE_PROFILE,
    Capability.SUPPLIER_LINK_CONTACT,
    Capability.SUPPLIER_MANAGE_TERMS,
    Capability.SUPPLIER_MANAGE_OFFERING,
    Capability.RESOURCE_READ,
    Capability.RESOURCE_MANAGE,
    Capability.RESOURCE_RESERVE,
    Capability.RESOURCE_MAINTAIN,
    Capability.INVENTORY_RECORD_MOVEMENT,
    Capability.PURCHASE_READ,
    Capability.PURCHASE_MANAGE,
    Capability.PURCHASE_RECEIVE,
    Capability.PURCHASE_MATERIALIZE_FINANCE,
}
EXPECTED_MATRIX[Membership.Role.OWNER].update(P12_OWNER_ADMIN)
EXPECTED_MATRIX[Membership.Role.ADMINISTRATOR].update(P12_OWNER_ADMIN)
EXPECTED_MATRIX[Membership.Role.COMMERCIAL].add(Capability.RESOURCE_READ_AVAILABILITY)
EXPECTED_MATRIX[Membership.Role.OPERATIONS].update(
    {
        Capability.RESOURCE_READ_AVAILABILITY,
        Capability.SUPPLIER_READ,
        Capability.SUPPLIER_MANAGE_PROFILE,
        Capability.SUPPLIER_LINK_CONTACT,
        Capability.SUPPLIER_MANAGE_OFFERING,
        Capability.RESOURCE_READ,
        Capability.RESOURCE_MANAGE,
        Capability.RESOURCE_RESERVE,
        Capability.RESOURCE_MAINTAIN,
        Capability.INVENTORY_RECORD_MOVEMENT,
        Capability.PURCHASE_READ,
        Capability.PURCHASE_RECEIVE,
    }
)
EXPECTED_MATRIX[Membership.Role.FINANCE].update(
    {
        Capability.RESOURCE_READ_AVAILABILITY,
        Capability.SUPPLIER_READ,
        Capability.SUPPLIER_LINK_CONTACT,
        Capability.SUPPLIER_MANAGE_TERMS,
        Capability.RESOURCE_READ,
        Capability.PURCHASE_READ,
        Capability.PURCHASE_MANAGE,
        Capability.PURCHASE_MATERIALIZE_FINANCE,
    }
)


def test_capability_catalog_is_exact_and_closed() -> None:
    assert {capability.value for capability in Capability} == {
        "organization:access",
        "organization_settings:read",
        "organization_settings:update",
        "membership:read",
        "membership:manage_non_owner",
        "membership:manage_owner",
        "membership:revoke_sessions",
        "person:read",
        "person:manage",
        "person:merge",
        "sales:read",
        "sales:manage",
        "interaction:read",
        "interaction:record",
        "task:manage",
        "consent:read",
        "consent:manage",
        "availability:read",
        "reservation:confirm",
        "reservation:cancel",
        "reservation:waive_deposit",
        "reservation:reschedule",
        "schedule:block",
        "schedule:export",
        "operation:read",
        "operation:manage",
        "operation:execute",
        "business_configuration:read",
        "business_configuration:manage",
        "venue:read",
        "venue:manage",
        "catalog:read",
        "catalog_price:read",
        "catalog:manage",
        "catalog_price:manage",
        "document_template:read",
        "document_template:manage",
        "contractual_record:read",
        "contractual_instrument:issue",
        "document_artifact:download",
        "document_external_file:manage",
        "document_external_access:manage",
        "document_retention:read",
        "document_retention:manage",
        "receivables:read",
        "receivables:read_summary",
        "receivables:manage_schedule",
        "receivables:record_payment",
        "receivables:apply_payment",
        "receivables:record_adjustment",
        "receivables:reverse_movement",
        "receivables:record_refund",
        "receivables:issue_receipt",
        "finance:read",
        "finance:manage_categories",
        "finance:plan_costs",
        "finance:record_actuals",
        "finance:submit_evidence",
        "finance:allocate_expenses",
        "finance:manage_recurring",
        "finance:record_cash",
        "finance:manage_budgets",
        "finance:adjust_recognition",
        "finance:close_period",
        "finance:export",
        "resource:read_availability",
        "supplier:read",
        "supplier:manage_profile",
        "supplier:link_contact",
        "supplier:manage_terms",
        "supplier:manage_offering",
        "resource:read",
        "resource:manage",
        "resource:reserve",
        "resource:maintain",
        "inventory:record_movement",
        "purchase:read",
        "purchase:manage",
        "purchase:receive",
        "purchase:materialize_finance",
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
