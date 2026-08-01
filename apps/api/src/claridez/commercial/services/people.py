from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope

from ..errors import conflict, invalid, unavailable
from ..models import Person, PersonRevision
from ..normalization import (
    canonical_email,
    canonical_optional_text,
    canonical_phone,
    canonical_text,
)
from .representations import _person_data
from .shared import _origin, _uuid


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


def _get_person(organization_id: UUID, person_id: UUID | str, *, lock: bool = False) -> Person:
    queryset = Person.objects.select_for_update() if lock else Person.objects.all()
    try:
        return queryset.get(organization_id=organization_id, pk=_uuid(person_id, "La persona"))
    except Person.DoesNotExist:
        raise unavailable("La persona") from None


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
