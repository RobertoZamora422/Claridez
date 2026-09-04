"""Puerto público inmutable de oportunidades y evidencia comercial para CRM."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from claridez.organizations.tenant_scope import TenantAuthorization

from .analytics import fetch_analytics_metrics, request_cohort, request_states_as_of
from .analytics_access import AnalyticsScheduleContext, schedule_context_for_analytics
from .errors import CommercialError, unavailable
from .finance_evidence import AcceptedSaleEvidence, economic_sales_for_analytics
from .models import EventRequest, EventRequestHistory, QuotationLine, QuotationVersion


@dataclass(frozen=True, slots=True)
class OperationEventTypeProjection:
    event_type_id: UUID
    event_type_label: str


def operation_event_type_snapshot(
    organization_id: UUID, quotation_version_id: UUID
) -> OperationEventTypeProjection:
    try:
        row = QuotationVersion.objects.only(
            "event_type_definition_snapshot_id", "event_type_snapshot"
        ).get(organization_id=organization_id, pk=quotation_version_id)
    except QuotationVersion.DoesNotExist:
        raise unavailable("El tipo de evento confirmado") from None
    return OperationEventTypeProjection(
        event_type_id=row.event_type_definition_snapshot_id,
        event_type_label=row.event_type_snapshot,
    )


def operational_event_projection_for_operations(
    reservation: object, *, include_phone: bool
) -> dict[str, object]:
    from .services.operations_projection import operational_event_projection

    return operational_event_projection(reservation, include_phone=include_phone)


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


@dataclass(frozen=True, slots=True)
class AcceptedScheduleEvidence:
    event_request_id: UUID
    quotation_version_id: UUID
    organization_id: UUID
    space_id: UUID
    starts_at: datetime
    ends_at: datetime
    timezone_name: str
    total: Decimal
    status: str
    accepted_at: datetime | None


@dataclass(frozen=True, slots=True)
class AcceptedQuotationLineProjection:
    position: int
    source: str
    description: str
    unit_label: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    line_subtotal: Decimal
    line_total: Decimal
    package_components_snapshot: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class AcceptedQuotationProjection:
    id: UUID
    organization_id: UUID
    event_request_id: UUID
    person_id: UUID
    visible_number: str
    version: int
    status: str
    currency: str
    organization_name: str
    person_name: str
    person_phone: str
    person_email: str | None
    event_type: str
    venue_id: UUID
    venue_name: str
    space_id: UUID
    space_name: str
    starts_at: datetime
    ends_at: datetime
    timezone_name: str
    estimated_guests: int
    general_need: str
    request_notes: str
    quotation_notes: str
    subtotal: Decimal
    discount_total: Decimal
    total: Decimal
    accepted_at: datetime
    acceptance_channel: str
    acceptance_note: str
    lines: tuple[AcceptedQuotationLineProjection, ...]


@dataclass(frozen=True, slots=True)
class EconomicSaleProjection:
    organization_id: UUID
    quotation_version_id: UUID
    currency: str
    total: Decimal
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class ClientEventRequestProjection:
    id: UUID
    person_id: UUID
    status: str
    event_type: str
    starts_at: datetime
    ends_at: datetime
    timezone_name: str
    venue_name: str
    space_name: str
    estimated_guests: int
    revision: int


@dataclass(frozen=True, slots=True)
class ClientQuotationLineProjection:
    position: int
    description: str
    unit_label: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    line_total: Decimal


@dataclass(frozen=True, slots=True)
class ClientQuotationProjection:
    id: UUID
    visible_number: str
    version: int
    status: str
    withdrawn: bool
    is_expired: bool
    currency: str | None
    event_type: str | None
    venue_name: str | None
    space_name: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    timezone_name: str | None
    subtotal: Decimal | None
    discount_total: Decimal | None
    total: Decimal | None
    issued_at: datetime | None
    valid_until: datetime | None
    accepted_at: datetime | None
    lines: tuple[ClientQuotationLineProjection, ...]


def create_public_event_request(organization_id: UUID, **values: object) -> UUID:
    from .services.requests import create_event_request_from_public_capture

    return create_event_request_from_public_capture(organization_id, **values).pk  # type: ignore[arg-type]


def client_event_request(
    organization_id: UUID, event_request_id: UUID
) -> ClientEventRequestProjection:
    try:
        row = EventRequest.objects.select_related("space", "space__venue").get(
            organization_id=organization_id, pk=event_request_id
        )
    except EventRequest.DoesNotExist:
        raise unavailable("La solicitud") from None
    return ClientEventRequestProjection(
        id=row.pk,
        person_id=row.person_id,
        status=row.status,
        event_type=row.event_type,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        timezone_name=row.event_timezone,
        venue_name=row.space.venue.name,
        space_name=row.space.name,
        estimated_guests=row.estimated_guests,
        revision=row.revision,
    )


def client_quotations(
    organization_id: UUID, event_request_id: UUID
) -> tuple[ClientQuotationProjection, ...]:
    from django.utils import timezone

    rows = QuotationVersion.objects.select_related("quotation").filter(
        organization_id=organization_id,
        quotation__event_request_id=event_request_id,
        status__in=[
            QuotationVersion.Status.ISSUED,
            QuotationVersion.Status.SUPERSEDED,
            QuotationVersion.Status.ACCEPTED,
            QuotationVersion.Status.WITHDRAWN,
        ],
    )
    result: list[ClientQuotationProjection] = []
    for row in rows.order_by("version", "id"):
        withdrawn = row.status == QuotationVersion.Status.WITHDRAWN
        line_rows: tuple[ClientQuotationLineProjection, ...] = ()
        if not withdrawn:
            line_rows = tuple(
                ClientQuotationLineProjection(
                    position=line.position,
                    description=line.description,
                    unit_label=line.unit_label,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    discount_amount=line.discount_amount,
                    line_total=line.line_total,
                )
                for line in QuotationLine.objects.filter(
                    organization_id=organization_id, quotation_version_id=row.pk
                ).order_by("position", "id")
            )
        result.append(
            ClientQuotationProjection(
                id=row.pk,
                visible_number=row.quotation.visible_number,
                version=row.version,
                status=row.status,
                withdrawn=withdrawn,
                is_expired=(
                    not withdrawn
                    and row.status == QuotationVersion.Status.ISSUED
                    and row.valid_until < timezone.now()
                ),
                currency=None if withdrawn else row.currency,
                event_type=None if withdrawn else row.event_type_snapshot,
                venue_name=None if withdrawn else row.venue_name_snapshot,
                space_name=None if withdrawn else row.space_name_snapshot,
                starts_at=None if withdrawn else row.event_starts_at_snapshot,
                ends_at=None if withdrawn else row.event_ends_at_snapshot,
                timezone_name=None if withdrawn else row.event_timezone_snapshot,
                subtotal=None if withdrawn else row.subtotal,
                discount_total=None if withdrawn else row.discount_total,
                total=None if withdrawn else row.total,
                issued_at=None if withdrawn else row.issued_at,
                valid_until=None if withdrawn else row.valid_until,
                accepted_at=None if withdrawn else row.accepted_at,
                lines=line_rows,
            )
        )
    return tuple(result)


def economic_sale_for_finance(
    authorization: TenantAuthorization, quotation_version_id: UUID
) -> EconomicSaleProjection:
    try:
        row = QuotationVersion.objects.get(
            organization_id=authorization.organization_id,
            pk=quotation_version_id,
            status=QuotationVersion.Status.ACCEPTED,
            accepted_at__isnull=False,
        )
    except QuotationVersion.DoesNotExist:
        raise unavailable("La venta confirmada") from None
    if row.accepted_at is None:
        raise unavailable("La venta confirmada")
    return EconomicSaleProjection(
        organization_id=row.organization_id,
        quotation_version_id=row.pk,
        currency=row.currency,
        total=row.total,
        accepted_at=row.accepted_at,
    )


def accepted_quotation_for_documents(
    authorization: TenantAuthorization, quotation_version_id: UUID
) -> AcceptedQuotationProjection:
    try:
        row = QuotationVersion.objects.select_related("quotation", "quotation__event_request").get(
            organization_id=authorization.organization_id,
            pk=quotation_version_id,
            status=QuotationVersion.Status.ACCEPTED,
            accepted_at__isnull=False,
        )
    except QuotationVersion.DoesNotExist:
        raise unavailable("La cotización aceptada") from None
    line_rows = QuotationLine.objects.filter(
        organization_id=authorization.organization_id, quotation_version_id=row.pk
    ).order_by("position", "id")
    lines = tuple(
        AcceptedQuotationLineProjection(
            position=line.position,
            source=line.source,
            description=line.description,
            unit_label=line.unit_label,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_amount=line.discount_amount,
            line_subtotal=line.line_subtotal,
            line_total=line.line_total,
            package_components_snapshot=tuple(line.package_components_snapshot),
        )
        for line in line_rows
    )
    accepted_at = row.accepted_at
    if accepted_at is None:
        raise unavailable("La cotización aceptada")
    return AcceptedQuotationProjection(
        id=row.pk,
        organization_id=row.organization_id,
        event_request_id=row.quotation.event_request_id,
        person_id=row.quotation.event_request.person_id,
        visible_number=row.quotation.visible_number,
        version=row.version,
        status=row.status,
        currency=row.currency,
        organization_name=row.organization_name_snapshot,
        person_name=row.person_name_snapshot,
        person_phone=row.person_phone_snapshot,
        person_email=row.person_email_snapshot or None,
        event_type=row.event_type_snapshot,
        venue_id=row.venue_snapshot_id,
        venue_name=row.venue_name_snapshot,
        space_id=row.space_snapshot_id,
        space_name=row.space_name_snapshot,
        starts_at=row.event_starts_at_snapshot,
        ends_at=row.event_ends_at_snapshot,
        timezone_name=row.event_timezone_snapshot,
        estimated_guests=row.estimated_guests_snapshot,
        general_need=row.general_need_snapshot,
        request_notes=row.request_notes_snapshot,
        quotation_notes=row.notes,
        subtotal=row.subtotal,
        discount_total=row.discount_total,
        total=row.total,
        accepted_at=accepted_at,
        acceptance_channel=row.acceptance_channel,
        acceptance_note=row.acceptance_note,
        lines=lines,
    )


def accepted_schedule_evidence(
    authorization: TenantAuthorization, quotation_version_id: UUID
) -> AcceptedScheduleEvidence:
    try:
        row = QuotationVersion.objects.select_related("quotation").get(
            organization_id=authorization.organization_id,
            pk=quotation_version_id,
        )
    except QuotationVersion.DoesNotExist:
        raise unavailable("La cotización aceptada") from None
    return AcceptedScheduleEvidence(
        event_request_id=row.quotation.event_request_id,
        quotation_version_id=row.pk,
        organization_id=row.organization_id,
        space_id=row.space_snapshot_id,
        starts_at=row.event_starts_at_snapshot,
        ends_at=row.event_ends_at_snapshot,
        timezone_name=row.event_timezone_snapshot,
        total=row.total,
        status=row.status,
        accepted_at=row.accepted_at,
    )


def accepted_quotation_snapshot(
    authorization: TenantAuthorization, quotation_version_id: UUID
) -> AcceptedQuotationProjection:
    """Snapshot económico aceptado para consumidores tipados, sin ORM compartido."""
    return accepted_quotation_for_documents(authorization, quotation_version_id)


def set_request_schedule_status(
    authorization: TenantAuthorization,
    event_request_id: UUID,
    *,
    status: str,
    closed_at: datetime | None = None,
    closed_reason: str = "",
) -> None:
    row = EventRequest.objects.select_for_update().get(
        organization_id=authorization.organization_id,
        pk=event_request_id,
    )
    row.status = status
    fields = ["status", "updated_at"]
    if closed_at is not None:
        row.closed_at = closed_at
        row.closed_reason = closed_reason
        fields += ["closed_at", "closed_reason"]
    row.save(update_fields=fields)


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
    from claridez.scheduling.public import expire_overdue_for_organization

    expire_overdue_for_organization(authorization)
    rows = EventRequest.objects.select_related("space", "space__venue").filter(
        organization_id=authorization.organization_id
    )
    if status:
        rows = rows.filter(status=status)
    if person_ids is not None:
        rows = rows.filter(person_id__in=person_ids)
    materialized = tuple(rows.order_by("starts_at", "id"))
    from claridez.scheduling.public import confirmed_event_request_ids

    won_ids = confirmed_event_request_ids(authorization, tuple(row.pk for row in materialized))
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
    request_ids = tuple(
        EventRequest.objects.filter(
            organization_id=authorization.organization_id, person_id__in=person_ids
        ).values_list("id", flat=True)
    )
    from claridez.scheduling.public import confirmed_event_request_ids

    return bool(confirmed_event_request_ids(authorization, request_ids))


def interest_evidence_for_people(
    authorization: TenantAuthorization, person_ids: tuple[UUID, ...]
) -> bool:
    return EventRequest.objects.filter(
        organization_id=authorization.organization_id, person_id__in=person_ids
    ).exists()


__all__ = (
    "AnalyticsScheduleContext",
    "schedule_context_for_analytics",
    "AcceptedSaleEvidence",
    "economic_sales_for_analytics",
    "CommercialError",
    "AcceptedScheduleEvidence",
    "AcceptedQuotationLineProjection",
    "AcceptedQuotationProjection",
    "EconomicSaleProjection",
    "ClientEventRequestProjection",
    "ClientQuotationLineProjection",
    "ClientQuotationProjection",
    "OpportunityHistoryProjection",
    "OpportunityProjection",
    "OperationEventTypeProjection",
    "accepted_schedule_evidence",
    "accepted_quotation_for_documents",
    "accepted_quotation_snapshot",
    "economic_sale_for_finance",
    "confirmed_evidence_for_people",
    "interest_evidence_for_people",
    "opportunities_for_crm",
    "opportunity_for_crm",
    "opportunity_history_for_crm",
    "operation_event_type_snapshot",
    "operational_event_projection_for_operations",
    "set_request_schedule_status",
    "create_public_event_request",
    "client_event_request",
    "client_quotations",
    "fetch_analytics_metrics",
    "request_cohort",
    "request_states_as_of",
)
