"""Puerto público inmutable de oportunidades y evidencia comercial para CRM."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from claridez.organizations.tenant_scope import TenantAuthorization

from .errors import CommercialError, unavailable
from .models import EventRequest, EventRequestHistory, Reservation
from .services.reservations import _expire_overdue


@dataclass(frozen=True, slots=True)
class OpportunityProjection:
    id: UUID
    person_id: UUID
    event_type: str
    starts_at: datetime
    ends_at: datetime
    status: str
    result: str
    open_for_followup: bool
    origin: str
    origin_detail: str | None
    responsible_membership_id: UUID
    closed_reason: str | None
    revision: int
    general_need: str
    notes: str
    estimated_guests: int
    venue_id: UUID
    venue_name: str
    space_id: UUID
    space_name: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OpportunityHistoryProjection:
    id: UUID
    kind: str
    status: str
    request_revision: int
    origin: str
    origin_detail: str | None
    responsible_membership_id: UUID
    actor_membership_id: UUID | None
    occurred_at: datetime | None
    provenance: str
    reason: str | None
    created_at: datetime


def _opportunity_projection(row: EventRequest, *, won: bool) -> OpportunityProjection:
    result = "won" if won else "lost" if row.status == EventRequest.Status.CLOSED_LOST else "open"
    return OpportunityProjection(
        id=row.pk,
        person_id=row.person_id,
        event_type=row.event_type,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        status=row.status,
        result=result,
        open_for_followup=row.status
        not in {EventRequest.Status.CLOSED_LOST, EventRequest.Status.CANCELLED},
        origin=row.origin,
        origin_detail=row.origin_detail or None,
        responsible_membership_id=row.responsible_membership_id,
        closed_reason=row.closed_reason or None,
        revision=row.revision,
        general_need=row.general_need,
        notes=row.notes,
        estimated_guests=row.estimated_guests,
        venue_id=row.space.venue_id,
        venue_name=row.space.venue.name,
        space_id=row.space_id,
        space_name=row.space.name,
        updated_at=row.updated_at,
    )


def opportunities_for_crm(
    authorization: TenantAuthorization,
    *,
    status: str = "",
    person_ids: tuple[UUID, ...] | None = None,
) -> tuple[OpportunityProjection, ...]:
    _expire_overdue(authorization)
    rows = EventRequest.objects.select_related("space", "space__venue").filter(
        organization_id=authorization.organization_id
    )
    if status:
        rows = rows.filter(status=status)
    if person_ids is not None:
        rows = rows.filter(person_id__in=person_ids)
    materialized = tuple(rows.order_by("starts_at", "id"))
    won_ids = set(
        Reservation.objects.filter(
            organization_id=authorization.organization_id,
            event_request_id__in=(row.pk for row in materialized),
            confirmed_at__isnull=False,
        ).values_list("event_request_id", flat=True)
    )
    return tuple(_opportunity_projection(row, won=row.pk in won_ids) for row in materialized)


def opportunity_for_crm(
    authorization: TenantAuthorization, request_id: UUID
) -> OpportunityProjection:
    for row in opportunities_for_crm(authorization):
        if row.id == request_id:
            return row
    raise unavailable("La oportunidad")


def opportunity_history_for_crm(
    authorization: TenantAuthorization, request_id: UUID
) -> tuple[OpportunityHistoryProjection, ...]:
    opportunity_for_crm(authorization, request_id)
    return tuple(
        OpportunityHistoryProjection(
            id=row.pk,
            kind=row.kind,
            status=row.status,
            request_revision=row.request_revision,
            origin=row.origin,
            origin_detail=row.origin_detail or None,
            responsible_membership_id=row.responsible_membership_id,
            actor_membership_id=row.actor_membership_id,
            occurred_at=row.occurred_at,
            provenance=row.provenance,
            reason=row.reason or None,
            created_at=row.created_at,
        )
        for row in EventRequestHistory.objects.filter(
            organization_id=authorization.organization_id, event_request_id=request_id
        ).order_by("created_at", "id")
    )


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


__all__ = (
    "CommercialError",
    "OpportunityHistoryProjection",
    "OpportunityProjection",
    "confirmed_evidence_for_people",
    "interest_evidence_for_people",
    "opportunities_for_crm",
    "opportunity_for_crm",
    "opportunity_history_for_crm",
)
