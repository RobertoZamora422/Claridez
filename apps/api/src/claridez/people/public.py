"""Puerto público estrecho de identidad de personas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from . import services as _services
from .analytics import canonical_clusters_as_of
from .errors import PeopleError
from .models import ConsentEvent, ContactOrigin, Person, PersonContactAlias
from .normalization import canonical_email, canonical_phone


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


@dataclass(frozen=True, slots=True)
class ContactControlProjection:
    canonical_person_id: UUID
    canonical_cluster_ids: tuple[UUID, ...]
    kind: str
    value: str
    person_revision: int


@dataclass(frozen=True, slots=True)
class ExternalConsentProjection:
    id: UUID
    person_id: UUID
    purpose: str
    channel: str
    decision: str
    occurred_at: datetime


def capture_origin_is_valid(value: str) -> bool:
    try:
        ContactOrigin(value)
    except ValueError:
        return False
    return True


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


def resolve_or_create_for_capture(
    organization_id: UUID,
    *,
    full_name: str,
    phone: str,
    email: str | None,
    origin: str,
    origin_detail: str | None,
    evidence_reference: str,
    evidence_sha256: str,
) -> PersonProjection:
    return _projection(
        _services.resolve_or_create_for_capture(
            organization_id,
            full_name=full_name,
            phone=phone,
            email=email,
            origin=origin,
            origin_detail=origin_detail,
            evidence_reference=evidence_reference,
            evidence_sha256=evidence_sha256,
        )
    )


def record_external_consent(
    organization_id: UUID,
    *,
    person_id: UUID,
    purpose: str,
    channel: str,
    decision: str,
    occurred_at: datetime,
    evidence_reference: str,
    submission_reference: str,
    evidence_sha256: str,
    observed_text_sha256: str,
    presentation_version: str,
) -> ExternalConsentProjection:
    row: ConsentEvent = _services.record_external_consent(
        organization_id,
        person_id=person_id,
        purpose=purpose,
        channel=channel,
        decision=decision,
        occurred_at=occurred_at,
        evidence_reference=evidence_reference,
        submission_reference=submission_reference,
        evidence_sha256=evidence_sha256,
        observed_text_sha256=observed_text_sha256,
        presentation_version=presentation_version,
    )
    return ExternalConsentProjection(
        id=row.pk,
        person_id=row.person_id,
        purpose=row.purpose,
        channel=row.channel,
        decision=row.decision,
        occurred_at=row.occurred_at,
    )


def contact_for_external_control(
    organization_id: UUID, *, person_id: UUID | str, channel: str
) -> ContactControlProjection | None:
    canonical_id = _services.canonical_person_id(organization_id, person_id)
    person = _services.get_person_raw(organization_id, canonical_id)
    if channel == ConsentEvent.Channel.EMAIL:
        kind = "email"
        value = person.email
    elif channel in {ConsentEvent.Channel.WHATSAPP, ConsentEvent.Channel.PHONE}:
        kind = "phone"
        value = person.phone_e164
    else:
        return None
    if not value:
        return None
    return ContactControlProjection(
        canonical_person_id=canonical_id,
        canonical_cluster_ids=_services.canonical_cluster_ids(organization_id, canonical_id),
        kind=kind,
        value=value,
        person_revision=person.revision,
    )


def resolve_contact_for_portal(
    organization_id: UUID, *, channel: str, value: str
) -> ContactControlProjection | None:
    try:
        if channel == ConsentEvent.Channel.EMAIL:
            normalized = canonical_email(value)
            person = Person.objects.filter(
                organization_id=organization_id, email=normalized
            ).first()
            if person is None:
                alias = PersonContactAlias.objects.filter(
                    organization_id=organization_id,
                    kind=PersonContactAlias.Kind.EMAIL,
                    normalized_value=normalized,
                ).first()
                person = alias.person if alias else None
        elif channel in {ConsentEvent.Channel.WHATSAPP, ConsentEvent.Channel.PHONE}:
            normalized = canonical_phone(value)
            person = Person.objects.filter(
                organization_id=organization_id, phone_e164=normalized
            ).first()
            if person is None:
                alias = PersonContactAlias.objects.filter(
                    organization_id=organization_id,
                    kind=PersonContactAlias.Kind.PHONE,
                    normalized_value=normalized,
                ).first()
                person = alias.person if alias else None
        else:
            return None
    except ValueError:
        return None
    if person is None:
        return None
    return contact_for_external_control(organization_id, person_id=person.pk, channel=channel)


effective_consent = _services.effective_consent


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
    "ContactControlProjection",
    "ExternalConsentProjection",
    "PersonProjection",
    "aliases_for_person",
    "contact_for_external_control",
    "resolve_contact_for_portal",
    "canonical_cluster_ids",
    "canonical_person_id",
    "capture_origin_is_valid",
    "create_person",
    "get_person",
    "effective_consent",
    "list_consents",
    "list_people",
    "list_person_revisions",
    "lock_canonical_person_id",
    "record_external_consent",
    "read_person",
    "update_person",
    "resolve_or_create_for_capture",
    "canonical_clusters_as_of",
)
