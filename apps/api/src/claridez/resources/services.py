from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, cast
from uuid import UUID, uuid4

from django.db import connection
from django.db.models import Exists, Max, Model, OuterRef, Sum
from django.utils import timezone
from psycopg.types.range import Range

import claridez.organizations.public as organizations_port
import claridez.people.public as people_port
import claridez.scheduling.public as scheduling_port
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from .errors import conflict, invalid, unavailable
from .models import (
    CustodyEvent,
    InventoryLocation,
    MaintenanceRecord,
    Purchase,
    PurchaseLine,
    Resource,
    ResourceAssignment,
    ResourceCapacityAllocation,
    ResourceCommand,
    ResourceEvent,
    ResourceRequirement,
    ResourceUnavailability,
    SerializedAsset,
    StockBalance,
    StockMovement,
    Supplier,
    SupplierContact,
    SupplierOffering,
    SupplierTermRevision,
    SupplyReceipt,
    SupplyReceiptLine,
    UnitConversion,
    UnitDefinition,
)

SIX = Decimal("0.000001")
ZERO = Decimal("0.000000")
P12_CAPABILITIES = frozenset(
    capability
    for capability in Capability
    if capability.value.startswith(("resource:", "supplier:", "inventory:", "purchase:"))
)


def _uuid(value: UUID | str, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise unavailable(label) from None


def _quantity(value: Decimal | int | str, *, integral: bool = False) -> Decimal:
    try:
        normalized = Decimal(str(value)).quantize(SIX, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise invalid("La cantidad no es válida.") from None
    if normalized <= ZERO or (integral and normalized != normalized.to_integral_value()):
        raise invalid("La cantidad debe ser positiva y compatible con el recurso.")
    return normalized


def _json(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(_json(payload), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _lock(key: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])


def _command_replay(
    authorization: TenantAuthorization,
    *,
    command_type: str,
    idempotency_key: UUID,
    payload: object,
) -> tuple[str, UUID] | None:
    _lock(f"resources:{authorization.organization_id}:command:{command_type}:{idempotency_key}")
    row = ResourceCommand.objects.filter(
        organization_id=authorization.organization_id,
        command_type=command_type,
        idempotency_key=idempotency_key,
    ).first()
    if row is None:
        return None
    if row.payload_sha256 != _hash(payload):
        raise conflict(
            "idempotency_conflict",
            "La clave de idempotencia ya fue usada con una solicitud diferente.",
        )
    return row.result_type, row.result_reference


def _complete(
    authorization: TenantAuthorization,
    *,
    command_type: str,
    idempotency_key: UUID,
    payload: object,
    result_type: str,
    result_reference: UUID,
) -> None:
    ResourceCommand.objects.create(
        organization_id=authorization.organization_id,
        command_type=command_type,
        idempotency_key=idempotency_key,
        payload_sha256=_hash(payload),
        result_type=result_type,
        result_reference=result_reference,
    )


def _event(
    authorization: TenantAuthorization,
    aggregate_kind: str,
    aggregate_id: UUID,
    kind: str,
    payload: object,
) -> None:
    ResourceEvent.objects.create(
        organization_id=authorization.organization_id,
        aggregate_kind=aggregate_kind,
        aggregate_id=aggregate_id,
        kind=kind,
        payload=_json(payload),
        occurred_at=timezone.now(),
        recorded_by_membership_id=authorization.membership_id,
    )


def _get[ModelT: Model](
    model: type[ModelT],
    authorization: TenantAuthorization,
    value: UUID | str,
    label: str,
) -> ModelT:
    try:
        return cast(
            ModelT,
            model.objects.get(  # type: ignore[attr-defined]
                organization_id=authorization.organization_id, pk=_uuid(value, label)
            ),
        )
    except model.DoesNotExist:  # type: ignore[attr-defined]
        raise unavailable(label) from None


def resources_capabilities(actor: User, organization_reference: UUID | str) -> tuple[str, ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.ORGANIZATION_ACCESS
    ) as authorization:
        return tuple(
            sorted(
                capability.value
                for capability in capabilities_for_role(authorization.role)
                if capability in P12_CAPABILITIES
            )
        )


def create_unit(
    actor: User,
    organization_reference: UUID | str,
    *,
    code: str,
    name: str,
    symbol: str,
    dimension: str,
    idempotency_key: UUID,
) -> UnitDefinition:
    payload = {"code": code, "name": name, "symbol": symbol, "dimension": dimension}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_MANAGE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="create_unit",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(UnitDefinition, authorization, replay[1], "La unidad")
        normalized_code = code.strip().lower()
        if not normalized_code or dimension not in UnitDefinition.Dimension.values:
            raise invalid("El código o dimensión de la unidad no es válido.")
        row = UnitDefinition.objects.create(
            organization_id=authorization.organization_id,
            code=normalized_code,
            name=name.strip(),
            symbol=symbol.strip(),
            dimension=dimension,
        )
        _complete(
            authorization,
            command_type="create_unit",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="unit",
            result_reference=row.pk,
        )
        return row


def create_conversion(
    actor: User,
    organization_reference: UUID | str,
    *,
    from_unit_id: UUID | str,
    to_unit_id: UUID | str,
    multiplier: Decimal | int | str,
    valid_from: date | None = None,
    valid_until: date | None = None,
    idempotency_key: UUID,
) -> UnitConversion:
    payload = {
        "from_unit_id": from_unit_id,
        "to_unit_id": to_unit_id,
        "multiplier": multiplier,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_MANAGE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="create_conversion",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(UnitConversion, authorization, replay[1], "La conversión")
        source = _get(UnitDefinition, authorization, from_unit_id, "La unidad de origen")
        target = _get(UnitDefinition, authorization, to_unit_id, "La unidad de destino")
        if source.dimension != target.dimension:
            raise invalid("Solo se convierten unidades de la misma dimensión.")
        _lock(f"resources:{authorization.organization_id}:conversion:{source.pk}:{target.pk}")
        revision = (
            UnitConversion.objects.filter(
                organization_id=authorization.organization_id,
                from_unit=source,
                to_unit=target,
            ).aggregate(value=Max("revision"))["value"]
            or 0
        ) + 1
        row = UnitConversion.objects.create(
            organization_id=authorization.organization_id,
            from_unit=source,
            to_unit=target,
            multiplier=_quantity(multiplier),
            revision=revision,
            valid_from=valid_from or date.today(),
            valid_until=valid_until,
        )
        _complete(
            authorization,
            command_type="create_conversion",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="conversion",
            result_reference=row.pk,
        )
        return row


def create_supplier(
    actor: User,
    organization_reference: UUID | str,
    *,
    legal_name: str,
    tax_identifier: str | None,
    internal_code: str | None = None,
    idempotency_key: UUID,
) -> Supplier:
    payload = {
        "legal_name": legal_name,
        "tax_identifier": tax_identifier,
        "internal_code": internal_code,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SUPPLIER_MANAGE_PROFILE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="create_supplier",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(Supplier, authorization, replay[1], "El proveedor")
        normalized_name = " ".join(legal_name.casefold().split())
        normalized_tax = "".join(
            character for character in (tax_identifier or "") if character.isalnum()
        ).upper()
        normalized_code = "-".join((internal_code or "").strip().upper().split())
        if not normalized_name:
            raise invalid("El nombre del proveedor es obligatorio.")
        if not normalized_tax and not normalized_code:
            raise invalid("El proveedor sin identificación fiscal requiere un código interno.")
        identity_key = f"tax:{normalized_tax}" if normalized_tax else f"code:{normalized_code}"
        row = Supplier.objects.create(
            organization_id=authorization.organization_id,
            legal_name=legal_name.strip(),
            normalized_legal_name=normalized_name,
            tax_identifier=normalized_tax or None,
            internal_code=None if normalized_tax else normalized_code,
            identity_key=identity_key,
            created_by_membership_id=authorization.membership_id,
        )
        _event(authorization, "supplier", row.pk, "supplier_created", payload)
        _complete(
            authorization,
            command_type="create_supplier",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="supplier",
            result_reference=row.pk,
        )
        return row


def set_supplier_active(
    actor: User,
    organization_reference: UUID | str,
    *,
    supplier_id: UUID | str,
    active: bool,
    reason: str,
    idempotency_key: UUID,
) -> Supplier:
    payload = {"supplier_id": supplier_id, "active": active, "reason": reason}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SUPPLIER_MANAGE_PROFILE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="set_supplier_active",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(Supplier, authorization, replay[1], "El proveedor")
        row = _get(Supplier, authorization, supplier_id, "El proveedor")
        Supplier.objects.filter(pk=row.pk).update(
            status=Supplier.Status.ACTIVE if active else Supplier.Status.INACTIVE,
            inactive_reason=None if active else reason.strip(),
            inactive_at=None if active else timezone.now(),
        )
        row.refresh_from_db()
        _event(
            authorization,
            "supplier",
            row.pk,
            "supplier_activated" if active else "supplier_inactivated",
            payload,
        )
        _complete(
            authorization,
            command_type="set_supplier_active",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="supplier",
            result_reference=row.pk,
        )
        return row


def link_supplier_contact(
    actor: User,
    organization_reference: UUID | str,
    *,
    supplier_id: UUID | str,
    person_id: UUID | str,
    responsibility: str,
    is_primary: bool,
    valid_from: date | None = None,
    idempotency_key: UUID,
) -> SupplierContact:
    payload = {
        "supplier_id": supplier_id,
        "person_id": person_id,
        "responsibility": responsibility,
        "is_primary": is_primary,
        "valid_from": valid_from,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SUPPLIER_LINK_CONTACT
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="link_supplier_contact",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(SupplierContact, authorization, replay[1], "El contacto")
        supplier = _get(Supplier, authorization, supplier_id, "El proveedor")
        if supplier.status != Supplier.Status.ACTIVE:
            raise invalid("No se enlazan contactos nuevos a un proveedor inactivo.")
        canonical_person_id = people_port.lock_canonical_person_id(
            authorization.organization_id, _uuid(person_id, "La persona")
        )
        row = SupplierContact.objects.create(
            organization_id=authorization.organization_id,
            supplier=supplier,
            person_id=canonical_person_id,
            responsibility=responsibility.strip(),
            valid_from=valid_from or date.today(),
            is_primary=is_primary,
            linked_by_membership_id=authorization.membership_id,
        )
        _event(authorization, "supplier", supplier.pk, "supplier_contact_linked", payload)
        _complete(
            authorization,
            command_type="link_supplier_contact",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="supplier_contact",
            result_reference=row.pk,
        )
        return row


def inactivate_supplier_contact(
    actor: User,
    organization_reference: UUID | str,
    *,
    contact_id: UUID | str,
    valid_until: date,
    idempotency_key: UUID,
) -> SupplierContact:
    payload = {"contact_id": contact_id, "valid_until": valid_until}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SUPPLIER_LINK_CONTACT
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="inactivate_supplier_contact",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(SupplierContact, authorization, replay[1], "El contacto")
        row = _get(SupplierContact, authorization, contact_id, "El contacto")
        if not row.is_active or valid_until < row.valid_from:
            raise conflict("contact_validity_conflict", "El contacto ya no está vigente.")
        SupplierContact.objects.filter(pk=row.pk).update(
            is_active=False, is_primary=False, valid_until=valid_until
        )
        row.refresh_from_db()
        _event(authorization, "supplier", row.supplier_id, "supplier_contact_inactivated", payload)
        _complete(
            authorization,
            command_type="inactivate_supplier_contact",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="supplier_contact",
            result_reference=row.pk,
        )
        return row


def add_supplier_term(
    actor: User,
    organization_reference: UUID | str,
    *,
    supplier_id: UUID | str,
    valid_from: date,
    valid_until: date | None,
    payment_terms: str,
    lead_time_days: int,
    notes: str,
    idempotency_key: UUID,
) -> SupplierTermRevision:
    payload = {
        "supplier_id": supplier_id,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "payment_terms": payment_terms,
        "lead_time_days": lead_time_days,
        "notes": notes,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SUPPLIER_MANAGE_TERMS
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="add_supplier_term",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(SupplierTermRevision, authorization, replay[1], "Los términos")
        supplier = _get(Supplier, authorization, supplier_id, "El proveedor")
        if supplier.status != Supplier.Status.ACTIVE:
            raise invalid("No se agregan términos nuevos a un proveedor inactivo.")
        _lock(f"resources:{authorization.organization_id}:supplier:{supplier.pk}:terms")
        revision = (
            SupplierTermRevision.objects.filter(
                organization_id=authorization.organization_id, supplier=supplier
            ).aggregate(value=Max("revision"))["value"]
            or 0
        ) + 1
        row = SupplierTermRevision.objects.create(
            organization_id=authorization.organization_id,
            supplier=supplier,
            revision=revision,
            valid_from=valid_from,
            valid_until=valid_until,
            payment_terms=payment_terms.strip(),
            lead_time_days=lead_time_days,
            notes=notes.strip(),
            recorded_by_membership_id=authorization.membership_id,
        )
        _complete(
            authorization,
            command_type="add_supplier_term",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="supplier_term",
            result_reference=row.pk,
        )
        return row


def create_resource(
    actor: User,
    organization_reference: UUID | str,
    *,
    name: str,
    nature: str,
    base_unit_id: UUID | str,
    declared_capacity: Decimal | int | str | None,
    idempotency_key: UUID,
) -> Resource:
    payload = {
        "name": name,
        "nature": nature,
        "base_unit_id": base_unit_id,
        "declared_capacity": declared_capacity,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_MANAGE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="create_resource",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(Resource, authorization, replay[1], "El recurso")
        unit = _get(UnitDefinition, authorization, base_unit_id, "La unidad base")
        if nature not in Resource.Nature.values:
            raise invalid("La naturaleza del recurso no es válida.")
        if nature == Resource.Nature.SUPPLIED_SERVICE and unit.dimension not in (
            UnitDefinition.Dimension.COUNT,
            UnitDefinition.Dimension.DURATION,
        ):
            raise invalid("Un servicio solo admite unidad de conteo o duración.")
        if (
            nature != Resource.Nature.SUPPLIED_SERVICE
            and unit.dimension == UnitDefinition.Dimension.DURATION
        ):
            raise invalid("La duración se reserva para servicios suministrados.")
        if nature != Resource.Nature.SUPPLIED_SERVICE and declared_capacity is not None:
            raise invalid("Solo un servicio suministrado admite capacidad declarada.")
        normalized_name = " ".join(name.casefold().split())
        row = Resource.objects.create(
            organization_id=authorization.organization_id,
            name=name.strip(),
            normalized_name=normalized_name,
            nature=nature,
            base_unit=unit,
            declared_capacity=None if declared_capacity is None else _quantity(declared_capacity),
            created_by_membership_id=authorization.membership_id,
        )
        _event(authorization, "resource", row.pk, "resource_created", payload)
        _complete(
            authorization,
            command_type="create_resource",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="resource",
            result_reference=row.pk,
        )
        return row


def set_resource_active(
    actor: User,
    organization_reference: UUID | str,
    *,
    resource_id: UUID | str,
    active: bool,
    reason: str,
    idempotency_key: UUID,
) -> Resource:
    payload = {"resource_id": resource_id, "active": active, "reason": reason}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_MANAGE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="set_resource_active",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(Resource, authorization, replay[1], "El recurso")
        row = _get(Resource, authorization, resource_id, "El recurso")
        Resource.objects.filter(pk=row.pk).update(
            is_active=active,
            inactive_reason=None if active else reason.strip(),
            inactive_at=None if active else timezone.now(),
        )
        row.refresh_from_db()
        _event(
            authorization,
            "resource",
            row.pk,
            "resource_activated" if active else "resource_inactivated",
            payload,
        )
        _complete(
            authorization,
            command_type="set_resource_active",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="resource",
            result_reference=row.pk,
        )
        return row


def add_supplier_offering(
    actor: User,
    organization_reference: UUID | str,
    *,
    supplier_id: UUID | str,
    resource_id: UUID | str,
    supplier_reference: str,
    minimum_quantity: Decimal | int | str,
    valid_from: date,
    valid_until: date | None,
    idempotency_key: UUID,
) -> SupplierOffering:
    payload = {
        "supplier_id": supplier_id,
        "resource_id": resource_id,
        "supplier_reference": supplier_reference,
        "minimum_quantity": minimum_quantity,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SUPPLIER_MANAGE_OFFERING
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="add_supplier_offering",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(SupplierOffering, authorization, replay[1], "La oferta")
        supplier = _get(Supplier, authorization, supplier_id, "El proveedor")
        resource = _get(Resource, authorization, resource_id, "El recurso")
        if supplier.status != Supplier.Status.ACTIVE or not resource.is_active:
            raise invalid("La oferta requiere proveedor y recurso activos.")
        row = SupplierOffering.objects.create(
            organization_id=authorization.organization_id,
            supplier=supplier,
            resource=resource,
            supplier_reference=supplier_reference.strip(),
            minimum_quantity=_quantity(minimum_quantity),
            valid_from=valid_from,
            valid_until=valid_until,
            recorded_by_membership_id=authorization.membership_id,
        )
        _complete(
            authorization,
            command_type="add_supplier_offering",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="supplier_offering",
            result_reference=row.pk,
        )
        return row


def set_supplier_offering_active(
    actor: User,
    organization_reference: UUID | str,
    *,
    offering_id: UUID | str,
    active: bool,
    reason: str,
    idempotency_key: UUID,
) -> SupplierOffering:
    payload = {"offering_id": offering_id, "active": active, "reason": reason}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SUPPLIER_MANAGE_OFFERING
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="set_supplier_offering_active",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(SupplierOffering, authorization, replay[1], "La oferta")
        row = _get(SupplierOffering, authorization, offering_id, "La oferta")
        SupplierOffering.objects.filter(pk=row.pk).update(is_active=active)
        row.refresh_from_db()
        _event(
            authorization,
            "supplier",
            row.supplier_id,
            "supplier_offering_activated" if active else "supplier_offering_inactivated",
            payload,
        )
        _complete(
            authorization,
            command_type="set_supplier_offering_active",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="supplier_offering",
            result_reference=row.pk,
        )
        return row


def create_location(
    actor: User,
    organization_reference: UUID | str,
    *,
    venue_id: UUID | str,
    code: str,
    name: str,
    idempotency_key: UUID,
) -> InventoryLocation:
    payload = {"venue_id": venue_id, "code": code, "name": name}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_MANAGE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="create_location",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(InventoryLocation, authorization, replay[1], "La ubicación")
        venue_uuid = _uuid(venue_id, "La sede")
        venue = organizations_port.venue_for_resources(authorization, venue_uuid)
        if venue is None or not venue.is_active:
            raise unavailable("La sede")
        row = InventoryLocation.objects.create(
            organization_id=authorization.organization_id,
            venue_id=venue.id,
            code=code.strip().upper(),
            name=name.strip(),
        )
        _complete(
            authorization,
            command_type="create_location",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="inventory_location",
            result_reference=row.pk,
        )
        return row


def create_purchase(
    actor: User,
    organization_reference: UUID | str,
    *,
    supplier_id: UUID | str,
    reference: str,
    ordered_on: date | None,
    root_reservation_id: UUID | str | None = None,
    venue_id: UUID | str | None = None,
    notes: str,
    lines: list[dict[str, object]],
    idempotency_key: UUID,
) -> Purchase:
    payload = {
        "supplier_id": supplier_id,
        "reference": reference,
        "ordered_on": ordered_on,
        "root_reservation_id": root_reservation_id,
        "venue_id": venue_id,
        "notes": notes,
        "lines": lines,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PURCHASE_MANAGE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="create_purchase",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(Purchase, authorization, replay[1], "La compra")
        supplier = _get(Supplier, authorization, supplier_id, "El proveedor")
        if supplier.status != Supplier.Status.ACTIVE or not lines:
            raise invalid("La compra requiere un proveedor activo y al menos una línea.")
        if (root_reservation_id is None) != (venue_id is None):
            raise invalid("La compra por evento requiere raíz y sede juntas.")
        root_id = (
            None
            if root_reservation_id is None
            else _uuid(root_reservation_id, "La raíz de reserva")
        )
        historical_venue_id = None if venue_id is None else _uuid(venue_id, "La sede")
        if (
            historical_venue_id is not None
            and organizations_port.venue_for_resources(authorization, historical_venue_id) is None
        ):
            raise unavailable("La sede")
        row = Purchase.objects.create(
            organization_id=authorization.organization_id,
            supplier=supplier,
            reference=reference.strip(),
            status=Purchase.Status.ORDERED if ordered_on else Purchase.Status.DRAFT,
            ordered_on=ordered_on,
            root_reservation_id=root_id,
            venue_id=historical_venue_id,
            notes=notes.strip(),
            created_by_membership_id=authorization.membership_id,
        )
        for position, item in enumerate(lines, start=1):
            procurement_amount = cast(Decimal | str | None, item.get("procurement_unit_amount"))
            resource = _get(Resource, authorization, cast(Any, item["resource_id"]), "El recurso")
            if not resource.is_active:
                raise invalid("La compra no admite recursos inactivos.")
            PurchaseLine.objects.create(
                organization_id=authorization.organization_id,
                purchase=row,
                position=position,
                resource=resource,
                ordered_quantity=_quantity(cast(Any, item["quantity"])),
                procurement_unit_amount=procurement_amount,
                procurement_currency=str(item.get("procurement_currency"))
                if procurement_amount is not None
                else None,
                description=str(item.get("description", "")).strip(),
            )
        _event(authorization, "purchase", row.pk, "purchase_created", payload)
        _complete(
            authorization,
            command_type="create_purchase",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="purchase",
            result_reference=row.pk,
        )
        return row


def _create_movement(
    authorization: TenantAuthorization,
    *,
    resource: Resource,
    location: InventoryLocation,
    kind: str,
    quantity: Decimal,
    direction: str,
    reason: str,
    transfer_group: UUID | None = None,
    other_location_id: UUID | None = None,
    source_kind: str | None = None,
    source_id: UUID | None = None,
    corrects: StockMovement | None = None,
) -> StockMovement:
    effect = quantity if direction == StockMovement.Direction.INCREASE else -quantity
    return StockMovement.objects.create(
        organization_id=authorization.organization_id,
        resource=resource,
        location=location,
        kind=kind,
        direction=direction,
        quantity=quantity,
        effect=effect,
        reason=reason.strip(),
        transfer_group=transfer_group,
        other_location_id=other_location_id,
        source_kind=source_kind,
        source_id=source_id,
        corrects=corrects,
        recorded_by_membership_id=authorization.membership_id,
        occurred_at=timezone.now(),
    )


def record_movement(
    actor: User,
    organization_reference: UUID | str,
    *,
    resource_id: UUID | str,
    location_id: UUID | str,
    kind: str,
    quantity: Decimal | int | str,
    direction: str | None,
    reason: str,
    other_location_id: UUID | str | None,
    corrects_id: UUID | str | None,
    idempotency_key: UUID,
) -> StockMovement:
    payload = {
        "resource_id": resource_id,
        "location_id": location_id,
        "kind": kind,
        "quantity": quantity,
        "direction": direction,
        "reason": reason,
        "other_location_id": other_location_id,
        "corrects_id": corrects_id,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.INVENTORY_RECORD_MOVEMENT
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="record_movement",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(StockMovement, authorization, replay[1], "El movimiento")
        resource = _get(Resource, authorization, resource_id, "El recurso")
        if resource.nature not in (
            Resource.Nature.CONSUMABLE,
            Resource.Nature.REUSABLE_POOL,
            Resource.Nature.SERIALIZED_ASSET,
        ):
            raise invalid("Un servicio suministrado no admite movimientos físicos.")
        normalized = _quantity(
            quantity, integral=resource.nature == Resource.Nature.SERIALIZED_ASSET
        )
        location = _get(InventoryLocation, authorization, location_id, "La ubicación")
        if kind == "transfer":
            if other_location_id is None:
                raise invalid("El traslado requiere una ubicación destino.")
            target = _get(
                InventoryLocation, authorization, other_location_id, "La ubicación destino"
            )
            keys = sorted((location.pk, target.pk), key=str)
            for key in keys:
                _lock(
                    f"resources:{authorization.organization_id}:resource:{resource.pk}:location:{key}"
                )
            group = uuid4()
            first = _create_movement(
                authorization,
                resource=resource,
                location=location,
                kind=StockMovement.Kind.TRANSFER_OUT,
                quantity=normalized,
                direction=StockMovement.Direction.DECREASE,
                reason=reason,
                transfer_group=group,
                other_location_id=target.pk,
            )
            _create_movement(
                authorization,
                resource=resource,
                location=target,
                kind=StockMovement.Kind.TRANSFER_IN,
                quantity=normalized,
                direction=StockMovement.Direction.INCREASE,
                reason=reason,
                transfer_group=group,
                other_location_id=location.pk,
            )
        else:
            actual_direction: str
            valid = set(StockMovement.Kind.values) - {
                StockMovement.Kind.TRANSFER_IN,
                StockMovement.Kind.TRANSFER_OUT,
            }
            if kind not in valid:
                raise invalid("El tipo de movimiento no es válido.")
            if kind in (StockMovement.Kind.ENTRY, StockMovement.Kind.RETURN):
                actual_direction = StockMovement.Direction.INCREASE
            elif kind == StockMovement.Kind.EXIT:
                actual_direction = StockMovement.Direction.DECREASE
            elif direction in StockMovement.Direction.values:
                actual_direction = direction
            else:
                raise invalid("El ajuste o corrección requiere dirección y razón.")
            corrects = None
            if kind == StockMovement.Kind.CORRECTION:
                if corrects_id is None:
                    raise invalid("La corrección debe enlazar el movimiento original.")
                corrects = _get(StockMovement, authorization, corrects_id, "El movimiento original")
            first = _create_movement(
                authorization,
                resource=resource,
                location=location,
                kind=kind,
                quantity=normalized,
                direction=actual_direction,
                reason=reason,
                corrects=corrects,
            )
        _complete(
            authorization,
            command_type="record_movement",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="stock_movement",
            result_reference=first.pk,
        )
        return first


def confirm_receipt_line(
    actor: User,
    organization_reference: UUID | str,
    *,
    purchase_line_id: UUID | str,
    receipt_reference: str,
    received_on: date,
    kind: str,
    quantity: Decimal | int | str,
    destination_location_id: UUID | str | None,
    serial_numbers: list[str],
    notes: str,
    idempotency_key: UUID,
) -> SupplyReceiptLine:
    payload = {
        "purchase_line_id": purchase_line_id,
        "receipt_reference": receipt_reference,
        "received_on": received_on,
        "kind": kind,
        "quantity": quantity,
        "destination_location_id": destination_location_id,
        "serial_numbers": serial_numbers,
        "notes": notes,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PURCHASE_RECEIVE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="confirm_receipt_line",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(SupplyReceiptLine, authorization, replay[1], "La línea de recepción")
        purchase_line = _get(PurchaseLine, authorization, purchase_line_id, "La línea de compra")
        resource = purchase_line.resource
        normalized = _quantity(
            quantity, integral=resource.nature == Resource.Nature.SERIALIZED_ASSET
        )
        expected_kind = (
            SupplyReceiptLine.Kind.SERVICE_FULFILLED
            if resource.nature == Resource.Nature.SUPPLIED_SERVICE
            else SupplyReceiptLine.Kind.GOODS_RECEIVED
        )
        if kind != expected_kind:
            raise invalid("La recepción no corresponde a la naturaleza del recurso.")
        location = None
        if kind == SupplyReceiptLine.Kind.GOODS_RECEIVED:
            if destination_location_id is None:
                raise invalid("Los bienes recibidos requieren ubicación destino.")
            location = _get(
                InventoryLocation, authorization, destination_location_id, "La ubicación destino"
            )
        elif destination_location_id is not None or serial_numbers:
            raise invalid("Un servicio cumplido no admite ubicación, stock ni series.")
        if resource.nature == Resource.Nature.SERIALIZED_ASSET and len(serial_numbers) != int(
            normalized
        ):
            raise invalid("La cantidad debe cuadrar exactamente con las unidades serializadas.")
        if resource.nature != Resource.Nature.SERIALIZED_ASSET and serial_numbers:
            raise invalid("Solo un activo serializado admite números de serie.")
        receipt, _ = SupplyReceipt.objects.get_or_create(
            organization_id=authorization.organization_id,
            reference=receipt_reference.strip(),
            defaults={
                "purchase": purchase_line.purchase,
                "received_on": received_on,
                "notes": notes.strip(),
                "recorded_by_membership_id": authorization.membership_id,
            },
        )
        if receipt.purchase_id != purchase_line.purchase_id:
            raise conflict(
                "receipt_reference_conflict", "La referencia ya pertenece a otra compra."
            )
        row = SupplyReceiptLine.objects.create(
            organization_id=authorization.organization_id,
            receipt=receipt,
            purchase_line=purchase_line,
            resource=resource,
            kind=kind,
            quantity=normalized,
            destination_location=location,
            confirmed_at=timezone.now(),
            recorded_by_membership_id=authorization.membership_id,
        )
        if kind == SupplyReceiptLine.Kind.GOODS_RECEIVED:
            assert location is not None
            _create_movement(
                authorization,
                resource=resource,
                location=location,
                kind=StockMovement.Kind.ENTRY,
                quantity=normalized,
                direction=StockMovement.Direction.INCREASE,
                reason=f"Recepción {receipt.reference}",
                source_kind="resources_receipt_line",
                source_id=row.pk,
            )
            for serial in serial_numbers:
                SerializedAsset.objects.create(
                    organization_id=authorization.organization_id,
                    resource=resource,
                    receipt_line=row,
                    location=location,
                    serial_number=serial.strip(),
                )
        _event(authorization, "supply_receipt_line", row.pk, "receipt_line_confirmed", payload)
        _complete(
            authorization,
            command_type="confirm_receipt_line",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="supply_receipt_line",
            result_reference=row.pk,
        )
        return row


def create_requirement(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    resource_id: UUID | str,
    quantity: Decimal | int | str,
    reason: str,
    idempotency_key: UUID,
    operational_window_id: UUID | str | None = None,
) -> ResourceRequirement:
    payload = {
        "reservation_id": reservation_id,
        "resource_id": resource_id,
        "quantity": quantity,
        "reason": reason,
        "operational_window_id": operational_window_id,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_RESERVE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="create_requirement",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(ResourceRequirement, authorization, replay[1], "El requerimiento")
        reservation_uuid = _uuid(reservation_id, "La reserva")
        schedule = scheduling_port.resource_schedule(authorization, reservation_uuid)
        if schedule is None or schedule.status not in ("provisional", "confirmed"):
            raise unavailable("La reserva vigente")
        resource = _get(Resource, authorization, resource_id, "El recurso")
        if not resource.is_active:
            raise invalid("El recurso inactivo no admite requerimientos nuevos.")
        normalized = _quantity(
            quantity, integral=resource.nature == Resource.Nature.SERIALIZED_ASSET
        )
        temporal_source = ResourceRequirement.TemporalSource.SCHEDULING_EVENT_INTERVAL
        operation_window_uuid = None
        resource_interval = Range(schedule.starts_at, schedule.ends_at, bounds="[)")
        if operational_window_id is not None:
            from claridez.operations.public import operational_window_for_resources

            operation_window_uuid = _uuid(operational_window_id, "La ventana operacional")
            window = operational_window_for_resources(
                authorization.organization_id, operation_window_uuid, lock=True
            )
            if (
                window is None
                or window.reservation_id != reservation_uuid
                or window.root_reservation_id != schedule.root_id
                or window.resource_id != resource.pk
                or window.quantity != normalized
            ):
                raise unavailable("La ventana operacional")
            temporal_source = ResourceRequirement.TemporalSource.OPERATIONS_WINDOW
            resource_interval = Range(window.starts_at, window.ends_at, bounds="[)")
        available = _available_quantity(authorization, resource, interval=resource_interval)
        row = ResourceRequirement.objects.create(
            organization_id=authorization.organization_id,
            root_reservation_id=schedule.root_id,
            reservation_id=schedule.reservation_id,
            resource=resource,
            quantity=normalized,
            resource_interval=resource_interval,
            temporal_source=temporal_source,
            operational_window_id=operation_window_uuid,
            status=(
                ResourceRequirement.Status.SHORTAGE
                if available is None or available < normalized
                else ResourceRequirement.Status.OPEN
            ),
            reason=reason.strip(),
            created_by_membership_id=authorization.membership_id,
        )
        _complete(
            authorization,
            command_type="create_requirement",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="resource_requirement",
            result_reference=row.pk,
        )
        return row


def _available_quantity(
    authorization: TenantAuthorization,
    resource: Resource,
    *,
    interval: Range[datetime] | None = None,
    location: InventoryLocation | None = None,
) -> Decimal | None:
    if resource.nature == Resource.Nature.CONSUMABLE:
        stock = (
            StockBalance.objects.filter(
                organization_id=authorization.organization_id,
                resource=resource,
                **({"location": location} if location is not None else {}),
            ).aggregate(value=Sum("quantity"))["value"]
            or ZERO
        )
        reserved = (
            ResourceCapacityAllocation.objects.filter(
                organization_id=authorization.organization_id,
                resource=resource,
                is_active=True,
                basis=ResourceCapacityAllocation.Basis.SCHEDULING,
                assignment__status=ResourceAssignment.Status.RESERVED,
                **({"assignment__source_location": location} if location is not None else {}),
            ).aggregate(value=Sum("quantity"))["value"]
            or ZERO
        )
        return stock - reserved
    if resource.nature == Resource.Nature.REUSABLE_POOL:
        effective_interval = interval or Range(
            timezone.now(), timezone.now() + timedelta(microseconds=1), bounds="[)"
        )
        stock = (
            StockBalance.objects.filter(
                organization_id=authorization.organization_id,
                resource=resource,
                **({"location": location} if location is not None else {}),
            ).aggregate(value=Sum("quantity"))["value"]
            or ZERO
        )
        custody = (
            ResourceCapacityAllocation.objects.filter(
                organization_id=authorization.organization_id,
                resource=resource,
                is_active=True,
                basis=ResourceCapacityAllocation.Basis.CUSTODY,
                **({"assignment__source_location": location} if location is not None else {}),
            ).aggregate(value=Sum("quantity"))["value"]
            or ZERO
        )
        competing = (
            ResourceCapacityAllocation.objects.filter(
                organization_id=authorization.organization_id,
                resource=resource,
                is_active=True,
                resource_interval__overlap=effective_interval,
                **({"assignment__source_location": location} if location is not None else {}),
            ).aggregate(value=Sum("quantity"))["value"]
            or ZERO
        )
        unavailable_amount = (
            ResourceUnavailability.objects.filter(
                organization_id=authorization.organization_id,
                resource=resource,
                is_active=True,
                unavailable_interval__overlap=effective_interval,
                **({"location": location} if location is not None else {}),
            ).aggregate(value=Sum("quantity"))["value"]
            or ZERO
        )
        return stock + custody - competing - unavailable_amount
    if resource.nature == Resource.Nature.SERIALIZED_ASSET:
        effective_interval = interval or Range(
            timezone.now(), timezone.now() + timedelta(microseconds=1), bounds="[)"
        )
        allocations = ResourceCapacityAllocation.objects.filter(
            organization_id=authorization.organization_id,
            serialized_asset_id=OuterRef("pk"),
            is_active=True,
            resource_interval__overlap=effective_interval,
        )
        unavailability = ResourceUnavailability.objects.filter(
            organization_id=authorization.organization_id,
            serialized_asset_id=OuterRef("pk"),
            is_active=True,
            unavailable_interval__overlap=effective_interval,
        )
        assets = (
            SerializedAsset.objects.filter(
                organization_id=authorization.organization_id,
                resource=resource,
                status=SerializedAsset.Status.AVAILABLE,
                **({"location": location} if location is not None else {}),
            )
            .annotate(
                has_allocation=Exists(allocations),
                has_unavailability=Exists(unavailability),
            )
            .filter(has_allocation=False, has_unavailability=False)
            .count()
        )
        return Decimal(assets)
    if resource.declared_capacity is None:
        return None
    if interval is None:
        return resource.declared_capacity
    allocated = (
        ResourceCapacityAllocation.objects.filter(
            organization_id=authorization.organization_id,
            resource=resource,
            is_active=True,
            resource_interval__overlap=interval,
        ).aggregate(value=Sum("quantity"))["value"]
        or ZERO
    )
    unavailable_amount = (
        ResourceUnavailability.objects.filter(
            organization_id=authorization.organization_id,
            resource=resource,
            is_active=True,
            unavailable_interval__overlap=interval,
        ).aggregate(value=Sum("quantity"))["value"]
        or ZERO
    )
    return resource.declared_capacity - allocated - unavailable_amount


def _serialized_asset_is_available(
    authorization: TenantAuthorization,
    asset: SerializedAsset,
    interval: Range[datetime],
) -> bool:
    if asset.status != SerializedAsset.Status.AVAILABLE:
        return False
    return not (
        ResourceCapacityAllocation.objects.filter(
            organization_id=authorization.organization_id,
            serialized_asset=asset,
            is_active=True,
            resource_interval__overlap=interval,
        ).exists()
        or ResourceUnavailability.objects.filter(
            organization_id=authorization.organization_id,
            serialized_asset=asset,
            is_active=True,
            unavailable_interval__overlap=interval,
        ).exists()
    )


def reserve_resource(
    actor: User,
    organization_reference: UUID | str,
    *,
    requirement_id: UUID | str,
    source_location_id: UUID | str | None,
    serialized_asset_id: UUID | str | None,
    idempotency_key: UUID,
) -> ResourceAssignment:
    payload = {
        "requirement_id": requirement_id,
        "source_location_id": source_location_id,
        "serialized_asset_id": serialized_asset_id,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_RESERVE
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="reserve_resource",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(ResourceAssignment, authorization, replay[1], "La asignación")
        requirement = _get(ResourceRequirement, authorization, requirement_id, "El requerimiento")
        resource = requirement.resource
        if not resource.is_active:
            raise invalid("El recurso inactivo no admite reservas nuevas.")
        _lock(f"resources:{authorization.organization_id}:resource:{resource.pk}")
        Resource.objects.select_for_update().get(pk=resource.pk)
        location = (
            None
            if source_location_id is None
            else _get(InventoryLocation, authorization, source_location_id, "La ubicación")
        )
        if (
            resource.nature
            in (
                Resource.Nature.CONSUMABLE,
                Resource.Nature.REUSABLE_POOL,
                Resource.Nature.SERIALIZED_ASSET,
            )
            and location is None
        ):
            raise invalid("El recurso físico requiere ubicación de origen.")
        asset = None
        if resource.nature == Resource.Nature.SERIALIZED_ASSET:
            if serialized_asset_id is None:
                raise invalid("El recurso requiere seleccionar un activo serializado.")
            asset = _get(SerializedAsset, authorization, serialized_asset_id, "El activo")
            asset = SerializedAsset.objects.select_for_update().get(pk=asset.pk)
            if (
                asset.resource_id != resource.pk
                or asset.location_id != cast(InventoryLocation, location).pk
            ):
                raise invalid("El activo no corresponde al recurso y ubicación.")
            if not _serialized_asset_is_available(
                authorization, asset, requirement.resource_interval
            ):
                ResourceRequirement.objects.filter(pk=requirement.pk).update(
                    status=ResourceRequirement.Status.SHORTAGE
                )
                raise conflict(
                    "resource_shortage",
                    "El activo seleccionado no está disponible en el intervalo solicitado.",
                )
        elif serialized_asset_id is not None:
            raise invalid("Solo un activo serializado admite selección individual.")
        available = _available_quantity(
            authorization, resource, interval=requirement.resource_interval, location=location
        )
        if available is None or available < requirement.quantity:
            ResourceRequirement.objects.filter(pk=requirement.pk).update(
                status=ResourceRequirement.Status.SHORTAGE
            )
            raise conflict(
                "resource_shortage",
                "No existe capacidad declarada o disponible; se conserva el faltante.",
            )
        row = ResourceAssignment.objects.create(
            organization_id=authorization.organization_id,
            requirement=requirement,
            root_reservation_id=requirement.root_reservation_id,
            reservation_id=requirement.reservation_id,
            resource=resource,
            serialized_asset=asset,
            source_location=location,
            quantity=requirement.quantity,
            resource_interval=requirement.resource_interval,
            recorded_by_membership_id=authorization.membership_id,
        )
        ResourceCapacityAllocation.objects.create(
            organization_id=authorization.organization_id,
            assignment=row,
            reservation_id=row.reservation_id,
            resource=resource,
            serialized_asset=asset,
            quantity=row.quantity,
            resource_interval=row.resource_interval,
        )
        ResourceRequirement.objects.filter(pk=requirement.pk).update(
            status=ResourceRequirement.Status.SATISFIED
        )
        _event(authorization, "resource_assignment", row.pk, "resource_reserved", payload)
        _complete(
            authorization,
            command_type="reserve_resource",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="resource_assignment",
            result_reference=row.pk,
        )
        return row


def execute_assignment(
    actor: User,
    organization_reference: UUID | str,
    *,
    assignment_id: UUID | str,
    action: str,
    notes: str,
    idempotency_key: UUID,
) -> ResourceAssignment:
    payload = {"assignment_id": assignment_id, "action": action, "notes": notes}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.INVENTORY_RECORD_MOVEMENT
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="execute_assignment",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(ResourceAssignment, authorization, replay[1], "La asignación")
        assignment = _get(ResourceAssignment, authorization, assignment_id, "La asignación")
        _lock(f"resources:{authorization.organization_id}:resource:{assignment.resource_id}")
        assignment = ResourceAssignment.objects.select_for_update().get(pk=assignment.pk)
        resource = assignment.resource
        allocation = ResourceCapacityAllocation.objects.select_for_update().get(
            assignment=assignment
        )
        if action == "issue":
            if resource.nature == Resource.Nature.SUPPLIED_SERVICE:
                raise invalid("Un servicio se cumple; no se entrega como inventario.")
            if (
                assignment.status != ResourceAssignment.Status.RESERVED
                or assignment.source_location_id is None
            ):
                raise conflict("assignment_state_conflict", "La asignación no puede entregarse.")
            source_location = _get(
                InventoryLocation,
                authorization,
                assignment.source_location_id,
                "La ubicación de origen",
            )
            _create_movement(
                authorization,
                resource=resource,
                location=source_location,
                kind=StockMovement.Kind.EXIT,
                quantity=assignment.quantity,
                direction=StockMovement.Direction.DECREASE,
                reason=notes or "Salida por evento",
                source_kind="resource_assignment",
                source_id=assignment.pk,
            )
            if resource.nature == Resource.Nature.CONSUMABLE:
                new_status = ResourceAssignment.Status.ISSUED
                allocation.is_active = False
                allocation.save(update_fields=["is_active"])
            else:
                new_status = ResourceAssignment.Status.CUSTODY
                ResourceAssignment.objects.filter(pk=assignment.pk).update(status=new_status)
                allocation.basis = ResourceCapacityAllocation.Basis.CUSTODY
                allocation.resource_interval = Range(timezone.now(), None, bounds="[)")
                allocation.save(update_fields=["basis", "resource_interval"])
                if assignment.serialized_asset_id:
                    SerializedAsset.objects.filter(pk=assignment.serialized_asset_id).update(
                        status=SerializedAsset.Status.CUSTODY
                    )
            CustodyEvent.objects.create(
                organization_id=authorization.organization_id,
                assignment=assignment,
                serialized_asset=assignment.serialized_asset,
                kind=CustodyEvent.Kind.DELIVERY,
                occurred_at=timezone.now(),
                notes=notes.strip(),
                recorded_by_membership_id=authorization.membership_id,
            )
        elif action == "fulfill":
            if (
                resource.nature != Resource.Nature.SUPPLIED_SERVICE
                or assignment.status != ResourceAssignment.Status.RESERVED
            ):
                raise conflict(
                    "assignment_state_conflict", "La asignación no puede marcarse cumplida."
                )
            new_status = ResourceAssignment.Status.FULFILLED
            allocation.is_active = False
            allocation.save(update_fields=["is_active"])
        elif action == "return":
            if (
                resource.nature == Resource.Nature.CONSUMABLE
                or assignment.status != ResourceAssignment.Status.CUSTODY
            ):
                raise conflict("assignment_state_conflict", "La asignación no admite devolución.")
            if assignment.source_location_id is None:
                raise invalid("La devolución requiere la ubicación original.")
            source_location = _get(
                InventoryLocation,
                authorization,
                assignment.source_location_id,
                "La ubicación de origen",
            )
            _create_movement(
                authorization,
                resource=resource,
                location=source_location,
                kind=StockMovement.Kind.RETURN,
                quantity=assignment.quantity,
                direction=StockMovement.Direction.INCREASE,
                reason=notes or "Devolución de evento",
                source_kind="resource_assignment_return",
                source_id=assignment.pk,
            )
            new_status = ResourceAssignment.Status.RETURNED
            allocation.is_active = False
            allocation.save(update_fields=["is_active"])
            if assignment.serialized_asset_id:
                SerializedAsset.objects.filter(pk=assignment.serialized_asset_id).update(
                    status=SerializedAsset.Status.AVAILABLE
                )
            CustodyEvent.objects.create(
                organization_id=authorization.organization_id,
                assignment=assignment,
                serialized_asset=assignment.serialized_asset,
                kind=CustodyEvent.Kind.RETURN,
                occurred_at=timezone.now(),
                notes=notes.strip(),
                recorded_by_membership_id=authorization.membership_id,
            )
        else:
            raise invalid("La acción de asignación no es válida.")
        ResourceAssignment.objects.filter(pk=assignment.pk).update(status=new_status)
        assignment.refresh_from_db()
        _event(authorization, "resource_assignment", assignment.pk, f"assignment_{action}", payload)
        _complete(
            authorization,
            command_type="execute_assignment",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="resource_assignment",
            result_reference=assignment.pk,
        )
        return assignment


def record_unavailability(
    actor: User,
    organization_reference: UUID | str,
    *,
    resource_id: UUID | str,
    serialized_asset_id: UUID | str | None,
    location_id: UUID | str | None = None,
    quantity: Decimal | int | str,
    starts_at: datetime,
    ends_at: datetime,
    reason: str,
    maintenance_description: str | None,
    corrects_id: UUID | str | None = None,
    idempotency_key: UUID,
) -> ResourceUnavailability:
    payload = {
        "resource_id": resource_id,
        "serialized_asset_id": serialized_asset_id,
        "location_id": location_id,
        "quantity": quantity,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "reason": reason,
        "maintenance_description": maintenance_description,
        "corrects_id": corrects_id,
    }
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_MAINTAIN
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="record_unavailability",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(ResourceUnavailability, authorization, replay[1], "La indisponibilidad")
        if ends_at <= starts_at:
            raise invalid("El intervalo de indisponibilidad debe ser [inicio, fin).")
        resource = _get(Resource, authorization, resource_id, "El recurso")
        asset = (
            None
            if serialized_asset_id is None
            else _get(SerializedAsset, authorization, serialized_asset_id, "El activo")
        )
        if asset is not None and asset.resource_id != resource.pk:
            raise invalid("El activo no corresponde al recurso.")
        location = (
            None
            if location_id is None
            else _get(InventoryLocation, authorization, location_id, "La ubicación")
        )
        if asset is not None:
            if location is None:
                location = asset.location
            elif asset.location_id != location.pk:
                raise invalid("La ubicación no corresponde al activo serializado.")
        if resource.nature != Resource.Nature.SUPPLIED_SERVICE and location is None:
            raise invalid("La indisponibilidad física requiere ubicación.")
        if resource.nature == Resource.Nature.SUPPLIED_SERVICE and location is not None:
            raise invalid("Un servicio suministrado no admite ubicación física.")
        corrects = (
            None
            if corrects_id is None
            else _get(ResourceUnavailability, authorization, corrects_id, "El hecho corregido")
        )
        if corrects is not None and (
            corrects.is_active
            or corrects.resource_id != resource.pk
            or corrects.serialized_asset_id != (None if asset is None else asset.pk)
            or corrects.location_id != (None if location is None else location.pk)
        ):
            raise invalid(
                "La corrección debe enlazar un hecho cerrado del mismo recurso y ubicación."
            )
        _lock(f"resources:{authorization.organization_id}:resource:{resource.pk}")
        if asset is not None:
            asset = SerializedAsset.objects.select_for_update().get(pk=asset.pk)
            if asset.status == SerializedAsset.Status.RETIRED:
                raise invalid("Un activo retirado no admite nuevas indisponibilidades.")
        row = ResourceUnavailability.objects.create(
            organization_id=authorization.organization_id,
            resource=resource,
            serialized_asset=asset,
            location=location,
            quantity=_quantity(quantity, integral=asset is not None),
            unavailable_interval=Range(starts_at, ends_at, bounds="[)"),
            reason=reason.strip(),
            corrects=corrects,
            recorded_by_membership_id=authorization.membership_id,
        )
        if maintenance_description:
            MaintenanceRecord.objects.create(
                organization_id=authorization.organization_id,
                resource=resource,
                serialized_asset=asset,
                unavailability=row,
                description=maintenance_description.strip(),
                recorded_by_membership_id=authorization.membership_id,
            )
        _event(authorization, "resource", resource.pk, "resource_unavailable", payload)
        _complete(
            authorization,
            command_type="record_unavailability",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="resource_unavailability",
            result_reference=row.pk,
        )
        return row


def close_unavailability(
    actor: User,
    organization_reference: UUID | str,
    *,
    unavailability_id: UUID | str,
    idempotency_key: UUID,
) -> ResourceUnavailability:
    payload = {"unavailability_id": unavailability_id}
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_MAINTAIN
    ) as authorization:
        replay = _command_replay(
            authorization,
            command_type="close_unavailability",
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay:
            return _get(ResourceUnavailability, authorization, replay[1], "La indisponibilidad")
        row = _get(ResourceUnavailability, authorization, unavailability_id, "La indisponibilidad")
        ResourceUnavailability.objects.filter(pk=row.pk).update(
            is_active=False, closed_at=timezone.now()
        )
        MaintenanceRecord.objects.filter(unavailability=row).update(
            status=MaintenanceRecord.Status.COMPLETED
        )
        row.refresh_from_db()
        _event(
            authorization, "resource", row.resource_id, "resource_availability_restored", payload
        )
        _complete(
            authorization,
            command_type="close_unavailability",
            idempotency_key=idempotency_key,
            payload=payload,
            result_type="resource_unavailability",
            result_reference=row.pk,
        )
        return row


def _row(row: Any, *fields: str) -> dict[str, Any]:
    result = {"id": row.pk}
    for field in fields:
        value = getattr(row, field)
        result[field] = _json(value)
    return result


def contextual_resource_availability(
    actor: User,
    organization_reference: UUID | str,
    *,
    event_request_id: UUID | str,
    resource_id: UUID | str,
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_READ_AVAILABILITY
    ) as authorization:
        context = scheduling_port.resource_availability_context(
            authorization, _uuid(event_request_id, "La solicitud")
        )
        if context is None:
            raise unavailable("La solicitud o reserva vigente")
        resource = _get(Resource, authorization, resource_id, "El recurso")
        requirements = ResourceRequirement.objects.filter(
            organization_id=authorization.organization_id,
            reservation_id=context.reservation_id,
            resource=resource,
        ).exclude(status=ResourceRequirement.Status.CANCELLED)
        required = requirements.aggregate(value=Sum("quantity"))["value"]
        if required is None:
            raise unavailable("El recurso en el contexto solicitado")
        interval = Range(context.starts_at, context.ends_at, bounds="[)")
        available = _available_quantity(authorization, resource, interval=interval)
        return {
            "event_request_id": context.event_request_id,
            "reservation_id": context.reservation_id,
            "resource_id": resource.pk,
            "starts_at": context.starts_at,
            "ends_at": context.ends_at,
            "unit": resource.base_unit.symbol,
            "required_quantity": required,
            "available_quantity": available,
            "shortage": available is None or available < required,
        }


def resources_overview(actor: User, organization_reference: UUID | str) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.RESOURCE_READ_AVAILABILITY
    ) as authorization:
        role_capabilities = capabilities_for_role(authorization.role)
        can_read_resources = Capability.RESOURCE_READ in role_capabilities
        can_read_suppliers = Capability.SUPPLIER_READ in role_capabilities
        can_read_purchases = Capability.PURCHASE_READ in role_capabilities
        resources = (
            list(
                Resource.objects.filter(
                    organization_id=authorization.organization_id
                ).select_related("base_unit")
            )
            if can_read_resources
            else []
        )
        result: dict[str, object] = {
            "organization_id": authorization.organization_id,
            "capabilities": sorted(
                capability.value
                for capability in role_capabilities
                if capability in P12_CAPABILITIES
            ),
            "availability": [
                {
                    "resource_id": row.pk,
                    "name": row.name,
                    "nature": row.nature,
                    "unit": row.base_unit.symbol,
                    "declared_capacity": _json(row.declared_capacity),
                    "available": _json(_available_quantity(authorization, row)),
                    "shortage": row.nature == Resource.Nature.SUPPLIED_SERVICE
                    and row.declared_capacity is None,
                }
                for row in Resource.objects.filter(
                    organization_id=authorization.organization_id, is_active=True
                ).select_related("base_unit")
            ]
            if can_read_resources
            else [],
            "resources": [
                {
                    **_row(row, "name", "nature", "is_active", "declared_capacity"),
                    "base_unit": {
                        "id": row.base_unit_id,
                        "code": row.base_unit.code,
                        "symbol": row.base_unit.symbol,
                        "dimension": row.base_unit.dimension,
                    },
                }
                for row in resources
            ],
            "units": [
                _row(row, "code", "name", "symbol", "dimension", "is_active")
                for row in UnitDefinition.objects.filter(
                    organization_id=authorization.organization_id
                )
            ]
            if can_read_resources
            else [],
            "conversions": [
                _row(
                    row,
                    "from_unit_id",
                    "to_unit_id",
                    "multiplier",
                    "revision",
                    "valid_from",
                    "valid_until",
                    "is_active",
                )
                for row in UnitConversion.objects.filter(
                    organization_id=authorization.organization_id
                )
            ]
            if can_read_resources
            else [],
            "locations": [
                _row(row, "venue_id", "code", "name", "is_active")
                for row in InventoryLocation.objects.filter(
                    organization_id=authorization.organization_id
                )
            ]
            if can_read_resources
            else [],
            "balances": [
                _row(row, "resource_id", "location_id", "quantity", "updated_at")
                for row in StockBalance.objects.filter(
                    organization_id=authorization.organization_id
                )
            ]
            if can_read_resources
            else [],
            "assets": [
                _row(row, "resource_id", "location_id", "serial_number", "status")
                for row in SerializedAsset.objects.filter(
                    organization_id=authorization.organization_id
                )
            ]
            if can_read_resources
            else [],
            "movements": [
                _row(
                    row,
                    "resource_id",
                    "location_id",
                    "kind",
                    "direction",
                    "quantity",
                    "reason",
                    "occurred_at",
                    "corrects_id",
                )
                for row in StockMovement.objects.filter(
                    organization_id=authorization.organization_id
                ).order_by("-occurred_at")[:100]
            ]
            if can_read_resources
            else [],
            "requirements": [
                _row(
                    row,
                    "root_reservation_id",
                    "reservation_id",
                    "resource_id",
                    "quantity",
                    "status",
                    "reason",
                )
                for row in ResourceRequirement.objects.filter(
                    organization_id=authorization.organization_id
                ).order_by("-created_at")[:100]
            ]
            if can_read_resources
            else [],
            "assignments": [
                _row(
                    row,
                    "root_reservation_id",
                    "reservation_id",
                    "resource_id",
                    "serialized_asset_id",
                    "quantity",
                    "status",
                )
                for row in ResourceAssignment.objects.filter(
                    organization_id=authorization.organization_id
                ).order_by("-created_at")[:100]
            ]
            if can_read_resources
            else [],
            "unavailability": [
                _row(
                    row,
                    "resource_id",
                    "serialized_asset_id",
                    "quantity",
                    "reason",
                    "is_active",
                    "closed_at",
                )
                for row in ResourceUnavailability.objects.filter(
                    organization_id=authorization.organization_id
                ).order_by("-created_at")[:100]
            ]
            if can_read_resources
            else [],
            "maintenance": [
                _row(
                    row,
                    "resource_id",
                    "serialized_asset_id",
                    "unavailability_id",
                    "status",
                    "description",
                )
                for row in MaintenanceRecord.objects.filter(
                    organization_id=authorization.organization_id
                ).order_by("-created_at")[:100]
            ]
            if can_read_resources
            else [],
        }
        result["suppliers"] = (
            [
                {
                    **_row(
                        row,
                        "legal_name",
                        "tax_identifier",
                        "internal_code",
                        "status",
                        "inactive_reason",
                    ),
                    "contacts": [
                        _row(
                            contact,
                            "person_id",
                            "responsibility",
                            "valid_from",
                            "valid_until",
                            "is_primary",
                            "is_active",
                        )
                        for contact in row.contacts.all()
                    ],
                    "terms": [
                        _row(
                            term,
                            "revision",
                            "valid_from",
                            "valid_until",
                            "payment_terms",
                            "lead_time_days",
                            "notes",
                        )
                        for term in row.term_revisions.all()
                    ],
                    "offerings": [
                        _row(
                            offering,
                            "resource_id",
                            "supplier_reference",
                            "minimum_quantity",
                            "valid_from",
                            "valid_until",
                            "is_active",
                        )
                        for offering in row.offerings.all()
                    ],
                }
                for row in Supplier.objects.filter(
                    organization_id=authorization.organization_id
                ).prefetch_related("contacts", "term_revisions", "offerings")
            ]
            if can_read_suppliers
            else []
        )
        result["purchases"] = (
            [
                {
                    **_row(
                        row,
                        "supplier_id",
                        "reference",
                        "status",
                        "ordered_on",
                        "root_reservation_id",
                        "venue_id",
                        "notes",
                    ),
                    "lines": [
                        _row(line, "resource_id", "position", "ordered_quantity", "description")
                        for line in row.lines.all()
                    ],
                }
                for row in Purchase.objects.filter(
                    organization_id=authorization.organization_id
                ).prefetch_related("lines")
            ]
            if can_read_purchases
            else []
        )
        result["receipts"] = (
            [
                {
                    **_row(row, "purchase_id", "reference", "received_on"),
                    "lines": [
                        _row(
                            line,
                            "purchase_line_id",
                            "resource_id",
                            "kind",
                            "quantity",
                            "destination_location_id",
                            "confirmed_at",
                        )
                        for line in row.lines.all()
                    ],
                }
                for row in SupplyReceipt.objects.filter(
                    organization_id=authorization.organization_id
                ).prefetch_related("lines")
            ]
            if can_read_purchases
            else []
        )
        return result


def receipt_line_for_finance(
    authorization: TenantAuthorization, receipt_line_id: UUID
) -> dict[str, object]:
    row = _get(SupplyReceiptLine, authorization, receipt_line_id, "La línea de recepción")
    return {
        "id": row.pk,
        "organization_id": row.organization_id,
        "kind": row.kind,
        "resource_id": row.resource_id,
        "quantity": row.quantity,
        "confirmed_at": row.confirmed_at,
        "purchase_id": row.receipt.purchase_id,
        "supplier_id": row.receipt.purchase.supplier_id,
        "root_reservation_id": row.receipt.purchase.root_reservation_id,
        "venue_id": row.receipt.purchase.venue_id,
    }


def transfer_assignments_authorized(
    authorization: TenantAuthorization,
    *,
    previous_reservation_id: UUID,
    successor_reservation_id: UUID,
    assignment_ids: tuple[UUID, ...],
) -> tuple[UUID, ...]:
    schedule = scheduling_port.resource_schedule(authorization, successor_reservation_id)
    if schedule is None:
        raise unavailable("La reserva sucesora")
    existing_successors = list(
        ResourceAssignment.objects.filter(
            organization_id=authorization.organization_id,
            reservation_id=successor_reservation_id,
            predecessor_assignment_id__in=assignment_ids,
        ).values_list("predecessor_assignment_id", "id")
    )
    if existing_successors:
        if {item[0] for item in existing_successors} != set(assignment_ids):
            raise conflict(
                "assignment_selection_conflict",
                "El reintento no coincide con la selección ya trasladada.",
            )
        return tuple(item[1] for item in sorted(existing_successors, key=lambda item: str(item[0])))
    selected = list(
        ResourceAssignment.objects.select_for_update().filter(
            organization_id=authorization.organization_id,
            reservation_id=previous_reservation_id,
            pk__in=assignment_ids,
            status=ResourceAssignment.Status.RELEASED,
        )
    )
    if len(selected) != len(set(assignment_ids)):
        raise conflict(
            "assignment_selection_conflict", "La selección incluye asignaciones no trasladables."
        )
    created: list[UUID] = []
    for previous in sorted(selected, key=lambda item: (str(item.resource_id), str(item.pk))):
        if previous.requirement is None:
            raise conflict(
                "assignment_selection_conflict",
                "La asignación no conserva su requerimiento de origen.",
            )
        if (
            previous.requirement.temporal_source
            != ResourceRequirement.TemporalSource.SCHEDULING_EVENT_INTERVAL
        ):
            raise conflict(
                "assignment_selection_conflict",
                "Una ventana P13 debe recalcularse y reservarse nuevamente en la sucesora.",
            )
        successor_requirement = ResourceRequirement.objects.create(
            organization_id=authorization.organization_id,
            root_reservation_id=schedule.root_id,
            reservation_id=schedule.reservation_id,
            resource=previous.resource,
            quantity=previous.quantity,
            resource_interval=Range(schedule.starts_at, schedule.ends_at, bounds="[)"),
            temporal_source=ResourceRequirement.TemporalSource.SCHEDULING_EVENT_INTERVAL,
            status=ResourceRequirement.Status.SATISFIED,
            reason=previous.requirement.reason,
            predecessor_requirement=previous.requirement,
            created_by_membership_id=authorization.membership_id,
        )
        row = ResourceAssignment.objects.create(
            organization_id=authorization.organization_id,
            requirement=successor_requirement,
            root_reservation_id=schedule.root_id,
            reservation_id=schedule.reservation_id,
            resource=previous.resource,
            serialized_asset=previous.serialized_asset,
            source_location=previous.source_location,
            quantity=previous.quantity,
            resource_interval=Range(schedule.starts_at, schedule.ends_at, bounds="[)"),
            predecessor_assignment=previous,
            recorded_by_membership_id=authorization.membership_id,
        )
        ResourceCapacityAllocation.objects.create(
            organization_id=authorization.organization_id,
            assignment=row,
            reservation_id=row.reservation_id,
            resource=row.resource,
            serialized_asset=row.serialized_asset,
            quantity=row.quantity,
            resource_interval=row.resource_interval,
        )
        created.append(row.pk)
    return tuple(created)


__all__ = (
    "add_supplier_offering",
    "add_supplier_term",
    "close_unavailability",
    "confirm_receipt_line",
    "create_conversion",
    "create_location",
    "create_purchase",
    "create_requirement",
    "create_resource",
    "create_supplier",
    "create_unit",
    "execute_assignment",
    "inactivate_supplier_contact",
    "link_supplier_contact",
    "receipt_line_for_finance",
    "record_movement",
    "record_unavailability",
    "reserve_resource",
    "resources_capabilities",
    "resources_overview",
    "set_resource_active",
    "set_supplier_offering_active",
    "set_supplier_active",
    "transfer_assignments_authorized",
)
