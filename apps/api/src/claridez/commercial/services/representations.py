from __future__ import annotations

from typing import Any

from django.utils import timezone

from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization
from claridez.people.public import canonical_cluster_ids

from ..models import (
    EventRequest,
    Person,
    Quotation,
    QuotationLine,
    QuotationVersion,
    Reservation,
)
from .shared import _can


def _is_client(person: Person) -> bool:
    cluster = canonical_cluster_ids(person.organization_id, person.pk)
    return Reservation.objects.filter(
        organization_id=person.organization_id,
        event_request__person_id__in=cluster,
        confirmed_at__isnull=False,
    ).exists()


def _person_data(person: Person, *, include_contact: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": person.pk,
        "commercial_type": "client" if _is_client(person) else "lead",
        "revision": person.revision,
        "created_at": person.created_at,
        "updated_at": person.updated_at,
    }
    if include_contact:
        data.update(
            {
                "full_name": person.full_name,
                "phone_e164": person.phone_e164,
                "email": person.email or None,
                "origin": person.origin,
                "origin_detail": person.origin_detail or None,
            }
        )
    return data


def _line_data(line: QuotationLine) -> dict[str, Any]:
    catalog_revision = (
        line.catalog_item_revision if line.catalog_item_revision_id is not None else None
    )
    return {
        "id": line.pk,
        "source": line.source,
        "catalog_item_id": catalog_revision.item_id if catalog_revision is not None else None,
        "catalog_item_revision_id": line.catalog_item_revision_id,
        "catalog_price_id": line.catalog_price_id,
        "package_components": line.package_components_snapshot,
        "position": line.position,
        "description": line.description,
        "unit_label": line.unit_label or None,
        "quantity": line.quantity,
        "unit_price": line.unit_price,
        "discount_amount": line.discount_amount,
        "line_subtotal": line.line_subtotal,
        "line_total": line.line_total,
    }


def _reservation_summary(row: Reservation) -> dict[str, Any]:
    return {
        "id": row.pk,
        "space_id": row.space_id,
        "status": row.status,
        "starts_at": row.event_interval.lower,
        "ends_at": row.event_interval.upper,
        "event_timezone": row.event_timezone,
        "hold_expires_at": row.hold_expires_at,
        "confirmation_kind": row.confirmation_kind or None,
        "recognized_deposit_amount": row.recognized_deposit_amount,
        "deposit_reported_at": row.deposit_reported_at,
        "deposit_reference": row.deposit_reference or None,
        "confirmed_at": row.confirmed_at,
        "waiver_reason": row.waiver_reason or None,
        "waiver_authorized_at": row.waiver_authorized_at,
        "cancelled_at": row.cancelled_at,
        "cancellation_reason": row.cancellation_reason or None,
    }


def _request_data(
    event_request: EventRequest, authorization: TenantAuthorization
) -> dict[str, Any]:
    include_contact = _can(authorization, Capability.PERSON_READ)
    person = _person_data(event_request.person, include_contact=include_contact)
    quotation = Quotation.objects.filter(
        organization_id=authorization.organization_id, event_request=event_request
    ).first()
    reservation = (
        Reservation.objects.filter(
            organization_id=authorization.organization_id, event_request=event_request
        )
        .order_by("-created_at")
        .first()
    )
    return {
        "id": event_request.pk,
        "person": person,
        "event_type_id": event_request.event_type_definition_id,
        "event_type": event_request.event_type,
        "venue": {
            "id": event_request.space.venue_id,
            "name": event_request.space.venue.name,
        },
        "space": {"id": event_request.space_id, "name": event_request.space.name},
        "starts_at": event_request.starts_at,
        "ends_at": event_request.ends_at,
        "event_timezone": event_request.event_timezone,
        "estimated_guests": event_request.estimated_guests,
        "general_need": event_request.general_need,
        "notes": event_request.notes,
        "origin": event_request.origin,
        "origin_detail": event_request.origin_detail or None,
        "responsible_membership_id": event_request.responsible_membership_id,
        "status": event_request.status,
        "revision": event_request.revision,
        "closed_at": event_request.closed_at,
        "closed_reason": event_request.closed_reason or None,
        "quotation_id": quotation.pk if quotation is not None else None,
        "reservation": _reservation_summary(reservation) if reservation is not None else None,
        "created_at": event_request.created_at,
        "updated_at": event_request.updated_at,
    }


def _version_data(row: QuotationVersion, *, include_contact: bool) -> dict[str, Any]:
    effective_status = (
        "expired"
        if row.status == QuotationVersion.Status.ISSUED and row.valid_until <= timezone.now()
        else row.status
    )
    lines = (
        QuotationLine.objects.select_related("catalog_item_revision")
        .filter(organization_id=row.organization_id, quotation_version=row)
        .order_by("position", "id")
    )
    reservation = Reservation.objects.filter(
        organization_id=row.organization_id, quotation_version=row
    ).first()
    person: dict[str, Any] = (
        {
            "full_name": row.person_name_snapshot,
            "phone_e164": row.person_phone_snapshot,
            "email": row.person_email_snapshot or None,
        }
        if include_contact
        else {"restricted": True}
    )
    return {
        "id": row.pk,
        "version": row.version,
        "request_revision": row.request_revision,
        "revision": row.revision,
        "status": effective_status,
        "stored_status": row.status,
        "valid_until": row.valid_until,
        "currency": row.currency,
        "organization_name": row.organization_name_snapshot,
        "person": person,
        "event": {
            "event_type_id": row.event_type_definition_snapshot_id,
            "event_type": row.event_type_snapshot,
            "venue": {"id": row.venue_snapshot_id, "name": row.venue_name_snapshot},
            "space": {"id": row.space_snapshot_id, "name": row.space_name_snapshot},
            "starts_at": row.event_starts_at_snapshot,
            "ends_at": row.event_ends_at_snapshot,
            "timezone": row.event_timezone_snapshot,
            "estimated_guests": row.estimated_guests_snapshot,
            "general_need": row.general_need_snapshot,
            "notes": row.request_notes_snapshot,
        },
        "notes": row.notes,
        "subtotal": row.subtotal,
        "discount_total": row.discount_total,
        "total": row.total,
        "issued_at": row.issued_at,
        "accepted_at": row.accepted_at,
        "acceptance_channel": row.acceptance_channel or None,
        "acceptance_note": row.acceptance_note or None,
        "lines": tuple(_line_data(line) for line in lines),
        "reservation_id": reservation.pk if reservation is not None else None,
    }


def _quotation_data(quotation: Quotation, authorization: TenantAuthorization) -> dict[str, Any]:
    versions = QuotationVersion.objects.filter(
        organization_id=quotation.organization_id, quotation=quotation
    ).order_by("version")
    return {
        "id": quotation.pk,
        "event_request_id": quotation.event_request_id,
        "visible_number": quotation.visible_number,
        "versions": tuple(
            _version_data(
                row,
                include_contact=_can(authorization, Capability.PERSON_READ),
            )
            for row in versions
        ),
        "created_at": quotation.created_at,
        "updated_at": quotation.updated_at,
    }
