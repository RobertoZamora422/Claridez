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
    PERSON_READ = "person:read"
    PERSON_MANAGE = "person:manage"
    PERSON_MERGE = "person:merge"
    SALES_READ = "sales:read"
    SALES_MANAGE = "sales:manage"
    INTERACTION_READ = "interaction:read"
    INTERACTION_RECORD = "interaction:record"
    TASK_MANAGE = "task:manage"
    CONSENT_READ = "consent:read"
    CONSENT_MANAGE = "consent:manage"
    AVAILABILITY_READ = "availability:read"
    RESERVATION_CONFIRM = "reservation:confirm"
    RESERVATION_CANCEL = "reservation:cancel"
    RESERVATION_WAIVE_DEPOSIT = "reservation:waive_deposit"
    RESERVATION_RESCHEDULE = "reservation:reschedule"
    SCHEDULE_BLOCK = "schedule:block"
    SCHEDULE_EXPORT = "schedule:export"
    OPERATION_READ = "operation:read"
    OPERATION_MANAGE = "operation:manage"
    OPERATION_EXECUTE = "operation:execute"
    BUSINESS_CONFIGURATION_READ = "business_configuration:read"
    BUSINESS_CONFIGURATION_MANAGE = "business_configuration:manage"
    VENUE_READ = "venue:read"
    VENUE_MANAGE = "venue:manage"
    CATALOG_READ = "catalog:read"
    CATALOG_PRICE_READ = "catalog_price:read"
    CATALOG_MANAGE = "catalog:manage"
    CATALOG_PRICE_MANAGE = "catalog_price:manage"
    DOCUMENT_TEMPLATE_READ = "document_template:read"
    DOCUMENT_TEMPLATE_MANAGE = "document_template:manage"
    CONTRACTUAL_RECORD_READ = "contractual_record:read"
    CONTRACTUAL_INSTRUMENT_ISSUE = "contractual_instrument:issue"
    DOCUMENT_ARTIFACT_DOWNLOAD = "document_artifact:download"
    DOCUMENT_EXTERNAL_FILE_MANAGE = "document_external_file:manage"
    DOCUMENT_EXTERNAL_ACCESS_MANAGE = "document_external_access:manage"
    DOCUMENT_RETENTION_READ = "document_retention:read"
    DOCUMENT_RETENTION_MANAGE = "document_retention:manage"
    RECEIVABLES_READ = "receivables:read"
    RECEIVABLES_READ_SUMMARY = "receivables:read_summary"
    RECEIVABLES_MANAGE_SCHEDULE = "receivables:manage_schedule"
    RECEIVABLES_RECORD_PAYMENT = "receivables:record_payment"
    RECEIVABLES_APPLY_PAYMENT = "receivables:apply_payment"
    RECEIVABLES_RECORD_ADJUSTMENT = "receivables:record_adjustment"
    RECEIVABLES_REVERSE_MOVEMENT = "receivables:reverse_movement"
    RECEIVABLES_RECORD_REFUND = "receivables:record_refund"
    RECEIVABLES_ISSUE_RECEIPT = "receivables:issue_receipt"
    FINANCE_READ = "finance:read"
    FINANCE_MANAGE_CATEGORIES = "finance:manage_categories"
    FINANCE_PLAN_COSTS = "finance:plan_costs"
    FINANCE_RECORD_ACTUALS = "finance:record_actuals"
    FINANCE_SUBMIT_EVIDENCE = "finance:submit_evidence"
    FINANCE_ALLOCATE_EXPENSES = "finance:allocate_expenses"
    FINANCE_MANAGE_RECURRING = "finance:manage_recurring"
    FINANCE_RECORD_CASH = "finance:record_cash"
    FINANCE_MANAGE_BUDGETS = "finance:manage_budgets"
    FINANCE_ADJUST_RECOGNITION = "finance:adjust_recognition"
    FINANCE_CLOSE_PERIOD = "finance:close_period"
    FINANCE_EXPORT = "finance:export"


ROLE_CAPABILITIES: Final = MappingProxyType(
    {
        Membership.Role.OWNER: frozenset(
            {
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
                Capability.RECEIVABLES_READ,
                Capability.RECEIVABLES_READ_SUMMARY,
                Capability.RECEIVABLES_MANAGE_SCHEDULE,
                Capability.RECEIVABLES_RECORD_PAYMENT,
                Capability.RECEIVABLES_APPLY_PAYMENT,
                Capability.RECEIVABLES_RECORD_ADJUSTMENT,
                Capability.RECEIVABLES_REVERSE_MOVEMENT,
                Capability.RECEIVABLES_RECORD_REFUND,
                Capability.RECEIVABLES_ISSUE_RECEIPT,
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
        ),
        Membership.Role.ADMINISTRATOR: frozenset(
            {
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
                Capability.RECEIVABLES_READ,
                Capability.RECEIVABLES_READ_SUMMARY,
                Capability.RECEIVABLES_MANAGE_SCHEDULE,
                Capability.RECEIVABLES_RECORD_PAYMENT,
                Capability.RECEIVABLES_APPLY_PAYMENT,
                Capability.RECEIVABLES_RECORD_ADJUSTMENT,
                Capability.RECEIVABLES_REVERSE_MOVEMENT,
                Capability.RECEIVABLES_RECORD_REFUND,
                Capability.RECEIVABLES_ISSUE_RECEIPT,
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
        ),
        Membership.Role.COMMERCIAL: frozenset(
            {
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
                Capability.RECEIVABLES_READ_SUMMARY,
            }
        ),
        Membership.Role.OPERATIONS: frozenset(
            {
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
                Capability.FINANCE_SUBMIT_EVIDENCE,
            }
        ),
        Membership.Role.FINANCE: frozenset(
            {
                Capability.ORGANIZATION_ACCESS,
                Capability.ORGANIZATION_SETTINGS_READ,
                Capability.SALES_READ,
                Capability.AVAILABILITY_READ,
                Capability.RESERVATION_CONFIRM,
                Capability.BUSINESS_CONFIGURATION_READ,
                Capability.VENUE_READ,
                Capability.CATALOG_READ,
                Capability.CATALOG_PRICE_READ,
                Capability.RECEIVABLES_READ,
                Capability.RECEIVABLES_READ_SUMMARY,
                Capability.RECEIVABLES_MANAGE_SCHEDULE,
                Capability.RECEIVABLES_RECORD_PAYMENT,
                Capability.RECEIVABLES_APPLY_PAYMENT,
                Capability.RECEIVABLES_RECORD_ADJUSTMENT,
                Capability.RECEIVABLES_REVERSE_MOVEMENT,
                Capability.RECEIVABLES_RECORD_REFUND,
                Capability.RECEIVABLES_ISSUE_RECEIPT,
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
