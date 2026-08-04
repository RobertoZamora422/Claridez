from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils import timezone

from claridez.catalog.models import EventType
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, require_capability
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.models import Membership, OrganizationSettings, Space
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope
from claridez.people.public import PeopleError, lock_canonical_person_id

from ..errors import CommercialError, conflict, invalid, unavailable
from ..models import EventRequest, Reservation
from ..normalization import canonical_optional_text, canonical_text
from .representations import _request_data
from .reservations import _expire_overdue
from .shared import _origin, _uuid, _validate_interval


def _responsible_membership(
    authorization: TenantAuthorization, reference: UUID | str | None
) -> Membership:
    membership_id = (
        authorization.membership_id if reference is None else _uuid(reference, "La membresía")
    )
    try:
        membership = Membership.objects.get(
            pk=membership_id,
            organization_id=authorization.organization_id,
            status=Membership.Status.ACTIVE,
        )
    except Membership.DoesNotExist:
        raise unavailable("La membresía") from None
    try:
        require_capability(membership.role, Capability.SALES_MANAGE)
    except AuthorizationDenied:
        raise invalid("El responsable no puede gestionar solicitudes.") from None
    return membership


def _get_request(
    organization_id: UUID, request_id: UUID | str, *, lock: bool = False
) -> EventRequest:
    rows = EventRequest.objects.select_related(
        "person", "event_type_definition", "space", "space__venue"
    )
    if lock:
        rows = rows.select_for_update()
    try:
        return rows.get(organization_id=organization_id, pk=_uuid(request_id, "La solicitud"))
    except EventRequest.DoesNotExist:
        raise unavailable("La solicitud") from None


def _event_type(organization_id: UUID, reference: UUID | str) -> EventType:
    try:
        return EventType.objects.get(
            organization_id=organization_id,
            pk=_uuid(reference, "El tipo de evento"),
            is_active=True,
        )
    except EventType.DoesNotExist:
        raise unavailable("El tipo de evento") from None


def _space(organization_id: UUID, reference: UUID | str) -> Space:
    try:
        return Space.objects.select_related("venue").get(
            organization_id=organization_id,
            pk=_uuid(reference, "El espacio"),
            is_active=True,
            venue__is_active=True,
        )
    except Space.DoesNotExist:
        raise unavailable("El espacio") from None


def create_event_request(
    actor: User,
    organization_reference: UUID | str,
    *,
    person_id: UUID | str,
    event_type_id: UUID | str,
    space_id: UUID | str,
    starts_at: datetime,
    ends_at: datetime,
    estimated_guests: int,
    general_need: str,
    notes: str,
    origin: str,
    origin_detail: str | None,
    responsible_membership_id: UUID | str | None = None,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_MANAGE
    ) as authorization:
        try:
            canonical_person_id = lock_canonical_person_id(authorization.organization_id, person_id)
        except PeopleError as error:
            raise CommercialError(error.code, error.message, status=error.status) from error
        event_type = _event_type(authorization.organization_id, event_type_id)
        space = _space(authorization.organization_id, space_id)
        responsible = _responsible_membership(authorization, responsible_membership_id)
        start, end = _validate_interval(starts_at, ends_at)
        settings = OrganizationSettings.objects.get(organization_id=authorization.organization_id)
        try:
            canonical_need = canonical_text(
                general_need, field="La necesidad general", max_length=500
            )
            canonical_notes = canonical_optional_text(notes, field="Las notas", max_length=4000)
            canonical_origin = _origin(origin)
            canonical_detail = canonical_optional_text(
                origin_detail, field="El detalle del origen", max_length=160
            )
        except ValueError as error:
            raise invalid(str(error)) from error
        if estimated_guests < 1:
            raise invalid("Los invitados estimados deben ser mayores que cero.")
        row = EventRequest.objects.create(
            organization_id=authorization.organization_id,
            person_id=canonical_person_id,
            event_type_definition=event_type,
            space=space,
            event_type=event_type.name,
            starts_at=start,
            ends_at=end,
            event_timezone=settings.timezone,
            estimated_guests=estimated_guests,
            general_need=canonical_need,
            notes=canonical_notes,
            origin=canonical_origin,
            origin_detail=canonical_detail,
            responsible_membership=responsible,
        )
        return _request_data(row, authorization)


def list_event_requests(
    actor: User, organization_reference: UUID | str, *, status: str = ""
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_READ
    ) as authorization:
        _expire_overdue(authorization)
        rows = EventRequest.objects.select_related(
            "person", "event_type_definition", "space", "space__venue"
        ).filter(organization_id=authorization.organization_id)
        if status:
            rows = rows.filter(status=status)
        return tuple(_request_data(row, authorization) for row in rows.order_by("starts_at", "id"))


def read_event_request(
    actor: User, organization_reference: UUID | str, *, request_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_READ
    ) as authorization:
        _expire_overdue(authorization)
        return _request_data(_get_request(authorization.organization_id, request_id), authorization)


def update_event_request(
    actor: User,
    organization_reference: UUID | str,
    *,
    request_id: UUID | str,
    revision: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_MANAGE
    ) as authorization:
        _expire_overdue(authorization)
        row = _get_request(authorization.organization_id, request_id, lock=True)
        if row.revision != revision:
            raise conflict("stale_revision", "La solicitud cambió; vuelve a cargarla.")
        if row.status not in {EventRequest.Status.NEW, EventRequest.Status.QUOTED}:
            raise conflict("invalid_transition", "La solicitud ya no puede editarse.")
        original = (
            row.event_type_definition_id,
            row.space_id,
            row.event_type,
            row.starts_at,
            row.ends_at,
            row.estimated_guests,
            row.general_need,
            row.notes,
            row.origin,
            row.origin_detail,
            row.responsible_membership_id,
        )
        try:
            if "event_type_id" in changes:
                event_type = _event_type(authorization.organization_id, changes["event_type_id"])
                row.event_type_definition = event_type
                row.event_type = event_type.name
            if "space_id" in changes:
                row.space = _space(authorization.organization_id, changes["space_id"])
            if "general_need" in changes:
                row.general_need = canonical_text(
                    str(changes["general_need"]), field="La necesidad general", max_length=500
                )
            if "notes" in changes:
                row.notes = canonical_optional_text(
                    changes["notes"], field="Las notas", max_length=4000
                )
            if "origin" in changes:
                row.origin = _origin(str(changes["origin"]))
            if "origin_detail" in changes:
                row.origin_detail = canonical_optional_text(
                    changes["origin_detail"], field="El detalle del origen", max_length=160
                )
            if "estimated_guests" in changes:
                guests = int(changes["estimated_guests"])
                if guests < 1:
                    raise ValueError("Los invitados estimados deben ser mayores que cero.")
                row.estimated_guests = guests
            if "starts_at" in changes or "ends_at" in changes:
                row.starts_at, row.ends_at = _validate_interval(
                    changes.get("starts_at", row.starts_at), changes.get("ends_at", row.ends_at)
                )
            if "responsible_membership_id" in changes:
                row.responsible_membership = _responsible_membership(
                    authorization, changes["responsible_membership_id"]
                )
        except (TypeError, ValueError) as error:
            raise invalid(str(error)) from error
        current = (
            row.event_type_definition_id,
            row.space_id,
            row.event_type,
            row.starts_at,
            row.ends_at,
            row.estimated_guests,
            row.general_need,
            row.notes,
            row.origin,
            row.origin_detail,
            row.responsible_membership_id,
        )
        if current == original:
            return _request_data(row, authorization)
        row.revision += 1
        row.save()
        return _request_data(row, authorization)


def close_event_request(
    actor: User,
    organization_reference: UUID | str,
    *,
    request_id: UUID | str,
    reason: str,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_MANAGE
    ) as authorization:
        _expire_overdue(authorization)
        row = _get_request(authorization.organization_id, request_id, lock=True)
        try:
            canonical_reason = canonical_text(reason, field="La razón", max_length=500)
        except ValueError as error:
            raise invalid(str(error)) from error
        if row.status == EventRequest.Status.CLOSED_LOST:
            return _request_data(row, authorization)
        if row.status in {EventRequest.Status.CONFIRMED, EventRequest.Status.CANCELLED}:
            raise conflict("invalid_transition", "La solicitud debe cancelarse desde su reserva.")
        now = timezone.now()
        active = Reservation.objects.select_for_update().filter(
            organization_id=authorization.organization_id,
            event_request=row,
            status=Reservation.Status.PROVISIONAL,
        )
        active.update(
            status=Reservation.Status.CANCELLED,
            cancelled_at=now,
            cancelled_by_membership_id=authorization.membership_id,
            cancellation_reason=canonical_reason,
            updated_at=now,
        )
        row.status = EventRequest.Status.CLOSED_LOST
        row.closed_at = now
        row.closed_reason = canonical_reason
        row.save(update_fields=["status", "closed_at", "closed_reason", "updated_at"])
        return _request_data(row, authorization)
