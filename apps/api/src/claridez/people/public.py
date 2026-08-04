"""Puerto público estrecho de identidad de personas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from . import services as _services
from .errors import PeopleError
from .models import Person, PersonContactAlias


@dataclass(frozen=True, slots=True)
class PersonProjection:
    id: UUID
    organization_id: UUID
    full_name: str
    phone_e164: str
    email: str | None
    origin: str
    origin_detail: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ContactAliasProjection:
    kind: str
    value: str
    source_person_id: UUID
    source_revision: int


def _projection(person: Person) -> PersonProjection:
    return PersonProjection(
        id=person.pk,
        organization_id=person.organization_id,
        full_name=person.full_name,
        phone_e164=person.phone_e164,
        email=person.email or None,
        origin=person.origin,
        origin_detail=person.origin_detail or None,
        revision=person.revision,
        created_at=person.created_at,
        updated_at=person.updated_at,
    )


def get_person(organization_id: UUID, person_id: UUID | str) -> PersonProjection:
    return _projection(_services.get_person_raw(organization_id, person_id))


def lock_canonical_person_id(organization_id: UUID, person_id: UUID | str) -> UUID:
    return _services.require_canonical_person(organization_id, person_id, lock=True).pk


def aliases_for_person(
    organization_id: UUID, person_id: UUID | str
) -> tuple[ContactAliasProjection, ...]:
    cluster = _services.canonical_cluster_ids(organization_id, person_id)
    return tuple(
        ContactAliasProjection(
            kind=row.kind,
            value=row.normalized_value,
            source_person_id=row.source_person_id,
            source_revision=row.source_revision,
        )
        for row in PersonContactAlias.objects.filter(
            organization_id=organization_id, person_id__in=cluster
        ).order_by("kind", "normalized_value")
    )


canonical_cluster_ids = _services.canonical_cluster_ids
canonical_person_id = _services.canonical_person_id
create_person = _services.create_person
list_consents = _services.list_consents
list_people = _services.list_people
list_person_revisions = _services.list_person_revisions
read_person = _services.read_person
update_person = _services.update_person

__all__ = (
    "PeopleError",
    "ContactAliasProjection",
    "PersonProjection",
    "aliases_for_person",
    "canonical_cluster_ids",
    "canonical_person_id",
    "create_person",
    "get_person",
    "list_consents",
    "list_people",
    "list_person_revisions",
    "lock_canonical_person_id",
    "read_person",
    "update_person",
)
