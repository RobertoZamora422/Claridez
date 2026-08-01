from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import IntegrityError, connection, transaction
from django.db.models import Max, Q
from django.utils import timezone
from psycopg.types.range import Range

from claridez.identity.models import User
from claridez.organizations.capabilities import (
    Capability,
    capabilities_for_role,
    require_capability,
)
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.models import Membership, Organization, OrganizationSettings
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from .errors import conflict, invalid, unavailable
from .models import (
    ContactOrigin,
    EventRequest,
    Person,
    PersonRevision,
    Quotation,
    QuotationLine,
    QuotationSequence,
    QuotationVersion,
    Reservation,
)
from .normalization import (
    canonical_email,
    canonical_optional_text,
    canonical_phone,
    canonical_text,
    money,
)

HOLD_DURATION = timedelta(hours=48)
ACCEPTANCE_CHANNELS = frozenset({"in_person", "phone_call", "whatsapp", "email", "other"})
COMMERCIAL_CAPABILITIES = frozenset(
    {
        Capability.PERSON_READ,
        Capability.PERSON_MANAGE,
        Capability.SALES_READ,
        Capability.SALES_MANAGE,
        Capability.AVAILABILITY_READ,
        Capability.RESERVATION_CONFIRM,
        Capability.RESERVATION_CANCEL,
        Capability.RESERVATION_WAIVE_DEPOSIT,
    }
)


def _uuid(value: UUID | str, resource: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise unavailable(resource) from None


def _aware(value: datetime, field: str) -> datetime:
    if timezone.is_naive(value):
        raise invalid(f"{field} debe incluir zona horaria.")
    return value.astimezone(UTC)


def _origin(value: str) -> str:
    try:
        return ContactOrigin(value)
    except ValueError:
        raise invalid("El origen no es válido.") from None


def _can(authorization: TenantAuthorization, capability: Capability) -> bool:
    return capability in capabilities_for_role(authorization.role)


def _person_snapshot(person: Person, actor_id: UUID) -> PersonRevision:
    return PersonRevision.objects.create(
        organization_id=person.organization_id,
        person=person,
        revision=person.revision,
        full_name=person.full_name,
        phone_e164=person.phone_e164,
        email=person.email,
        origin=person.origin,
        origin_detail=person.origin_detail,
        changed_by_id=actor_id,
    )


def _is_client(person: Person) -> bool:
    return Reservation.objects.filter(
        organization_id=person.organization_id,
        event_request__person_id=person.pk,
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


def _get_person(organization_id: UUID, person_id: UUID | str, *, lock: bool = False) -> Person:
    queryset = Person.objects.select_for_update() if lock else Person.objects.all()
    try:
        return queryset.get(organization_id=organization_id, pk=_uuid(person_id, "La persona"))
    except Person.DoesNotExist:
        raise unavailable("La persona") from None


def commercial_capabilities(actor: User, organization_reference: UUID | str) -> tuple[str, ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.ORGANIZATION_ACCESS
    ) as authorization:
        available = capabilities_for_role(authorization.role) & COMMERCIAL_CAPABILITIES
        return tuple(sorted(capability.value for capability in available))


def list_people(
    actor: User, organization_reference: UUID | str, *, query: str = ""
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        rows = Person.objects.filter(organization_id=authorization.organization_id)
        canonical_query = query.strip()
        if canonical_query:
            rows = rows.filter(
                Q(full_name__icontains=canonical_query)
                | Q(phone_e164__icontains=canonical_query)
                | Q(email__icontains=canonical_query)
            )
        return tuple(_person_data(row) for row in rows.order_by("full_name", "id")[:100])


def create_person(
    actor: User,
    organization_reference: UUID | str,
    *,
    full_name: str,
    phone: str,
    email: str | None,
    origin: str,
    origin_detail: str | None,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_MANAGE
    ) as authorization:
        try:
            canonical_name = canonical_text(full_name, field="El nombre", max_length=150)
            canonical_phone_value = canonical_phone(phone)
            canonical_email_value = canonical_email(email)
            canonical_origin = _origin(origin)
            canonical_detail = canonical_optional_text(
                origin_detail, field="El detalle del origen", max_length=160
            )
        except ValueError as error:
            raise invalid(str(error)) from error
        try:
            with transaction.atomic():
                person = Person.objects.create(
                    organization_id=authorization.organization_id,
                    full_name=canonical_name,
                    phone_e164=canonical_phone_value,
                    email=canonical_email_value,
                    origin=canonical_origin,
                    origin_detail=canonical_detail,
                )
                _person_snapshot(person, authorization.actor_id)
        except IntegrityError as error:
            raise conflict("duplicate_person", "Ya existe una persona con ese teléfono.") from error
        return _person_data(person)


def read_person(
    actor: User, organization_reference: UUID | str, *, person_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        return _person_data(_get_person(authorization.organization_id, person_id))


def update_person(
    actor: User,
    organization_reference: UUID | str,
    *,
    person_id: UUID | str,
    revision: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_MANAGE
    ) as authorization:
        person = _get_person(authorization.organization_id, person_id, lock=True)
        if person.revision != revision:
            raise conflict("stale_revision", "La persona cambió; vuelve a cargarla.")
        original = (
            person.full_name,
            person.phone_e164,
            person.email,
            person.origin,
            person.origin_detail,
        )
        try:
            if "full_name" in changes:
                person.full_name = canonical_text(
                    str(changes["full_name"]), field="El nombre", max_length=150
                )
            if "phone" in changes:
                person.phone_e164 = canonical_phone(str(changes["phone"]))
            if "email" in changes:
                person.email = canonical_email(changes["email"])
            if "origin" in changes:
                person.origin = _origin(str(changes["origin"]))
            if "origin_detail" in changes:
                person.origin_detail = canonical_optional_text(
                    changes["origin_detail"], field="El detalle del origen", max_length=160
                )
        except ValueError as error:
            raise invalid(str(error)) from error
        current = (
            person.full_name,
            person.phone_e164,
            person.email,
            person.origin,
            person.origin_detail,
        )
        if current == original:
            return _person_data(person)
        person.revision += 1
        try:
            with transaction.atomic():
                person.save()
                _person_snapshot(person, authorization.actor_id)
        except IntegrityError as error:
            raise conflict("duplicate_person", "Ya existe una persona con ese teléfono.") from error
        return _person_data(person)


def list_person_revisions(
    actor: User, organization_reference: UUID | str, *, person_id: UUID | str
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        person = _get_person(authorization.organization_id, person_id)
        rows = PersonRevision.objects.filter(
            organization_id=authorization.organization_id, person=person
        ).order_by("revision")
        return tuple(
            {
                "revision": row.revision,
                "full_name": row.full_name,
                "phone_e164": row.phone_e164,
                "email": row.email or None,
                "origin": row.origin,
                "origin_detail": row.origin_detail or None,
                "changed_by_id": row.changed_by_id,
                "changed_at": row.created_at,
            }
            for row in rows
        )


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


def _validate_interval(starts_at: datetime, ends_at: datetime) -> tuple[datetime, datetime]:
    start = _aware(starts_at, "La hora inicial")
    end = _aware(ends_at, "La hora final")
    if start >= end:
        raise invalid("La hora final debe ser posterior a la inicial.")
    return start, end


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
        "event_type": event_request.event_type,
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


def _get_request(
    organization_id: UUID, request_id: UUID | str, *, lock: bool = False
) -> EventRequest:
    rows = EventRequest.objects.select_related("person")
    if lock:
        rows = rows.select_for_update()
    try:
        return rows.get(organization_id=organization_id, pk=_uuid(request_id, "La solicitud"))
    except EventRequest.DoesNotExist:
        raise unavailable("La solicitud") from None


def create_event_request(
    actor: User,
    organization_reference: UUID | str,
    *,
    person_id: UUID | str,
    event_type: str,
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
        person = _get_person(authorization.organization_id, person_id)
        responsible = _responsible_membership(authorization, responsible_membership_id)
        start, end = _validate_interval(starts_at, ends_at)
        settings = OrganizationSettings.objects.get(organization_id=authorization.organization_id)
        try:
            canonical_event_type = canonical_text(
                event_type, field="El tipo de evento", max_length=100
            )
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
            person=person,
            event_type=canonical_event_type,
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
        rows = EventRequest.objects.select_related("person").filter(
            organization_id=authorization.organization_id
        )
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
            if "event_type" in changes:
                row.event_type = canonical_text(
                    str(changes["event_type"]), field="El tipo de evento", max_length=100
                )
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


def _next_quote_number(organization_id: UUID, organization_timezone: str) -> str:
    Organization.objects.select_for_update().get(pk=organization_id)
    year = timezone.now().astimezone(ZoneInfo(organization_timezone)).year
    sequence, _ = QuotationSequence.objects.get_or_create(
        organization_id=organization_id, year=year, defaults={"next_value": 1}
    )
    sequence = QuotationSequence.objects.select_for_update().get(pk=sequence.pk)
    value = sequence.next_value
    sequence.next_value += 1
    sequence.save(update_fields=["next_value", "updated_at"])
    return f"COT-{year}-{value:06d}"


def _new_version(
    *,
    authorization: TenantAuthorization,
    quotation: Quotation,
    event_request: EventRequest,
    version: int,
    valid_until: datetime,
) -> QuotationVersion:
    valid = _aware(valid_until, "La vigencia")
    if valid <= timezone.now():
        raise invalid("La vigencia debe estar en el futuro.")
    settings = OrganizationSettings.objects.get(organization_id=authorization.organization_id)
    if settings.currency != "USD":
        raise conflict("unsupported_currency", "La Iteración 5.1 solo permite cotizaciones en USD.")
    organization = Organization.objects.get(pk=authorization.organization_id)
    person = event_request.person
    return QuotationVersion.objects.create(
        organization_id=authorization.organization_id,
        quotation=quotation,
        version=version,
        request_revision=event_request.revision,
        valid_until=valid,
        currency="USD",
        organization_name_snapshot=organization.name,
        person_name_snapshot=person.full_name,
        person_phone_snapshot=person.phone_e164,
        person_email_snapshot=person.email,
        event_type_snapshot=event_request.event_type,
        event_starts_at_snapshot=event_request.starts_at,
        event_ends_at_snapshot=event_request.ends_at,
        event_timezone_snapshot=event_request.event_timezone,
        estimated_guests_snapshot=event_request.estimated_guests,
        general_need_snapshot=event_request.general_need,
        request_notes_snapshot=event_request.notes,
    )


def create_quotation(
    actor: User,
    organization_reference: UUID | str,
    *,
    request_id: UUID | str,
    valid_until: datetime,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_MANAGE
    ) as authorization:
        _expire_overdue(authorization)
        event_request = _get_request(authorization.organization_id, request_id, lock=True)
        if event_request.status not in {EventRequest.Status.NEW, EventRequest.Status.QUOTED}:
            raise conflict("invalid_transition", "No puede crearse una cotización en este estado.")
        if Quotation.objects.filter(
            organization_id=authorization.organization_id, event_request=event_request
        ).exists():
            raise conflict("quotation_exists", "La solicitud ya tiene una cotización.")
        settings = OrganizationSettings.objects.get(organization_id=authorization.organization_id)
        quotation = Quotation.objects.create(
            organization_id=authorization.organization_id,
            event_request=event_request,
            visible_number=_next_quote_number(authorization.organization_id, settings.timezone),
        )
        _new_version(
            authorization=authorization,
            quotation=quotation,
            event_request=event_request,
            version=1,
            valid_until=valid_until,
        )
        return _quotation_data(quotation, authorization)


def create_quotation_version(
    actor: User,
    organization_reference: UUID | str,
    *,
    quotation_id: UUID | str,
    valid_until: datetime,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_MANAGE
    ) as authorization:
        _expire_overdue(authorization)
        quotation = _get_quotation(authorization.organization_id, quotation_id, lock=True)
        event_request = _get_request(
            authorization.organization_id, quotation.event_request_id, lock=True
        )
        if event_request.status not in {EventRequest.Status.NEW, EventRequest.Status.QUOTED}:
            raise conflict("invalid_transition", "No puede versionarse la cotización.")
        if QuotationVersion.objects.filter(
            organization_id=authorization.organization_id,
            quotation=quotation,
            status=QuotationVersion.Status.DRAFT,
        ).exists():
            raise conflict("draft_exists", "Ya existe una versión en borrador.")
        maximum = QuotationVersion.objects.filter(
            organization_id=authorization.organization_id, quotation=quotation
        ).aggregate(value=Max("version"))["value"]
        _new_version(
            authorization=authorization,
            quotation=quotation,
            event_request=event_request,
            version=int(maximum or 0) + 1,
            valid_until=valid_until,
        )
        return _quotation_data(quotation, authorization)


def _get_quotation(
    organization_id: UUID, quotation_id: UUID | str, *, lock: bool = False
) -> Quotation:
    rows = Quotation.objects.select_related("event_request__person")
    if lock:
        rows = rows.select_for_update()
    try:
        return rows.get(organization_id=organization_id, pk=_uuid(quotation_id, "La cotización"))
    except Quotation.DoesNotExist:
        raise unavailable("La cotización") from None


def _get_version(
    organization_id: UUID,
    quotation: Quotation,
    version: int,
    *,
    lock: bool = False,
) -> QuotationVersion:
    rows = QuotationVersion.objects.all()
    if lock:
        rows = rows.select_for_update()
    try:
        return rows.get(organization_id=organization_id, quotation=quotation, version=version)
    except QuotationVersion.DoesNotExist:
        raise unavailable("La versión") from None


def _line_data(line: QuotationLine) -> dict[str, Any]:
    return {
        "id": line.pk,
        "position": line.position,
        "description": line.description,
        "unit_label": line.unit_label or None,
        "quantity": line.quantity,
        "unit_price": line.unit_price,
        "discount_amount": line.discount_amount,
        "line_subtotal": line.line_subtotal,
        "line_total": line.line_total,
    }


def _version_data(row: QuotationVersion, *, include_contact: bool) -> dict[str, Any]:
    effective_status = (
        "expired"
        if row.status == QuotationVersion.Status.ISSUED and row.valid_until <= timezone.now()
        else row.status
    )
    lines = QuotationLine.objects.filter(
        organization_id=row.organization_id, quotation_version=row
    ).order_by("position", "id")
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
            "event_type": row.event_type_snapshot,
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


def read_quotation(
    actor: User, organization_reference: UUID | str, *, quotation_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_READ
    ) as authorization:
        _expire_overdue(authorization)
        return _quotation_data(
            _get_quotation(authorization.organization_id, quotation_id), authorization
        )


def replace_quotation_draft(
    actor: User,
    organization_reference: UUID | str,
    *,
    quotation_id: UUID | str,
    version: int,
    revision: int,
    valid_until: datetime,
    notes: str,
    lines: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_MANAGE
    ) as authorization:
        quotation = _get_quotation(authorization.organization_id, quotation_id, lock=True)
        draft = _get_version(authorization.organization_id, quotation, version, lock=True)
        if draft.status != QuotationVersion.Status.DRAFT:
            raise conflict("immutable_quotation", "La versión emitida es inmutable.")
        if draft.revision != revision:
            raise conflict("stale_revision", "La cotización cambió; vuelve a cargarla.")
        valid = _aware(valid_until, "La vigencia")
        if valid <= timezone.now():
            raise invalid("La vigencia debe estar en el futuro.")
        try:
            canonical_notes = canonical_optional_text(
                notes, field="Las notas de cotización", max_length=4000
            )
        except ValueError as error:
            raise invalid(str(error)) from error
        prepared: list[QuotationLine] = []
        subtotal = Decimal("0.00")
        discounts = Decimal("0.00")
        for position, raw in enumerate(lines, start=1):
            try:
                description = canonical_text(
                    str(raw["description"]), field="La descripción", max_length=240
                )
                unit_label = canonical_optional_text(
                    raw.get("unit_label"), field="La unidad", max_length=40
                )
                quantity = Decimal(str(raw["quantity"])).quantize(Decimal("0.001"))
                unit_price = money(Decimal(str(raw["unit_price"])))
                discount_amount = money(Decimal(str(raw.get("discount_amount", 0))))
            except (KeyError, ValueError, ArithmeticError) as error:
                raise invalid("Una línea de cotización no es válida.") from error
            line_subtotal = money(quantity * unit_price)
            if (
                quantity <= 0
                or unit_price < 0
                or discount_amount < 0
                or discount_amount > line_subtotal
            ):
                raise invalid("Los importes de una línea no son válidos.")
            line_total = line_subtotal - discount_amount
            prepared.append(
                QuotationLine(
                    organization_id=authorization.organization_id,
                    quotation_version=draft,
                    position=position,
                    description=description,
                    unit_label=unit_label,
                    quantity=quantity,
                    unit_price=unit_price,
                    discount_amount=discount_amount,
                    line_subtotal=line_subtotal,
                    line_total=line_total,
                )
            )
            subtotal += line_subtotal
            discounts += discount_amount
        if not prepared:
            raise invalid("La cotización debe contener al menos una línea.")
        draft.valid_until = valid
        draft.notes = canonical_notes
        draft.subtotal = money(subtotal)
        draft.discount_total = money(discounts)
        draft.total = money(subtotal - discounts)
        draft.revision += 1
        draft.save()
        QuotationLine.objects.filter(
            organization_id=authorization.organization_id, quotation_version=draft
        ).delete()
        QuotationLine.objects.bulk_create(prepared)
        return _quotation_data(quotation, authorization)


def issue_quotation_version(
    actor: User,
    organization_reference: UUID | str,
    *,
    quotation_id: UUID | str,
    version: int,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_MANAGE
    ) as authorization:
        quotation = _get_quotation(authorization.organization_id, quotation_id, lock=True)
        event_request = _get_request(
            authorization.organization_id, quotation.event_request_id, lock=True
        )
        row = _get_version(authorization.organization_id, quotation, version, lock=True)
        if row.status != QuotationVersion.Status.DRAFT:
            if row.status == QuotationVersion.Status.ISSUED:
                return _quotation_data(quotation, authorization)
            raise conflict("invalid_transition", "La versión no puede emitirse.")
        latest = QuotationVersion.objects.filter(
            organization_id=authorization.organization_id, quotation=quotation
        ).aggregate(value=Max("version"))["value"]
        if row.version != latest or row.request_revision != event_request.revision:
            raise conflict("stale_quotation", "La cotización no corresponde a la solicitud actual.")
        if row.valid_until <= timezone.now():
            raise conflict("expired_quotation", "La cotización está vencida.")
        if not QuotationLine.objects.filter(
            organization_id=authorization.organization_id, quotation_version=row
        ).exists():
            raise invalid("La cotización debe contener al menos una línea.")
        now = timezone.now()
        QuotationVersion.objects.filter(
            organization_id=authorization.organization_id,
            quotation=quotation,
            status=QuotationVersion.Status.ISSUED,
        ).exclude(pk=row.pk).update(status=QuotationVersion.Status.SUPERSEDED, updated_at=now)
        row.status = QuotationVersion.Status.ISSUED
        row.issued_at = now
        row.issued_by_membership_id = authorization.membership_id
        row.save(update_fields=["status", "issued_at", "issued_by_membership", "updated_at"])
        event_request.status = EventRequest.Status.QUOTED
        event_request.save(update_fields=["status", "updated_at"])
        return _quotation_data(quotation, authorization)


def _reservation_summary(row: Reservation) -> dict[str, Any]:
    return {
        "id": row.pk,
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


def _expire_overdue(authorization: TenantAuthorization, *, now: datetime | None = None) -> int:
    effective_now = timezone.now() if now is None else now
    rows = list(
        Reservation.objects.select_for_update()
        .filter(
            organization_id=authorization.organization_id,
            status=Reservation.Status.PROVISIONAL,
            hold_expires_at__lte=effective_now,
        )
        .order_by("created_at", "id")
    )
    transitioned = 0
    for reservation in rows:
        reservation.status = Reservation.Status.EXPIRED
        reservation.save(update_fields=["status", "updated_at"])
        event_request = EventRequest.objects.select_for_update().get(
            organization_id=authorization.organization_id, pk=reservation.event_request_id
        )
        has_active = Reservation.objects.filter(
            organization_id=authorization.organization_id,
            event_request=event_request,
            status__in=[Reservation.Status.PROVISIONAL, Reservation.Status.CONFIRMED],
        ).exists()
        if event_request.status == EventRequest.Status.ACCEPTED and not has_active:
            event_request.status = EventRequest.Status.QUOTED
            event_request.save(update_fields=["status", "updated_at"])
        transitioned += 1
    return transitioned


def _evaluate_expiration(
    actor: User,
    organization_reference: UUID | str,
    capability: Capability,
) -> int:
    """Persistir vencimientos antes de ejecutar un comando que todavía puede fallar."""
    with authorized_tenant_scope(actor, organization_reference, capability) as authorization:
        return _expire_overdue(authorization)


def _lock_organization_schedule(organization_id: UUID) -> None:
    """Serializar aceptaciones del único espacio sin bloquear otros comandos comerciales."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (str(organization_id),),
        )


def accept_quotation_version(
    actor: User,
    organization_reference: UUID | str,
    *,
    quotation_id: UUID | str,
    version: int,
    channel: str,
    note: str,
) -> dict[str, Any]:
    _evaluate_expiration(actor, organization_reference, Capability.SALES_MANAGE)
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_MANAGE
    ) as authorization:
        _lock_organization_schedule(authorization.organization_id)
        quotation = _get_quotation(authorization.organization_id, quotation_id, lock=True)
        event_request = _get_request(
            authorization.organization_id, quotation.event_request_id, lock=True
        )
        row = _get_version(authorization.organization_id, quotation, version, lock=True)
        existing = Reservation.objects.filter(
            organization_id=authorization.organization_id, quotation_version=row
        ).first()
        if row.status == QuotationVersion.Status.ACCEPTED and existing is not None:
            return _reservation_summary(existing)
        latest = QuotationVersion.objects.filter(
            organization_id=authorization.organization_id, quotation=quotation
        ).aggregate(value=Max("version"))["value"]
        if row.status != QuotationVersion.Status.ISSUED or row.version != latest:
            raise conflict("invalid_transition", "Solo la última versión emitida puede aceptarse.")
        now = timezone.now()
        if row.valid_until <= now:
            raise conflict("expired_quotation", "La cotización está vencida.")
        if row.request_revision != event_request.revision:
            raise conflict("stale_quotation", "La cotización no corresponde a la solicitud actual.")
        if row.event_ends_at_snapshot <= now:
            raise conflict("event_in_past", "El evento ya no puede reservarse.")
        if channel not in ACCEPTANCE_CHANNELS:
            raise invalid("El canal de aceptación no es válido.")
        try:
            canonical_note = canonical_optional_text(
                note, field="La nota de aceptación", max_length=500
            )
        except ValueError as error:
            raise invalid(str(error)) from error
        try:
            with transaction.atomic():
                row.status = QuotationVersion.Status.ACCEPTED
                row.accepted_at = now
                row.accepted_by_membership_id = authorization.membership_id
                row.acceptance_channel = channel
                row.acceptance_note = canonical_note
                row.save(
                    update_fields=[
                        "status",
                        "accepted_at",
                        "accepted_by_membership",
                        "acceptance_channel",
                        "acceptance_note",
                        "updated_at",
                    ]
                )
                event_request.status = EventRequest.Status.ACCEPTED
                event_request.save(update_fields=["status", "updated_at"])
                reservation = Reservation.objects.create(
                    organization_id=authorization.organization_id,
                    event_request=event_request,
                    quotation_version=row,
                    event_interval=Range(
                        row.event_starts_at_snapshot,
                        row.event_ends_at_snapshot,
                        bounds="[)",
                    ),
                    event_timezone=row.event_timezone_snapshot,
                    status=Reservation.Status.PROVISIONAL,
                    hold_expires_at=now + HOLD_DURATION,
                )
        except IntegrityError as error:
            raise conflict(
                "schedule_conflict", "El horario ya no se encuentra disponible."
            ) from error
        return _reservation_summary(reservation)


def list_availability(
    actor: User,
    organization_reference: UUID | str,
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.AVAILABILITY_READ
    ) as authorization:
        start, end = _validate_interval(starts_at, ends_at)
        _expire_overdue(authorization)
        candidate = Range(start, end, bounds="[)")
        rows = Reservation.objects.select_related("event_request").filter(
            organization_id=authorization.organization_id,
            status__in=[Reservation.Status.PROVISIONAL, Reservation.Status.CONFIRMED],
            event_interval__overlap=candidate,
        )
        blocks = tuple(
            {
                **_reservation_summary(row),
                "event_request_id": row.event_request_id,
                "event_type": row.event_request.event_type,
            }
            for row in rows.order_by("event_interval", "id")
        )
        return {"from": start, "to": end, "available": not blocks, "blocks": blocks}


def read_reservation(
    actor: User, organization_reference: UUID | str, *, reservation_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_READ
    ) as authorization:
        _expire_overdue(authorization)
        return _reservation_summary(_get_reservation(authorization.organization_id, reservation_id))


def _get_reservation(
    organization_id: UUID, reservation_id: UUID | str, *, lock: bool = False
) -> Reservation:
    rows = Reservation.objects.select_related("quotation_version", "event_request")
    if lock:
        rows = rows.select_for_update()
    try:
        return rows.get(
            organization_id=organization_id,
            pk=_uuid(reservation_id, "La reserva"),
        )
    except Reservation.DoesNotExist:
        raise unavailable("La reserva") from None


def confirm_reservation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    kind: str,
    recognized_amount: Decimal | None = None,
    reported_at: datetime | None = None,
    reference: str = "",
    waiver_reason: str = "",
) -> dict[str, Any]:
    _evaluate_expiration(actor, organization_reference, Capability.RESERVATION_CONFIRM)
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESERVATION_CONFIRM
    ) as authorization:
        row = _get_reservation(authorization.organization_id, reservation_id, lock=True)
        if row.status == Reservation.Status.CONFIRMED:
            return _reservation_summary(row)
        if row.status != Reservation.Status.PROVISIONAL:
            raise conflict("invalid_transition", "La reserva ya no puede confirmarse.")
        now = timezone.now()
        if row.hold_expires_at <= now:
            _expire_overdue(authorization, now=now)
            raise conflict("expired_reservation", "La reserva provisional venció.")
        if kind == Reservation.ConfirmationKind.EXTERNAL_DEPOSIT:
            if recognized_amount is None or reported_at is None:
                raise invalid("El monto y la fecha informada son obligatorios.")
            amount = money(recognized_amount)
            quote_total = row.quotation_version.total
            if amount <= 0 or amount > quote_total:
                raise invalid("El monto reconocido debe ser mayor que cero y no superar el total.")
            reported = _aware(reported_at, "La fecha informada")
            try:
                canonical_reference = canonical_text(
                    reference, field="La referencia", max_length=300
                )
            except ValueError as error:
                raise invalid(str(error)) from error
            row.recognized_deposit_amount = amount
            row.deposit_reported_at = reported
            row.deposit_reference = canonical_reference
        elif kind == Reservation.ConfirmationKind.WAIVER:
            authorization.require(Capability.RESERVATION_WAIVE_DEPOSIT)
            try:
                row.waiver_reason = canonical_text(
                    waiver_reason, field="La razón de excepción", max_length=500
                )
            except ValueError as error:
                raise invalid(str(error)) from error
            row.waiver_authorized_at = now
            row.waiver_authorized_by_membership_id = authorization.membership_id
        else:
            raise invalid("El tipo de confirmación no es válido.")
        row.confirmation_kind = kind
        row.status = Reservation.Status.CONFIRMED
        row.confirmed_at = now
        row.confirmed_by_membership_id = authorization.membership_id
        row.save()
        event_request = EventRequest.objects.select_for_update().get(
            organization_id=authorization.organization_id, pk=row.event_request_id
        )
        if event_request.status != EventRequest.Status.ACCEPTED:
            raise conflict("invalid_transition", "La solicitud no puede confirmarse.")
        event_request.status = EventRequest.Status.CONFIRMED
        event_request.save(update_fields=["status", "updated_at"])
        return _reservation_summary(row)


def cancel_reservation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    reason: str,
) -> dict[str, Any]:
    _evaluate_expiration(actor, organization_reference, Capability.RESERVATION_CANCEL)
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESERVATION_CANCEL
    ) as authorization:
        row = _get_reservation(authorization.organization_id, reservation_id, lock=True)
        if row.status == Reservation.Status.CANCELLED:
            return _reservation_summary(row)
        if row.status == Reservation.Status.EXPIRED:
            raise conflict("invalid_transition", "La reserva provisional ya venció.")
        try:
            canonical_reason = canonical_text(
                reason, field="La razón de cancelación", max_length=500
            )
        except ValueError as error:
            raise invalid(str(error)) from error
        was_confirmed = row.confirmed_at is not None
        now = timezone.now()
        row.status = Reservation.Status.CANCELLED
        row.cancelled_at = now
        row.cancelled_by_membership_id = authorization.membership_id
        row.cancellation_reason = canonical_reason
        row.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancelled_by_membership",
                "cancellation_reason",
                "updated_at",
            ]
        )
        event_request = EventRequest.objects.select_for_update().get(
            organization_id=authorization.organization_id, pk=row.event_request_id
        )
        event_request.status = (
            EventRequest.Status.CANCELLED if was_confirmed else EventRequest.Status.CLOSED_LOST
        )
        event_request.closed_at = now
        event_request.closed_reason = canonical_reason
        event_request.save(update_fields=["status", "closed_at", "closed_reason", "updated_at"])
        return _reservation_summary(row)
