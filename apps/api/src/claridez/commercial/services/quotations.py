from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from psycopg.types.range import Range

from claridez.catalog.services import resolve_catalog_line
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.models import Organization, OrganizationSettings
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from ..errors import conflict, invalid, unavailable
from ..models import (
    EventRequest,
    Quotation,
    QuotationLine,
    QuotationSequence,
    QuotationVersion,
    Reservation,
)
from ..normalization import canonical_optional_text, canonical_text, money
from .representations import _quotation_data, _reservation_summary
from .requests import _get_request
from .reservations import (
    HOLD_DURATION,
    _evaluate_expiration,
    _expire_overdue,
    _lock_organization_schedule,
)
from .shared import _aware, _uuid

ACCEPTANCE_CHANNELS = frozenset({"in_person", "phone_call", "whatsapp", "email", "other"})


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
        event_type_definition_snapshot=event_request.event_type_definition,
        event_type_snapshot=event_request.event_type,
        venue_snapshot=event_request.space.venue,
        venue_name_snapshot=event_request.space.venue.name,
        space_snapshot=event_request.space,
        space_name_snapshot=event_request.space.name,
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
    rows = Quotation.objects.select_related(
        "event_request__person",
        "event_request__event_type_definition",
        "event_request__space",
        "event_request__space__venue",
    )
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
                quantity = Decimal(str(raw["quantity"])).quantize(Decimal("0.001"))
                discount_amount = money(Decimal(str(raw.get("discount_amount", 0))))
            except (KeyError, ValueError, ArithmeticError) as error:
                raise invalid("Una línea de cotización no es válida.") from error
            catalog_item_id = raw.get("catalog_item_id")
            if catalog_item_id is None:
                try:
                    description = canonical_text(
                        str(raw["description"]), field="La descripción", max_length=240
                    )
                    unit_label = canonical_optional_text(
                        raw.get("unit_label"), field="La unidad", max_length=40
                    )
                    unit_price = money(Decimal(str(raw["unit_price"])))
                except (KeyError, ValueError, ArithmeticError) as error:
                    raise invalid("Una línea ad hoc no es válida.") from error
                source = QuotationLine.Source.AD_HOC
                catalog_revision_id = None
                catalog_price_id = None
                package_components: list[dict[str, Any]] = []
            else:
                catalog = resolve_catalog_line(authorization, item_id=catalog_item_id)
                description = str(catalog["description"])
                unit_label = str(catalog["unit_label"])
                unit_price = money(Decimal(str(catalog["unit_price"])))
                source = QuotationLine.Source.CATALOG
                catalog_revision_id = catalog["revision_id"]
                catalog_price_id = catalog["price_id"]
                package_components = list(catalog["package_components"])
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
                    source=source,
                    catalog_item_revision_id=catalog_revision_id,
                    catalog_price_id=catalog_price_id,
                    package_components_snapshot=package_components,
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
        quotation = _get_quotation(authorization.organization_id, quotation_id, lock=True)
        event_request = _get_request(
            authorization.organization_id, quotation.event_request_id, lock=True
        )
        row = _get_version(authorization.organization_id, quotation, version, lock=True)
        _lock_organization_schedule(authorization.organization_id, row.space_snapshot_id)
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
                    space_id=row.space_snapshot_id,
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
