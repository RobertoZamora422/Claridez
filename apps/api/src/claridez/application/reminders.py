"""Coordinación neutral de recordatorios decididos por sus dominios propietarios."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from claridez.commercial.public import client_event_request
from claridez.communications.authorization import source_rule
from claridez.communications.models import Purpose
from claridez.communications.public import cancel_intent, request_intent
from claridez.documents.public import document_reminder_decision
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.receivables.public import payment_reminder_decision
from claridez.scheduling.public import contractual_schedule, event_reminder_decision


class ReminderKind(StrEnum):
    EVENT = "event"
    PAYMENT = "payment"
    DOCUMENT = "document"


_PURPOSE = {
    ReminderKind.EVENT: Purpose.EVENT_REMINDER,
    ReminderKind.PAYMENT: Purpose.PAYMENT_REMINDER,
    ReminderKind.DOCUMENT: Purpose.DOCUMENT_REMINDER,
}
_CAPABILITY = {
    ReminderKind.EVENT: Capability.OPERATION_MANAGE,
    ReminderKind.PAYMENT: Capability.RECEIVABLES_MANAGE_SCHEDULE,
    ReminderKind.DOCUMENT: Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE,
}
_AGGREGATE_TYPE = {
    ReminderKind.EVENT: "scheduling_reservation",
    ReminderKind.PAYMENT: "receivable_obligation",
    ReminderKind.DOCUMENT: "issued_instrument_version",
}


def request_reminder(
    actor: User,
    organization_id: UUID,
    *,
    kind: str,
    source_id: UUID,
    channel: str,
    template_version_id: UUID,
    variables: dict[str, object],
    idempotency_key: str,
    not_before: datetime,
) -> dict[str, object]:
    reminder_kind = ReminderKind(kind)
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_INTENT_REQUEST
    ) as authorization:
        authorization.require(_CAPABILITY[reminder_kind])
        source_rule(
            authorization,
            purpose=_PURPOSE[reminder_kind],
            aggregate_type=_AGGREGATE_TYPE[reminder_kind],
        )
        if reminder_kind == ReminderKind.EVENT:
            decision = event_reminder_decision(authorization, source_id)
            event_request_id = decision.event_request_id
            aggregate_type = "scheduling_reservation"
            aggregate_id = decision.current_reservation_id
            source_version = decision.source_version
            causal_key = f"event-reminder:{decision.root_reservation_id}"
        elif reminder_kind == ReminderKind.PAYMENT:
            payment = payment_reminder_decision(authorization, source_id)
            event_request_id = payment.event_request_id
            aggregate_type = "receivable_obligation"
            aggregate_id = payment.obligation_id
            source_version = payment.source_version
            causal_key = f"payment-reminder:{payment.obligation_id}"
        else:
            document = document_reminder_decision(authorization, source_id)
            schedule = contractual_schedule(authorization, document.root_reservation_id)
            event_request_id = schedule.event_request_id
            aggregate_type = "issued_instrument_version"
            aggregate_id = document.issued_version_id
            source_version = document.source_version
            causal_key = f"document-reminder:{document.instrument_id}"
        event = client_event_request(authorization.organization_id, event_request_id)
        intent = request_intent(
            authorization.organization_id,
            purpose=_PURPOSE[reminder_kind],
            channel=channel,
            person_id=event.person_id,
            template_version_id=template_version_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            variables=variables,
            idempotency_key=idempotency_key,
            requested_by_membership_id=authorization.membership_id,
            source_version=source_version,
            causal_key=causal_key,
            causal_sequence=source_version,
            not_before=not_before,
        )
        return {
            "id": intent.pk,
            "state": intent.state,
            "purpose": intent.purpose,
            "source_version": intent.source_version,
        }


def cancel_reminder(
    actor: User,
    organization_id: UUID,
    *,
    kind: str,
    intent_id: UUID,
    source_version: int,
    reason: str,
) -> bool:
    reminder_kind = ReminderKind(kind)
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_INTENT_REQUEST
    ) as authorization:
        authorization.require(_CAPABILITY[reminder_kind])
        source_rule(
            authorization,
            purpose=_PURPOSE[reminder_kind],
            aggregate_type=_AGGREGATE_TYPE[reminder_kind],
        )
        return cancel_intent(
            authorization.organization_id,
            intent_id=intent_id,
            source_version=source_version,
            expected_purpose=_PURPOSE[reminder_kind],
            reason=reason,
            actor_membership_id=authorization.membership_id,
        )
