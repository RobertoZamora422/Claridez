"""Configuración funcional P6, separada de membresías y acciones sensibles."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import IntegrityError
from django.db.models import F
from django.utils import timezone

from claridez.identity.models import User

from .capabilities import Capability, capabilities_for_role
from .models import Organization, OrganizationSettings, Space, Venue
from .normalization import (
    canonicalize_business_label,
    canonicalize_location_reference,
    canonicalize_organization_name,
    canonicalize_timezone,
)
from .tenant_scope import TenantAuthorization, authorized_tenant_scope


class ConfigurationError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _invalid(message: str) -> ConfigurationError:
    return ConfigurationError("invalid_request", message)


def _conflict(code: str, message: str) -> ConfigurationError:
    return ConfigurationError(code, message, status=409)


def _unavailable(resource: str) -> ConfigurationError:
    return ConfigurationError(
        "resource_not_available", f"{resource} no está disponible.", status=404
    )


P6_CAPABILITIES = frozenset(
    {
        Capability.BUSINESS_CONFIGURATION_READ,
        Capability.BUSINESS_CONFIGURATION_MANAGE,
        Capability.VENUE_READ,
        Capability.VENUE_MANAGE,
        Capability.CATALOG_READ,
        Capability.CATALOG_PRICE_READ,
        Capability.CATALOG_MANAGE,
        Capability.CATALOG_PRICE_MANAGE,
    }
)


def configuration_capabilities(actor: User, organization_reference: UUID | str) -> tuple[str, ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.ORGANIZATION_ACCESS
    ) as authorization:
        allowed = capabilities_for_role(authorization.role)
        return tuple(sorted(capability.value for capability in P6_CAPABILITIES & allowed))


def _configuration_data(
    organization: Organization, settings: OrganizationSettings
) -> dict[str, Any]:
    return {
        "organization_id": organization.pk,
        "name": organization.name,
        "currency": settings.currency,
        "timezone": settings.timezone,
        "updated_at": max(organization.updated_at, settings.updated_at),
    }


def read_business_configuration(actor: User, organization_reference: UUID | str) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.BUSINESS_CONFIGURATION_READ
    ) as authorization:
        organization = Organization.objects.get(pk=authorization.organization_id)
        settings = OrganizationSettings.objects.get(organization_id=authorization.organization_id)
        return _configuration_data(organization, settings)


def update_business_configuration(
    actor: User,
    organization_reference: UUID | str,
    *,
    name: str,
    currency: str,
    timezone: str,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.BUSINESS_CONFIGURATION_MANAGE
    ) as authorization:
        try:
            canonical_name = canonicalize_organization_name(name)
            canonical_timezone = canonicalize_timezone(timezone)
        except ValueError as error:
            raise _invalid(str(error)) from error
        if currency.strip().upper() != "USD":
            raise _invalid("P6 mantiene USD como moneda funcional inicial.")
        organization = Organization.objects.select_for_update().get(
            pk=authorization.organization_id
        )
        settings = OrganizationSettings.objects.select_for_update().get(
            organization_id=authorization.organization_id
        )
        organization.name = canonical_name
        settings.currency = "USD"
        settings.timezone = canonical_timezone
        organization.save(update_fields=["name", "updated_at"])
        settings.save(update_fields=["currency", "timezone", "updated_at"])
        return _configuration_data(organization, settings)


def _space_data(space: Space) -> dict[str, Any]:
    return {
        "id": space.pk,
        "venue_id": space.venue_id,
        "name": space.name,
        "is_primary": space.is_primary,
        "is_active": space.is_active,
        "revision": space.revision,
        "created_at": space.created_at,
        "updated_at": space.updated_at,
    }


def _venue_data(venue: Venue, *, spaces: list[Space] | None = None) -> dict[str, Any]:
    materialized_spaces = list(venue.spaces.all()) if spaces is None else spaces
    return {
        "id": venue.pk,
        "name": venue.name,
        "location_reference": venue.location_reference or None,
        "is_primary": venue.is_primary,
        "is_active": venue.is_active,
        "revision": venue.revision,
        "spaces": tuple(_space_data(space) for space in materialized_spaces),
        "created_at": venue.created_at,
        "updated_at": venue.updated_at,
    }


def list_venues(actor: User, organization_reference: UUID | str) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.VENUE_READ
    ) as authorization:
        venues = list(
            Venue.objects.prefetch_related("spaces")
            .filter(organization_id=authorization.organization_id)
            .order_by("name", "id")
        )
        return tuple(_venue_data(venue, spaces=list(venue.spaces.all())) for venue in venues)


def _venue(
    authorization: TenantAuthorization, venue_id: UUID | str, *, lock: bool = False
) -> Venue:
    rows = Venue.objects.select_for_update() if lock else Venue.objects
    try:
        return rows.get(organization_id=authorization.organization_id, pk=UUID(str(venue_id)))
    except (Venue.DoesNotExist, TypeError, ValueError):
        raise _unavailable("La sede") from None


def _space(
    authorization: TenantAuthorization, space_id: UUID | str, *, lock: bool = False
) -> Space:
    rows = Space.objects.select_related("venue")
    if lock:
        rows = rows.select_for_update()
    try:
        return rows.get(organization_id=authorization.organization_id, pk=UUID(str(space_id)))
    except (Space.DoesNotExist, TypeError, ValueError):
        raise _unavailable("El espacio") from None


def create_venue(
    actor: User,
    organization_reference: UUID | str,
    *,
    name: str,
    location_reference: str = "",
    is_primary: bool = False,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.VENUE_MANAGE
    ) as authorization:
        try:
            canonical_name = canonicalize_business_label(name, field="El nombre de la sede")
            canonical_location = canonicalize_location_reference(location_reference)
        except ValueError as error:
            raise _invalid(str(error)) from error
        if is_primary:
            Venue.objects.select_for_update().filter(
                organization_id=authorization.organization_id, is_primary=True
            ).update(is_primary=False, revision=F("revision") + 1, updated_at=timezone.now())
        try:
            venue = Venue.objects.create(
                organization_id=authorization.organization_id,
                name=canonical_name,
                location_reference=canonical_location,
                is_primary=is_primary,
                is_active=True,
            )
        except IntegrityError as error:
            raise _conflict("venue_conflict", "La sede ya existe.") from error
        return _venue_data(venue, spaces=[])


def update_venue(
    actor: User,
    organization_reference: UUID | str,
    *,
    venue_id: UUID | str,
    revision: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.VENUE_MANAGE
    ) as authorization:
        venue = _venue(authorization, venue_id, lock=True)
        if venue.revision != revision:
            raise _conflict("stale_revision", "La sede cambió; vuelve a cargarla.")
        try:
            if "name" in changes:
                venue.name = canonicalize_business_label(
                    str(changes["name"]), field="El nombre de la sede"
                )
            if "location_reference" in changes:
                venue.location_reference = canonicalize_location_reference(
                    changes["location_reference"]
                )
        except ValueError as error:
            raise _invalid(str(error)) from error
        target_active = bool(changes.get("is_active", venue.is_active))
        target_primary = bool(changes.get("is_primary", venue.is_primary))
        if venue.is_primary and not target_primary:
            raise _conflict(
                "primary_venue_required", "Selecciona otra sede principal antes de cambiar esta."
            )
        if not target_active and (
            venue.is_primary
            or Space.objects.filter(
                organization_id=authorization.organization_id, venue=venue, is_active=True
            ).exists()
        ):
            raise _conflict(
                "venue_in_use", "La sede principal o con espacios activos no puede desactivarse."
            )
        if target_primary and not venue.is_primary:
            Venue.objects.select_for_update().filter(
                organization_id=authorization.organization_id, is_primary=True
            ).exclude(pk=venue.pk).update(
                is_primary=False,
                revision=F("revision") + 1,
                updated_at=timezone.now(),
            )
        venue.is_primary = target_primary
        venue.is_active = target_active
        venue.revision += 1
        try:
            venue.save()
        except IntegrityError as error:
            raise _conflict("venue_conflict", "La sede no pudo actualizarse.") from error
        return _venue_data(venue)


def create_space(
    actor: User,
    organization_reference: UUID | str,
    *,
    venue_id: UUID | str,
    name: str,
    is_primary: bool = False,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.VENUE_MANAGE
    ) as authorization:
        venue = _venue(authorization, venue_id, lock=True)
        if not venue.is_active:
            raise _conflict("venue_inactive", "La sede no está activa.")
        try:
            canonical_name = canonicalize_business_label(name, field="El nombre del espacio")
        except ValueError as error:
            raise _invalid(str(error)) from error
        if is_primary:
            Space.objects.select_for_update().filter(
                organization_id=authorization.organization_id, is_primary=True
            ).update(is_primary=False, revision=F("revision") + 1, updated_at=timezone.now())
        try:
            space = Space.objects.create(
                organization_id=authorization.organization_id,
                venue=venue,
                name=canonical_name,
                is_primary=is_primary,
                is_active=True,
            )
        except IntegrityError as error:
            raise _conflict("space_conflict", "El espacio ya existe.") from error
        return _space_data(space)


def update_space(
    actor: User,
    organization_reference: UUID | str,
    *,
    space_id: UUID | str,
    revision: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.VENUE_MANAGE
    ) as authorization:
        space = _space(authorization, space_id, lock=True)
        if space.revision != revision:
            raise _conflict("stale_revision", "El espacio cambió; vuelve a cargarlo.")
        try:
            if "name" in changes:
                space.name = canonicalize_business_label(
                    str(changes["name"]), field="El nombre del espacio"
                )
        except ValueError as error:
            raise _invalid(str(error)) from error
        target_active = bool(changes.get("is_active", space.is_active))
        target_primary = bool(changes.get("is_primary", space.is_primary))
        if space.is_primary and not target_primary:
            raise _conflict(
                "primary_space_required", "Selecciona otro espacio principal antes de cambiar este."
            )
        if not target_active and space.is_primary:
            raise _conflict(
                "primary_space_required", "El espacio principal debe permanecer activo."
            )
        if target_primary and not space.is_primary:
            Space.objects.select_for_update().filter(
                organization_id=authorization.organization_id, is_primary=True
            ).exclude(pk=space.pk).update(
                is_primary=False,
                revision=F("revision") + 1,
                updated_at=timezone.now(),
            )
        space.is_primary = target_primary
        space.is_active = target_active
        space.revision += 1
        try:
            space.save()
        except IntegrityError as error:
            raise _conflict("space_conflict", "El espacio no pudo actualizarse.") from error
        return _space_data(space)
