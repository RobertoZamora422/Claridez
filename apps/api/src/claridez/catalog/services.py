from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import IntegrityError
from django.db.models import Max
from django.utils import timezone
from psycopg.types.range import Range

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from .errors import conflict, invalid, unavailable
from .models import (
    CatalogItem,
    CatalogItemRevision,
    CatalogPrice,
    EventType,
    EventTypeRevision,
    PackageComponent,
)
from .normalization import canonical_optional_text, canonical_text, money


def _uuid(value: UUID | str, resource: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise unavailable(resource) from None


def _event_type(
    organization_id: UUID, event_type_id: UUID | str, *, lock: bool = False
) -> EventType:
    rows = EventType.objects.select_for_update() if lock else EventType.objects
    try:
        return rows.get(
            organization_id=organization_id, pk=_uuid(event_type_id, "El tipo de evento")
        )
    except EventType.DoesNotExist:
        raise unavailable("El tipo de evento") from None


def _item(organization_id: UUID, item_id: UUID | str, *, lock: bool = False) -> CatalogItem:
    rows = CatalogItem.objects.select_for_update() if lock else CatalogItem.objects
    try:
        return rows.get(organization_id=organization_id, pk=_uuid(item_id, "El ítem de catálogo"))
    except CatalogItem.DoesNotExist:
        raise unavailable("El ítem de catálogo") from None


def _event_type_data(row: EventType) -> dict[str, Any]:
    return {
        "id": row.pk,
        "name": row.name,
        "is_active": row.is_active,
        "revision": row.revision,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_event_types(actor: User, organization_reference: UUID | str) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.CATALOG_READ
    ) as authorization:
        rows = EventType.objects.filter(organization_id=authorization.organization_id)
        if Capability.CATALOG_MANAGE not in authorization_role_capabilities(authorization):
            rows = rows.filter(is_active=True)
        return tuple(_event_type_data(row) for row in rows.order_by("name", "id"))


def authorization_role_capabilities(authorization: TenantAuthorization) -> frozenset[Capability]:
    from claridez.organizations.capabilities import capabilities_for_role

    return capabilities_for_role(authorization.role)


def _append_event_type_revision(
    row: EventType, authorization: TenantAuthorization
) -> EventTypeRevision:
    return EventTypeRevision.objects.create(
        organization_id=authorization.organization_id,
        event_type=row,
        revision=row.revision,
        name=row.name,
        is_active=row.is_active,
        changed_by_membership_id=authorization.membership_id,
    )


def create_event_type(
    actor: User, organization_reference: UUID | str, *, name: str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.CATALOG_MANAGE
    ) as authorization:
        try:
            canonical_name = canonical_text(name, field="El tipo de evento", max_length=100)
            row = EventType.objects.create(
                organization_id=authorization.organization_id, name=canonical_name
            )
            _append_event_type_revision(row, authorization)
        except ValueError as error:
            raise invalid(str(error)) from error
        except IntegrityError as error:
            raise conflict("event_type_conflict", "El tipo de evento ya existe.") from error
        return _event_type_data(row)


def update_event_type(
    actor: User,
    organization_reference: UUID | str,
    *,
    event_type_id: UUID | str,
    revision: int,
    name: str,
    is_active: bool,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.CATALOG_MANAGE
    ) as authorization:
        row = _event_type(authorization.organization_id, event_type_id, lock=True)
        if row.revision != revision:
            raise conflict("stale_revision", "El tipo de evento cambió; vuelve a cargarlo.")
        try:
            canonical_name = canonical_text(name, field="El tipo de evento", max_length=100)
        except ValueError as error:
            raise invalid(str(error)) from error
        if row.name == canonical_name and row.is_active == is_active:
            return _event_type_data(row)
        row.name = canonical_name
        row.is_active = is_active
        row.revision += 1
        try:
            row.save()
            _append_event_type_revision(row, authorization)
        except IntegrityError as error:
            raise conflict(
                "event_type_conflict", "El tipo de evento no pudo actualizarse."
            ) from error
        return _event_type_data(row)


def _current_revision(item: CatalogItem) -> CatalogItemRevision:
    try:
        return CatalogItemRevision.objects.get(
            organization_id=item.organization_id, item=item, revision=item.revision
        )
    except CatalogItemRevision.DoesNotExist:
        raise conflict(
            "catalog_integrity_conflict", "El catálogo no conserva una revisión válida."
        ) from None


def _prepare_components(
    authorization: TenantAuthorization,
    *,
    package: CatalogItem,
    raw_components: list[dict[str, Any]],
) -> list[tuple[CatalogItem, CatalogItemRevision, Decimal]]:
    if package.kind != CatalogItem.Kind.PACKAGE:
        if raw_components:
            raise invalid("Solo los paquetes pueden tener componentes.")
        return []
    if not raw_components:
        raise invalid("Un paquete debe contener al menos un componente explícito.")
    prepared: list[tuple[CatalogItem, CatalogItemRevision, Decimal]] = []
    seen: set[UUID] = set()
    for raw in raw_components:
        component = _item(authorization.organization_id, raw.get("item_id", ""), lock=True)
        if component.pk == package.pk or component.kind == CatalogItem.Kind.PACKAGE:
            raise invalid("Un paquete solo puede contener servicios o productos distintos.")
        if not component.is_active or component.pk in seen:
            raise invalid("Los componentes del paquete deben estar activos y no repetirse.")
        try:
            quantity = Decimal(str(raw.get("quantity", ""))).quantize(Decimal("0.001"))
        except ArithmeticError as error:
            raise invalid("La cantidad del componente no es válida.") from error
        if quantity <= 0:
            raise invalid("La cantidad del componente debe ser mayor que cero.")
        seen.add(component.pk)
        prepared.append((component, _current_revision(component), quantity))
    return prepared


def _append_item_revision(
    item: CatalogItem,
    authorization: TenantAuthorization,
    components: list[tuple[CatalogItem, CatalogItemRevision, Decimal]],
) -> CatalogItemRevision:
    component_snapshot = [
        {
            "item_id": str(component.pk),
            "revision_id": str(component_revision.pk),
            "revision": component_revision.revision,
            "kind": component.kind,
            "name": component.name,
            "unit_label": component.unit_label,
            "quantity": f"{quantity:.3f}",
        }
        for component, component_revision, quantity in components
    ]
    revision = CatalogItemRevision.objects.create(
        organization_id=authorization.organization_id,
        item=item,
        revision=item.revision,
        kind=item.kind,
        name=item.name,
        description=item.description,
        unit_label=item.unit_label,
        is_active=item.is_active,
        package_components=component_snapshot,
        changed_by_membership_id=authorization.membership_id,
    )
    PackageComponent.objects.bulk_create(
        [
            PackageComponent(
                organization_id=authorization.organization_id,
                package=item,
                package_revision=item.revision,
                component=component,
                component_revision=component_revision,
                position=position,
                quantity=quantity,
            )
            for position, (component, component_revision, quantity) in enumerate(
                components, start=1
            )
        ]
    )
    return revision


def _price_data(price: CatalogPrice) -> dict[str, Any]:
    return {
        "id": price.pk,
        "amount": price.amount,
        "currency": price.currency,
        "valid_from": price.validity.lower,
        "valid_until": price.validity.upper,
        "revision": price.revision,
        "created_at": price.created_at,
        "updated_at": price.updated_at,
    }


def _item_data(
    item: CatalogItem, *, include_prices: bool, at: datetime | None = None
) -> dict[str, Any]:
    revision = _current_revision(item)
    result: dict[str, Any] = {
        "id": item.pk,
        "kind": item.kind,
        "name": item.name,
        "description": item.description or None,
        "unit_label": item.unit_label,
        "is_active": item.is_active,
        "revision": item.revision,
        "revision_id": revision.pk,
        "components": revision.package_components,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    if include_prices:
        effective_at = timezone.now() if at is None else at
        prices = list(
            CatalogPrice.objects.filter(organization_id=item.organization_id, item=item).order_by(
                "validity", "id"
            )
        )
        current = next((price for price in prices if effective_at in price.validity), None)
        result["current_price"] = _price_data(current) if current is not None else None
        result["prices"] = tuple(_price_data(price) for price in prices)
    return result


def list_catalog_items(
    actor: User,
    organization_reference: UUID | str,
    *,
    at: datetime | None = None,
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.CATALOG_READ
    ) as authorization:
        capabilities = authorization_role_capabilities(authorization)
        rows = CatalogItem.objects.filter(organization_id=authorization.organization_id)
        if Capability.CATALOG_MANAGE not in capabilities:
            rows = rows.filter(is_active=True)
        include_prices = Capability.CATALOG_PRICE_READ in capabilities
        return tuple(
            _item_data(row, include_prices=include_prices, at=at)
            for row in rows.order_by("kind", "name", "id")
        )


def create_catalog_item(
    actor: User,
    organization_reference: UUID | str,
    *,
    kind: str,
    name: str,
    description: str,
    unit_label: str,
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.CATALOG_MANAGE
    ) as authorization:
        try:
            canonical_kind = CatalogItem.Kind(kind)
            canonical_name = canonical_text(name, field="El nombre del catálogo", max_length=150)
            canonical_description = canonical_optional_text(
                description, field="La descripción", max_length=500
            )
            canonical_unit = canonical_text(unit_label, field="La unidad", max_length=40)
        except (ValueError, TypeError) as error:
            raise invalid(str(error) or "El ítem de catálogo no es válido.") from error
        try:
            item = CatalogItem.objects.create(
                organization_id=authorization.organization_id,
                kind=canonical_kind,
                name=canonical_name,
                description=canonical_description,
                unit_label=canonical_unit,
            )
            prepared = _prepare_components(authorization, package=item, raw_components=components)
            _append_item_revision(item, authorization, prepared)
        except IntegrityError as error:
            raise conflict("catalog_item_conflict", "El ítem de catálogo ya existe.") from error
        return _item_data(item, include_prices=True)


def update_catalog_item(
    actor: User,
    organization_reference: UUID | str,
    *,
    item_id: UUID | str,
    revision: int,
    name: str,
    description: str,
    unit_label: str,
    is_active: bool,
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.CATALOG_MANAGE
    ) as authorization:
        item = _item(authorization.organization_id, item_id, lock=True)
        if item.revision != revision:
            raise conflict("stale_revision", "El catálogo cambió; vuelve a cargarlo.")
        try:
            item.name = canonical_text(name, field="El nombre del catálogo", max_length=150)
            item.description = canonical_optional_text(
                description, field="La descripción", max_length=500
            )
            item.unit_label = canonical_text(unit_label, field="La unidad", max_length=40)
        except ValueError as error:
            raise invalid(str(error)) from error
        item.is_active = is_active
        item.revision += 1
        prepared = _prepare_components(authorization, package=item, raw_components=components)
        try:
            item.save()
            _append_item_revision(item, authorization, prepared)
        except IntegrityError as error:
            raise conflict(
                "catalog_item_conflict", "El ítem de catálogo no pudo actualizarse."
            ) from error
        return _item_data(item, include_prices=True)


def create_catalog_price(
    actor: User,
    organization_reference: UUID | str,
    *,
    item_id: UUID | str,
    amount: Decimal,
    valid_from: datetime,
    valid_until: datetime | None,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.CATALOG_PRICE_MANAGE
    ) as authorization:
        item = _item(authorization.organization_id, item_id, lock=True)
        if valid_from.tzinfo is None or (valid_until is not None and valid_until.tzinfo is None):
            raise invalid("La vigencia debe incluir zona horaria.")
        if valid_until is not None and valid_until <= valid_from:
            raise invalid("El fin de vigencia debe ser posterior al inicio.")
        canonical_amount = money(amount)
        if canonical_amount < 0:
            raise invalid("El precio no puede ser negativo.")
        try:
            overlapping = (
                CatalogPrice.objects.select_for_update()
                .filter(
                    organization_id=authorization.organization_id,
                    item=item,
                    validity__contains=valid_from,
                )
                .first()
            )
            if overlapping is not None:
                if overlapping.validity.lower >= valid_from:
                    raise conflict(
                        "price_validity_conflict",
                        "Ya existe un precio que comienza en esa fecha.",
                    )
                overlapping.validity = Range(overlapping.validity.lower, valid_from, bounds="[)")
                overlapping.save(update_fields=["validity", "updated_at"])
            next_revision = (
                CatalogPrice.objects.filter(
                    organization_id=authorization.organization_id, item=item
                ).aggregate(value=Max("revision"))["value"]
                or 0
            ) + 1
            price = CatalogPrice.objects.create(
                organization_id=authorization.organization_id,
                item=item,
                amount=canonical_amount,
                currency="USD",
                validity=Range(valid_from, valid_until, bounds="[)"),
                revision=next_revision,
                created_by_membership_id=authorization.membership_id,
            )
        except IntegrityError as error:
            raise conflict(
                "price_validity_conflict", "La vigencia se superpone con otro precio."
            ) from error
        return _price_data(price)


def resolve_catalog_line(
    authorization: TenantAuthorization,
    *,
    item_id: UUID | str,
    at: datetime | None = None,
) -> dict[str, Any]:
    authorization.require(Capability.CATALOG_READ)
    authorization.require(Capability.CATALOG_PRICE_READ)
    item = _item(authorization.organization_id, item_id, lock=True)
    if not item.is_active:
        raise conflict("catalog_item_inactive", "El ítem de catálogo no está activo.")
    effective_at = timezone.now() if at is None else at
    price = (
        CatalogPrice.objects.select_for_update()
        .filter(
            organization_id=authorization.organization_id,
            item=item,
            validity__contains=effective_at,
        )
        .first()
    )
    if price is None:
        raise conflict("catalog_price_unavailable", "El ítem no tiene un precio vigente.")
    revision = _current_revision(item)
    return {
        "item_id": item.pk,
        "revision_id": revision.pk,
        "price_id": price.pk,
        "kind": item.kind,
        "description": item.name,
        "unit_label": item.unit_label,
        "unit_price": price.amount,
        "package_components": revision.package_components,
    }
