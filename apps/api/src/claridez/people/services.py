from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope

from .errors import conflict, invalid, unavailable
from .models import (
    ConsentEvent,
    ContactOrigin,
    Person,
    PersonContactAlias,
    PersonMerge,
    PersonRevision,
)
from .normalization import (
    canonical_email,
    canonical_optional_text,
    canonical_phone,
    canonical_text,
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


def get_person_raw(organization_id: UUID, person_id: UUID | str, *, lock: bool = False) -> Person:
    rows = Person.objects.select_for_update() if lock else Person.objects.all()
    try:
        return rows.get(organization_id=organization_id, pk=_uuid(person_id, "La persona"))
    except Person.DoesNotExist:
        raise unavailable("La persona") from None


def canonical_person_id(organization_id: UUID, person_id: UUID | str) -> UUID:
    current = _uuid(person_id, "La persona")
    seen: set[UUID] = set()
    while current not in seen:
        seen.add(current)
        target = (
            PersonMerge.objects.filter(organization_id=organization_id, source_person_id=current)
            .values_list("target_person_id", flat=True)
            .first()
        )
        if target is None:
            return current
        current = target
    raise conflict("merge_cycle", "La identidad canónica no puede resolverse.")


def canonical_cluster_ids(organization_id: UUID, person_id: UUID | str) -> tuple[UUID, ...]:
    root = canonical_person_id(organization_id, person_id)
    cluster: set[UUID] = {root}
    pending = [root]
    while pending:
        targets = tuple(pending)
        pending = []
        for source in PersonMerge.objects.filter(
            organization_id=organization_id, target_person_id__in=targets
        ).values_list("source_person_id", flat=True):
            if source not in cluster:
                cluster.add(source)
                pending.append(source)
    return tuple(sorted(cluster, key=str))


def require_canonical_person(
    organization_id: UUID, person_id: UUID | str, *, lock: bool = False
) -> Person:
    person = get_person_raw(organization_id, person_id, lock=lock)
    target = (
        PersonMerge.objects.filter(organization_id=organization_id, source_person=person)
        .values_list("target_person_id", flat=True)
        .first()
    )
    if target is not None:
        raise conflict("person_merged", "La persona fue fusionada; vuelve a cargarla.")
    return person


def _person_data(person: Person, *, requested_id: UUID | None = None) -> dict[str, Any]:
    aliases = PersonContactAlias.objects.filter(
        organization_id=person.organization_id,
        person_id__in=canonical_cluster_ids(person.organization_id, person.pk),
    ).order_by("kind", "normalized_value")
    return {
        "id": person.pk,
        "canonical_id": person.pk,
        "requested_id": requested_id or person.pk,
        "full_name": person.full_name,
        "phone_e164": person.phone_e164,
        "email": person.email or None,
        "origin": person.origin,
        "origin_detail": person.origin_detail or None,
        "revision": person.revision,
        "aliases": tuple(
            {
                "id": alias.pk,
                "kind": alias.kind,
                "value": alias.normalized_value,
                "source_person_id": alias.source_person_id,
                "source_revision": alias.source_revision,
            }
            for alias in aliases
        ),
        "merged_person_ids": canonical_cluster_ids(person.organization_id, person.pk),
        "created_at": person.created_at,
        "updated_at": person.updated_at,
    }


def _snapshot(person: Person, actor_id: UUID) -> PersonRevision:
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


def _alias_conflict(organization_id: UUID, *, phone: str, email: str, exclude: UUID | None) -> bool:
    current_values = Q(phone_e164=phone)
    people = Person.objects.filter(organization_id=organization_id).filter(current_values)
    values = Q(kind=PersonContactAlias.Kind.PHONE, normalized_value=phone)
    if email:
        values |= Q(kind=PersonContactAlias.Kind.EMAIL, normalized_value=email)
    rows = PersonContactAlias.objects.filter(organization_id=organization_id).filter(values)
    if exclude is not None:
        cluster = canonical_cluster_ids(organization_id, exclude)
        people = people.exclude(pk__in=cluster)
        rows = rows.exclude(person_id__in=cluster)
    return people.exists() or rows.exists()


def list_people(
    actor: User, organization_reference: UUID | str, *, query: str = ""
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        merged_sources = PersonMerge.objects.filter(
            organization_id=authorization.organization_id
        ).values_list("source_person_id", flat=True)
        roots = Person.objects.filter(organization_id=authorization.organization_id).exclude(
            pk__in=merged_sources
        )
        term = query.strip()
        if term:
            contact_match = Q(phone_e164__icontains=term) | Q(email__icontains=term)
            alias_match = Q(normalized_value__icontains=term.lower())
            try:
                phone_term = canonical_phone(term)
            except ValueError:
                phone_term = ""
            if phone_term:
                contact_match |= Q(phone_e164=phone_term)
                alias_match |= Q(kind=PersonContactAlias.Kind.PHONE, normalized_value=phone_term)
            matching_people = Person.objects.filter(
                organization_id=authorization.organization_id
            ).filter(Q(full_name__icontains=term) | contact_match)
            matching_ids = {
                canonical_person_id(authorization.organization_id, person_id)
                for person_id in matching_people.values_list("id", flat=True)
            }
            alias_ids = (
                PersonContactAlias.objects.filter(
                    organization_id=authorization.organization_id,
                )
                .filter(alias_match)
                .values_list("person_id", flat=True)
            )
            matching_ids.update(
                canonical_person_id(authorization.organization_id, person_id)
                for person_id in alias_ids
            )
            roots = roots.filter(pk__in=matching_ids)
        return tuple(_person_data(row) for row in roots.order_by("full_name", "id")[:100])


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
            name = canonical_text(full_name, field="El nombre", max_length=150)
            phone_value = canonical_phone(phone)
            email_value = canonical_email(email)
            origin_value = _origin(origin)
            detail = canonical_optional_text(
                origin_detail, field="El detalle del origen", max_length=160
            )
        except ValueError as error:
            raise invalid(str(error)) from error
        if _alias_conflict(
            authorization.organization_id, phone=phone_value, email=email_value, exclude=None
        ):
            raise conflict("duplicate_person", "Ese contacto pertenece a una persona existente.")
        try:
            with transaction.atomic():
                person = Person.objects.create(
                    organization_id=authorization.organization_id,
                    full_name=name,
                    phone_e164=phone_value,
                    email=email_value,
                    origin=origin_value,
                    origin_detail=detail,
                )
                _snapshot(person, authorization.actor_id)
        except IntegrityError as error:
            raise conflict("duplicate_person", "Ya existe una persona con ese teléfono.") from error
        return _person_data(person)


def read_person(
    actor: User, organization_reference: UUID | str, *, person_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        requested = _uuid(person_id, "La persona")
        get_person_raw(authorization.organization_id, requested)
        canonical = get_person_raw(
            authorization.organization_id,
            canonical_person_id(authorization.organization_id, requested),
        )
        return _person_data(canonical, requested_id=requested)


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
        person = require_canonical_person(authorization.organization_id, person_id, lock=True)
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
        if _alias_conflict(
            authorization.organization_id,
            phone=person.phone_e164,
            email=person.email,
            exclude=person.pk,
        ):
            raise conflict("duplicate_person", "Ese contacto pertenece a una persona existente.")
        person.revision += 1
        try:
            with transaction.atomic():
                person.save()
                _snapshot(person, authorization.actor_id)
        except IntegrityError as error:
            raise conflict("duplicate_person", "Ya existe una persona con ese teléfono.") from error
        return _person_data(person)


def list_person_revisions(
    actor: User, organization_reference: UUID | str, *, person_id: UUID | str
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        get_person_raw(authorization.organization_id, person_id)
        cluster = canonical_cluster_ids(authorization.organization_id, person_id)
        rows = PersonRevision.objects.filter(
            organization_id=authorization.organization_id, person_id__in=cluster
        ).order_by("created_at", "person_id", "revision")
        return tuple(
            {
                "id": row.pk,
                "person_id": row.person_id,
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


def _merge_data(row: PersonMerge) -> dict[str, Any]:
    return {
        "id": row.pk,
        "source_person_id": row.source_person_id,
        "target_person_id": row.target_person_id,
        "canonical_person_id": canonical_person_id(row.organization_id, row.target_person_id),
        "source_revision": row.source_revision,
        "target_revision": row.target_revision,
        "reason": row.reason,
        "idempotency_key": row.idempotency_key,
        "merged_by_membership_id": row.merged_by_membership_id,
        "created_at": row.created_at,
    }


def merge_people(
    actor: User,
    organization_reference: UUID | str,
    *,
    source_person_id: UUID | str,
    target_person_id: UUID | str,
    source_revision: int,
    target_revision: int,
    reason: str,
    idempotency_key: UUID | str,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_MANAGE
    ) as authorization:
        authorization.require(Capability.PERSON_MERGE)
        source_id = _uuid(source_person_id, "La persona origen")
        target_id = _uuid(target_person_id, "La persona destino")
        key = _uuid(idempotency_key, "La clave de idempotencia")
        try:
            canonical_reason = canonical_text(reason, field="La razón", max_length=500)
        except ValueError as error:
            raise invalid(str(error)) from error
        existing_key = PersonMerge.objects.filter(
            organization_id=authorization.organization_id, idempotency_key=key
        ).first()
        if existing_key is not None:
            if (
                existing_key.source_person_id == source_id
                and existing_key.target_person_id == target_id
                and existing_key.source_revision == source_revision
                and existing_key.target_revision == target_revision
                and existing_key.reason == canonical_reason
            ):
                return _merge_data(existing_key)
            raise conflict("idempotency_conflict", "La clave ya fue usada con otra fusión.")
        if source_id == target_id:
            raise invalid("La persona origen y destino deben ser distintas.")
        locked = {
            row.pk: row
            for row in Person.objects.select_for_update()
            .filter(organization_id=authorization.organization_id, pk__in=[source_id, target_id])
            .order_by("id")
        }
        if source_id not in locked or target_id not in locked:
            raise unavailable("La persona")
        source_person = locked[source_id]
        target_person = locked[target_id]
        previous = PersonMerge.objects.filter(
            organization_id=authorization.organization_id, source_person=source_person
        ).first()
        if previous is not None:
            if previous.target_person_id == target_id and previous.reason == canonical_reason:
                return _merge_data(previous)
            raise conflict("person_merged", "La persona origen ya fue fusionada.")
        if PersonMerge.objects.filter(
            organization_id=authorization.organization_id, source_person=target_person
        ).exists():
            raise conflict("target_not_canonical", "La persona destino ya fue fusionada.")
        if source_person.revision != source_revision or target_person.revision != target_revision:
            raise conflict("stale_revision", "Una de las personas cambió; vuelve a cargarlas.")

        revision_values = PersonRevision.objects.filter(
            organization_id=authorization.organization_id, person=source_person
        ).values_list("revision", "phone_e164", "email")
        alias_values: set[tuple[str, str, int]] = {
            (PersonContactAlias.Kind.PHONE, source_person.phone_e164, source_person.revision)
        }
        if source_person.email:
            alias_values.add(
                (PersonContactAlias.Kind.EMAIL, source_person.email, source_person.revision)
            )
        for revision_value, phone, email in revision_values:
            alias_values.add((PersonContactAlias.Kind.PHONE, phone, revision_value))
            if email:
                alias_values.add((PersonContactAlias.Kind.EMAIL, email, revision_value))
        for kind, value, _ in alias_values:
            alias = PersonContactAlias.objects.filter(
                organization_id=authorization.organization_id,
                kind=kind,
                normalized_value=value,
            ).first()
            if alias is not None and canonical_person_id(
                authorization.organization_id, alias.person_id
            ) not in {source_id, target_id}:
                raise conflict("alias_conflict", "Un contacto pertenece a otra persona.")
        try:
            with transaction.atomic():
                merge = PersonMerge.objects.create(
                    organization_id=authorization.organization_id,
                    source_person=source_person,
                    target_person=target_person,
                    source_revision=source_revision,
                    target_revision=target_revision,
                    reason=canonical_reason,
                    idempotency_key=key,
                    merged_by_membership_id=authorization.membership_id,
                )
                for kind, value, revision_value in sorted(alias_values):
                    PersonContactAlias.objects.get_or_create(
                        organization_id=authorization.organization_id,
                        kind=kind,
                        normalized_value=value,
                        defaults={
                            "person": target_person,
                            "source_person": source_person,
                            "source_revision": revision_value,
                        },
                    )
        except IntegrityError as error:
            raise conflict(
                "merge_conflict", "La fusión entró en conflicto; vuelve a cargar."
            ) from error
        return _merge_data(merge)


def _effective_consents(rows: tuple[ConsentEvent, ...]) -> tuple[dict[str, Any], ...]:
    grouped: dict[tuple[str, str], list[ConsentEvent]] = defaultdict(list)
    for row in rows:
        grouped[(row.purpose, row.channel)].append(row)
    result = []
    for (purpose, channel), events in sorted(grouped.items()):
        latest = max(
            events,
            key=lambda event: (
                event.occurred_at,
                event.created_at,
                event.decision == ConsentEvent.Decision.REVOKED,
            ),
        )
        result.append(
            {
                "purpose": purpose,
                "channel": channel,
                "decision": latest.decision,
                "event_id": latest.pk,
                "occurred_at": latest.occurred_at,
            }
        )
    return tuple(result)


def list_consents(
    actor: User, organization_reference: UUID | str, *, person_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        authorization.require(Capability.CONSENT_READ)
        get_person_raw(authorization.organization_id, person_id)
        canonical_id = canonical_person_id(authorization.organization_id, person_id)
        cluster = canonical_cluster_ids(authorization.organization_id, canonical_id)
        rows = tuple(
            ConsentEvent.objects.filter(
                organization_id=authorization.organization_id, person_id__in=cluster
            ).order_by("occurred_at", "created_at", "id")
        )
        return {
            "person_id": canonical_id,
            "effective": _effective_consents(rows),
            "events": tuple(
                {
                    "id": row.pk,
                    "person_id": row.person_id,
                    "purpose": row.purpose,
                    "channel": row.channel,
                    "event_type": row.event_type,
                    "decision": row.decision,
                    "source": row.source,
                    "occurred_at": row.occurred_at,
                    "evidence_reference": row.evidence_reference,
                    "corrects_id": row.corrects_id,
                    "recorded_by_membership_id": row.recorded_by_membership_id,
                    "created_at": row.created_at,
                }
                for row in rows
            ),
        }


def record_consent(
    actor: User,
    organization_reference: UUID | str,
    *,
    person_id: UUID | str,
    purpose: str,
    channel: str,
    event_type: str,
    decision: str,
    source: str,
    occurred_at: datetime,
    evidence_reference: str,
    corrects_id: UUID | str | None = None,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        authorization.require(Capability.CONSENT_MANAGE)
        person = require_canonical_person(authorization.organization_id, person_id, lock=True)
        try:
            purpose_value = canonical_text(purpose, field="El propósito", max_length=80)
            source_value = canonical_text(source, field="El origen", max_length=80)
            evidence = canonical_text(evidence_reference, field="La evidencia", max_length=240)
            channel_value = ConsentEvent.Channel(channel)
            event_type_value = ConsentEvent.EventType(event_type)
            decision_value = ConsentEvent.Decision(decision)
        except ValueError as error:
            raise invalid(str(error) or "El consentimiento no es válido.") from error
        correction = None
        if corrects_id is not None:
            try:
                correction = ConsentEvent.objects.get(
                    organization_id=authorization.organization_id,
                    pk=_uuid(corrects_id, "El consentimiento"),
                    person_id__in=canonical_cluster_ids(authorization.organization_id, person.pk),
                )
            except ConsentEvent.DoesNotExist:
                raise unavailable("El consentimiento") from None
        try:
            row = ConsentEvent.objects.create(
                organization_id=authorization.organization_id,
                person=person,
                purpose=purpose_value,
                channel=channel_value,
                event_type=event_type_value,
                decision=decision_value,
                source=source_value,
                occurred_at=_aware(occurred_at, "La fecha"),
                evidence_reference=evidence,
                corrects=correction,
                recorded_by_membership_id=authorization.membership_id,
            )
        except IntegrityError as error:
            raise conflict("consent_conflict", "El consentimiento no pudo registrarse.") from error
        return {
            "id": row.pk,
            "person_id": row.person_id,
            "purpose": row.purpose,
            "channel": row.channel,
            "event_type": row.event_type,
            "decision": row.decision,
            "source": row.source,
            "occurred_at": row.occurred_at,
            "evidence_reference": row.evidence_reference,
            "corrects_id": row.corrects_id,
            "created_at": row.created_at,
        }
