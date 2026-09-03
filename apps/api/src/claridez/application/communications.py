"""Coordinación de procedencia autoritativa para Communications P14."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from claridez.commercial.errors import CommercialError
from claridez.commercial.public import client_event_request
from claridez.communications.authorization import source_rule
from claridez.communications.errors import unavailable
from claridez.communications.models import Purpose
from claridez.communications.services import (
    request_intent,
    retry_delivery_authorized,
    retryable_delivery,
)
from claridez.documents.public import DocumentsPortError, document_reminder_decision
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope
from claridez.people.errors import PeopleError
from claridez.people.public import canonical_person_id
from claridez.portal.errors import PortalError
from claridez.portal.public import portal_authentication_retry_decision
from claridez.receivables.public import (
    ReceivablesError,
    payment_reminder_decision_for_obligation,
)
from claridez.scheduling.public import (
    SchedulingError,
    contractual_schedule,
    event_reminder_decision_for_reservation,
)


def request_event_intent(
    actor: User,
    organization_id: UUID,
    *,
    purpose: str,
    channel: str,
    event_request_id: UUID,
    template_version_id: UUID,
    variables: dict[str, object],
    idempotency_key: str,
    not_before: datetime | None = None,
) -> dict[str, object]:
    """Único caso genérico aprobado: comunicación comercial sobre EventRequest real."""
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_INTENT_REQUEST
    ) as authorization:
        if purpose not in {Purpose.SERVICE_UPDATE, Purpose.CLIENT_ACTION}:
            raise unavailable("La procedencia de la comunicación")
        source_rule(
            authorization,
            purpose=purpose,
            aggregate_type="event_request",
        )
        try:
            event = client_event_request(authorization.organization_id, event_request_id)
        except CommercialError:
            raise unavailable("La procedencia de la comunicación") from None
        intent = request_intent(
            authorization.organization_id,
            purpose=purpose,
            channel=channel,
            person_id=event.person_id,
            template_version_id=template_version_id,
            aggregate_type="event_request",
            aggregate_id=event.id,
            variables=variables,
            idempotency_key=idempotency_key,
            requested_by_membership_id=authorization.membership_id,
            source_version=event.revision,
            not_before=not_before,
        )
        return {"id": intent.pk, "state": intent.state, "created_at": intent.created_at}


def _same_canonical_person(authorization: TenantAuthorization, first: UUID, second: UUID) -> bool:
    return canonical_person_id(authorization.organization_id, first) == canonical_person_id(
        authorization.organization_id, second
    )


def _validate_retry_source(authorization: TenantAuthorization, delivery: dict[str, object]) -> None:
    purpose = str(delivery["purpose"])
    aggregate_id = UUID(str(delivery["aggregate_id"]))
    person_id = UUID(str(delivery["person_id"]))
    source_version = int(str(delivery["source_version"]))
    try:
        if purpose in {
            Purpose.CAPTURE_ACKNOWLEDGEMENT,
            Purpose.SERVICE_UPDATE,
            Purpose.CLIENT_ACTION,
        }:
            event_decision = client_event_request(authorization.organization_id, aggregate_id)
            valid = event_decision.revision == source_version and _same_canonical_person(
                authorization, event_decision.person_id, person_id
            )
        elif purpose == Purpose.EVENT_REMINDER:
            schedule_decision = event_reminder_decision_for_reservation(authorization, aggregate_id)
            event = client_event_request(
                authorization.organization_id, schedule_decision.event_request_id
            )
            valid = schedule_decision.source_version == source_version and _same_canonical_person(
                authorization, event.person_id, person_id
            )
        elif purpose == Purpose.PAYMENT_REMINDER:
            payment_decision = payment_reminder_decision_for_obligation(authorization, aggregate_id)
            valid = payment_decision.source_version == source_version and _same_canonical_person(
                authorization, payment_decision.person_id, person_id
            )
        elif purpose == Purpose.DOCUMENT_REMINDER:
            document_decision = document_reminder_decision(authorization, aggregate_id)
            schedule = contractual_schedule(authorization, document_decision.root_reservation_id)
            event = client_event_request(authorization.organization_id, schedule.event_request_id)
            valid = document_decision.source_version == source_version and _same_canonical_person(
                authorization, event.person_id, person_id
            )
        elif purpose == Purpose.PORTAL_AUTHENTICATION:
            portal_decision = portal_authentication_retry_decision(
                authorization.organization_id, aggregate_id
            )
            valid = portal_decision.source_version == source_version and _same_canonical_person(
                authorization, portal_decision.person_id, person_id
            )
        else:
            valid = False
    except (
        AuthorizationDenied,
        CommercialError,
        DocumentsPortError,
        PeopleError,
        PortalError,
        ReceivablesError,
        SchedulingError,
    ):
        raise unavailable("La entrega") from None
    if not valid:
        raise unavailable("La entrega")


def retry_delivery(
    actor: User,
    organization_id: UUID,
    *,
    message_id: UUID,
    reason: str,
) -> None:
    """Revalida propósito, capability fuente y estado vivo antes del retry."""
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_DELIVERY_RETRY
    ) as authorization:
        delivery = retryable_delivery(authorization, message_id=message_id)
        _validate_retry_source(authorization, delivery)
        retry_delivery_authorized(
            authorization,
            message_id=message_id,
            purpose=str(delivery["purpose"]),
            aggregate_type=str(delivery["aggregate_type"]),
            aggregate_id=UUID(str(delivery["aggregate_id"])),
            person_id=UUID(str(delivery["person_id"])),
            source_version=int(str(delivery["source_version"])),
            reason=reason,
        )


__all__ = ("request_event_intent", "retry_delivery")
