"""Puerto público de oportunidades y evidencia comercial para CRM."""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet

from claridez.organizations.tenant_scope import TenantAuthorization

from .models import EventRequest, EventRequestHistory, Reservation
from .services.reservations import _expire_overdue


def opportunities_for_crm(
    authorization: TenantAuthorization, *, status: str = ""
) -> QuerySet[EventRequest]:
    _expire_overdue(authorization)
    rows = EventRequest.objects.select_related(
        "person", "event_type_definition", "space", "space__venue", "responsible_membership"
    ).filter(organization_id=authorization.organization_id)
    if status:
        rows = rows.filter(status=status)
    return rows.order_by("starts_at", "id")


def opportunity_for_crm(authorization: TenantAuthorization, request_id: UUID) -> EventRequest:
    try:
        return opportunities_for_crm(authorization).get(pk=request_id)
    except EventRequest.DoesNotExist:
        from .errors import unavailable

        raise unavailable("La oportunidad") from None


def opportunity_history_for_crm(
    authorization: TenantAuthorization, request_id: UUID
) -> QuerySet[EventRequestHistory]:
    opportunity_for_crm(authorization, request_id)
    return EventRequestHistory.objects.filter(
        organization_id=authorization.organization_id, event_request_id=request_id
    ).order_by("created_at", "id")


def confirmed_evidence_for_people(
    authorization: TenantAuthorization, person_ids: tuple[UUID, ...]
) -> bool:
    return Reservation.objects.filter(
        organization_id=authorization.organization_id,
        event_request__person_id__in=person_ids,
        confirmed_at__isnull=False,
    ).exists()


def interest_evidence_for_people(
    authorization: TenantAuthorization, person_ids: tuple[UUID, ...]
) -> bool:
    return EventRequest.objects.filter(
        organization_id=authorization.organization_id, person_id__in=person_ids
    ).exists()
