from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from django.db import IntegrityError
from django.utils import timezone

from claridez.commercial.models import EventRequest, EventRequestHistory, Reservation
from claridez.commercial.public import (
    confirmed_evidence_for_people,
    interest_evidence_for_people,
    opportunities_for_crm,
    opportunity_for_crm,
    opportunity_history_for_crm,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import (
    Capability,
    capabilities_for_role,
    require_capability,
)
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.models import Membership
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope
from claridez.people import public as people_port
from claridez.people.models import Person, PersonContactAlias
from claridez.people.normalization import canonical_optional_text, canonical_text

from .errors import conflict, invalid, unavailable
from .models import FollowUpTask, Interaction

CRM_CAPABILITIES = frozenset(
    {
        Capability.PERSON_READ,
        Capability.PERSON_MANAGE,
        Capability.PERSON_MERGE,
        Capability.SALES_READ,
        Capability.SALES_MANAGE,
        Capability.INTERACTION_READ,
        Capability.INTERACTION_RECORD,
        Capability.TASK_MANAGE,
        Capability.CONSENT_READ,
        Capability.CONSENT_MANAGE,
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


def _can(authorization: TenantAuthorization, capability: Capability) -> bool:
    return capability in capabilities_for_role(authorization.role)


def crm_capabilities(actor: User, organization_reference: UUID | str) -> tuple[str, ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.ORGANIZATION_ACCESS
    ) as authorization:
        available = capabilities_for_role(authorization.role) & CRM_CAPABILITIES
        return tuple(sorted(capability.value for capability in available))


def _membership(
    authorization: TenantAuthorization,
    reference: UUID | str | None,
    capability: Capability,
) -> Membership:
    membership_id = (
        authorization.membership_id
        if reference is None
        else _uuid(reference, "La membresía responsable")
    )
    try:
        row = Membership.objects.get(
            organization_id=authorization.organization_id,
            pk=membership_id,
            status=Membership.Status.ACTIVE,
        )
    except Membership.DoesNotExist:
        raise unavailable("La membresía responsable") from None
    try:
        require_capability(row.role, capability)
    except AuthorizationDenied:
        raise invalid("La membresía no puede asumir este seguimiento.") from None
    return row


def _canonical_person(
    authorization: TenantAuthorization, person_id: UUID | str, *, lock: bool = False
) -> Person:
    return people_port.require_canonical_person(authorization.organization_id, person_id, lock=lock)


def _linked_request(
    authorization: TenantAuthorization,
    reference: UUID | str | None,
    person: Person,
) -> EventRequest | None:
    if reference is None:
        return None
    authorization.require(Capability.SALES_READ)
    row = opportunity_for_crm(authorization, _uuid(reference, "La oportunidad"))
    if people_port.canonical_person_id(authorization.organization_id, row.person_id) != person.pk:
        raise invalid("La oportunidad no pertenece a la persona canónica.")
    return row


def _person_summary(authorization: TenantAuthorization, person_id: UUID | str) -> dict[str, Any]:
    canonical_id = people_port.canonical_person_id(authorization.organization_id, person_id)
    person = people_port.get_person_raw(authorization.organization_id, canonical_id)
    cluster = people_port.canonical_cluster_ids(authorization.organization_id, canonical_id)
    return {
        "id": person.pk,
        "full_name": person.full_name,
        "phone_e164": person.phone_e164,
        "email": person.email or None,
        "revision": person.revision,
        "has_interest_history": interest_evidence_for_people(authorization, cluster),
        "is_client": confirmed_evidence_for_people(authorization, cluster),
    }


def _interaction_data(row: Interaction) -> dict[str, Any]:
    return {
        "id": row.pk,
        "person_id": row.person_id,
        "event_request_id": row.event_request_id,
        "channel": row.channel,
        "direction": row.direction,
        "occurred_at": row.occurred_at,
        "responsible_membership_id": row.responsible_membership_id,
        "summary": row.summary,
        "correction_of_id": row.correction_of_id,
        "recorded_by_membership_id": row.recorded_by_membership_id,
        "created_at": row.created_at,
    }


def _task_data(row: FollowUpTask, *, include_history: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": row.pk,
        "person_id": row.person_id,
        "event_request_id": row.event_request_id,
        "title": row.title,
        "due_at": row.due_at,
        "next_contact_at": row.next_contact_at,
        "status": row.status,
        "responsible_membership_id": row.responsible_membership_id,
        "completed_at": row.completed_at,
        "completed_by_membership_id": row.completed_by_membership_id,
        "revision": row.revision,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "overdue": row.status == FollowUpTask.Status.OPEN and row.due_at < timezone.now(),
    }
    if include_history:
        data["history"] = tuple(
            {
                "id": history.pk,
                "kind": history.kind,
                "revision": history.revision,
                "title": history.title,
                "due_at": history.due_at,
                "next_contact_at": history.next_contact_at,
                "status": history.status,
                "responsible_membership_id": history.responsible_membership_id,
                "changed_by_membership_id": history.changed_by_membership_id,
                "reason": history.reason or None,
                "created_at": history.created_at,
            }
            for history in row.history.all().order_by("revision", "id")
        )
    return data


def _history_data(row: EventRequestHistory) -> dict[str, Any]:
    return {
        "id": row.pk,
        "kind": row.kind,
        "status": row.status,
        "request_revision": row.request_revision,
        "origin": row.origin,
        "origin_detail": row.origin_detail or None,
        "responsible_membership_id": row.responsible_membership_id,
        "actor_membership_id": row.actor_membership_id,
        "occurred_at": row.occurred_at,
        "provenance": row.provenance,
        "reason": row.reason or None,
        "recorded_at": row.created_at,
    }


def _opportunity_data(
    authorization: TenantAuthorization, row: EventRequest, *, detailed: bool = False
) -> dict[str, Any]:
    person = _person_summary(authorization, row.person_id)
    won = Reservation.objects.filter(
        organization_id=authorization.organization_id,
        event_request=row,
        confirmed_at__isnull=False,
    ).exists()
    result = "won" if won else "lost" if row.status == EventRequest.Status.CLOSED_LOST else "open"
    next_task = (
        FollowUpTask.objects.filter(
            organization_id=authorization.organization_id,
            event_request=row,
            status=FollowUpTask.Status.OPEN,
        )
        .order_by("next_contact_at", "due_at", "id")
        .first()
    )
    data: dict[str, Any] = {
        "id": row.pk,
        "person": person,
        "event_type": row.event_type,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "status": row.status,
        "result": result,
        "origin": row.origin,
        "origin_detail": row.origin_detail or None,
        "responsible_membership_id": row.responsible_membership_id,
        "closed_reason": row.closed_reason or None,
        "revision": row.revision,
        "next_action": _task_data(next_task) if next_task is not None else None,
        "updated_at": row.updated_at,
    }
    if detailed:
        data.update(
            {
                "general_need": row.general_need,
                "notes": row.notes,
                "estimated_guests": row.estimated_guests,
                "venue": {"id": row.space.venue_id, "name": row.space.venue.name},
                "space": {"id": row.space_id, "name": row.space.name},
                "history": tuple(
                    _history_data(history)
                    for history in opportunity_history_for_crm(authorization, row.pk)
                ),
            }
        )
    return data


def list_opportunities(
    actor: User, organization_reference: UUID | str, *, status: str = ""
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_READ
    ) as authorization:
        authorization.require(Capability.PERSON_READ)
        return tuple(
            _opportunity_data(authorization, row)
            for row in opportunities_for_crm(authorization, status=status)
        )


def read_opportunity(
    actor: User, organization_reference: UUID | str, *, request_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_READ
    ) as authorization:
        authorization.require(Capability.PERSON_READ)
        return _opportunity_data(
            authorization,
            opportunity_for_crm(authorization, _uuid(request_id, "La oportunidad")),
            detailed=True,
        )


def read_opportunity_history(
    actor: User, organization_reference: UUID | str, *, request_id: UUID | str
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_READ
    ) as authorization:
        authorization.require(Capability.PERSON_READ)
        return tuple(
            _history_data(row)
            for row in opportunity_history_for_crm(
                authorization, _uuid(request_id, "La oportunidad")
            )
        )


def list_interactions(
    actor: User,
    organization_reference: UUID | str,
    *,
    person_id: UUID | str | None = None,
    event_request_id: UUID | str | None = None,
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        authorization.require(Capability.INTERACTION_READ)
        rows = Interaction.objects.filter(organization_id=authorization.organization_id)
        if person_id is not None:
            people_port.get_person_raw(authorization.organization_id, person_id)
            cluster = people_port.canonical_cluster_ids(authorization.organization_id, person_id)
            rows = rows.filter(person_id__in=cluster)
        if event_request_id is not None:
            authorization.require(Capability.SALES_READ)
            request_id = _uuid(event_request_id, "La oportunidad")
            opportunity_for_crm(authorization, request_id)
            rows = rows.filter(event_request_id=request_id)
        elif not _can(authorization, Capability.SALES_READ):
            rows = rows.filter(event_request__isnull=True)
        return tuple(_interaction_data(row) for row in rows.order_by("-occurred_at", "-id")[:200])


def record_interaction(
    actor: User,
    organization_reference: UUID | str,
    *,
    person_id: UUID | str,
    event_request_id: UUID | str | None,
    channel: str,
    direction: str,
    occurred_at: datetime,
    summary: str,
    responsible_membership_id: UUID | str | None = None,
    correction_of_id: UUID | str | None = None,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        authorization.require(Capability.INTERACTION_RECORD)
        person = _canonical_person(authorization, person_id, lock=True)
        event_request = _linked_request(authorization, event_request_id, person)
        responsible = _membership(
            authorization, responsible_membership_id, Capability.INTERACTION_RECORD
        )
        try:
            channel_value = Interaction.Channel(channel)
            direction_value = Interaction.Direction(direction)
            summary_value = canonical_text(summary, field="El resumen", max_length=1000)
        except ValueError as error:
            raise invalid(str(error) or "La interacción no es válida.") from error
        correction = None
        if correction_of_id is not None:
            try:
                correction = Interaction.objects.get(
                    organization_id=authorization.organization_id,
                    pk=_uuid(correction_of_id, "La interacción"),
                    person=person,
                    event_request=event_request,
                )
            except Interaction.DoesNotExist:
                raise unavailable("La interacción") from None
        try:
            row = Interaction.objects.create(
                organization_id=authorization.organization_id,
                person=person,
                event_request=event_request,
                channel=channel_value,
                direction=direction_value,
                occurred_at=_aware(occurred_at, "La fecha"),
                responsible_membership=responsible,
                summary=summary_value,
                correction_of=correction,
                recorded_by_membership_id=authorization.membership_id,
            )
        except IntegrityError as error:
            raise conflict("interaction_conflict", "La interacción no pudo registrarse.") from error
        return _interaction_data(row)


def list_tasks(
    actor: User,
    organization_reference: UUID | str,
    *,
    person_id: UUID | str | None = None,
    event_request_id: UUID | str | None = None,
    status: str = "",
) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        authorization.require(Capability.TASK_MANAGE)
        rows = FollowUpTask.objects.filter(organization_id=authorization.organization_id)
        if person_id is not None:
            people_port.get_person_raw(authorization.organization_id, person_id)
            rows = rows.filter(
                person_id__in=people_port.canonical_cluster_ids(
                    authorization.organization_id, person_id
                )
            )
        if event_request_id is not None:
            authorization.require(Capability.SALES_READ)
            request_id = _uuid(event_request_id, "La oportunidad")
            opportunity_for_crm(authorization, request_id)
            rows = rows.filter(event_request_id=request_id)
        elif not _can(authorization, Capability.SALES_READ):
            rows = rows.filter(event_request__isnull=True)
        if status:
            rows = rows.filter(status=status)
        return tuple(
            _task_data(row, include_history=True) for row in rows.order_by("due_at", "id")[:200]
        )


def create_task(
    actor: User,
    organization_reference: UUID | str,
    *,
    person_id: UUID | str,
    event_request_id: UUID | str | None,
    title: str,
    due_at: datetime,
    next_contact_at: datetime | None,
    responsible_membership_id: UUID | str | None = None,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        authorization.require(Capability.TASK_MANAGE)
        person = _canonical_person(authorization, person_id, lock=True)
        event_request = _linked_request(authorization, event_request_id, person)
        responsible = _membership(authorization, responsible_membership_id, Capability.TASK_MANAGE)
        try:
            title_value = canonical_text(title, field="La tarea", max_length=180)
        except ValueError as error:
            raise invalid(str(error)) from error
        try:
            row = FollowUpTask.objects.create(
                organization_id=authorization.organization_id,
                person=person,
                event_request=event_request,
                title=title_value,
                due_at=_aware(due_at, "El vencimiento"),
                next_contact_at=(
                    _aware(next_contact_at, "El próximo contacto")
                    if next_contact_at is not None
                    else None
                ),
                responsible_membership=responsible,
                created_by_membership_id=authorization.membership_id,
            )
        except IntegrityError as error:
            raise conflict("task_conflict", "La tarea no pudo registrarse.") from error
        return _task_data(row, include_history=True)


def update_task(
    actor: User,
    organization_reference: UUID | str,
    *,
    task_id: UUID | str,
    revision: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        authorization.require(Capability.TASK_MANAGE)
        try:
            row = FollowUpTask.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                pk=_uuid(task_id, "La tarea"),
            )
        except FollowUpTask.DoesNotExist:
            raise unavailable("La tarea") from None
        if row.event_request_id is not None:
            authorization.require(Capability.SALES_READ)
        if row.revision != revision:
            raise conflict("stale_revision", "La tarea cambió; vuelve a cargarla.")
        if row.status != FollowUpTask.Status.OPEN:
            raise conflict("task_closed", "La tarea ya está finalizada.")
        try:
            if "title" in changes:
                row.title = canonical_text(str(changes["title"]), field="La tarea", max_length=180)
            if "due_at" in changes:
                row.due_at = _aware(changes["due_at"], "El vencimiento")
            if "next_contact_at" in changes:
                value = changes["next_contact_at"]
                row.next_contact_at = (
                    _aware(value, "El próximo contacto") if value is not None else None
                )
            if "responsible_membership_id" in changes:
                row.responsible_membership = _membership(
                    authorization, changes["responsible_membership_id"], Capability.TASK_MANAGE
                )
            if "status" in changes:
                status_value = FollowUpTask.Status(changes["status"])
                if status_value == FollowUpTask.Status.OPEN:
                    raise ValueError("La tarea ya está pendiente.")
                row.status = status_value
                if status_value == FollowUpTask.Status.COMPLETED:
                    row.completed_at = timezone.now()
                    row.completed_by_membership_id = authorization.membership_id
                else:
                    reason = canonical_optional_text(
                        changes.get("reason"), field="La razón", max_length=500
                    )
                    if not reason:
                        raise ValueError("La cancelación requiere una razón.")
        except (TypeError, ValueError) as error:
            raise invalid(str(error)) from error
        row.revision += 1
        try:
            row.save()
        except IntegrityError as error:
            raise conflict("task_conflict", "La tarea no pudo actualizarse.") from error
        return _task_data(row, include_history=True)


def indicators(actor: User, organization_reference: UUID | str) -> dict[str, int]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.SALES_READ
    ) as authorization:
        authorization.require(Capability.PERSON_READ)
        requests = opportunities_for_crm(authorization)
        won_ids = set(
            Reservation.objects.filter(
                organization_id=authorization.organization_id,
                confirmed_at__isnull=False,
            ).values_list("event_request_id", flat=True)
        )
        request_ids = set(requests.values_list("id", flat=True))
        open_ids = {
            row.pk
            for row in requests
            if row.status not in {EventRequest.Status.CLOSED_LOST, EventRequest.Status.CANCELLED}
        }
        with_task = set(
            FollowUpTask.objects.filter(
                organization_id=authorization.organization_id,
                event_request_id__in=open_ids,
                status=FollowUpTask.Status.OPEN,
            ).values_list("event_request_id", flat=True)
        )
        return {
            "opportunities": len(request_ids),
            "open": len(open_ids),
            "won": len(request_ids & won_ids),
            "lost": requests.filter(status=EventRequest.Status.CLOSED_LOST)
            .exclude(pk__in=won_ids)
            .count(),
            "without_next_action": len(open_ids - with_task),
            "overdue_tasks": FollowUpTask.objects.filter(
                organization_id=authorization.organization_id,
                status=FollowUpTask.Status.OPEN,
                due_at__lt=timezone.now(),
            ).count(),
        }


def person_overview(
    actor: User, organization_reference: UUID | str, *, person_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.PERSON_READ
    ) as authorization:
        authorization.require(Capability.SALES_READ)
        authorization.require(Capability.INTERACTION_READ)
        authorization.require(Capability.TASK_MANAGE)
        authorization.require(Capability.CONSENT_READ)
        people_port.get_person_raw(authorization.organization_id, person_id)
        canonical_id = people_port.canonical_person_id(authorization.organization_id, person_id)
        cluster = people_port.canonical_cluster_ids(authorization.organization_id, canonical_id)
        person = _person_summary(authorization, canonical_id)
        person["aliases"] = tuple(
            {
                "kind": alias.kind,
                "value": alias.normalized_value,
                "source_person_id": alias.source_person_id,
            }
            for alias in PersonContactAlias.objects.filter(
                organization_id=authorization.organization_id, person_id__in=cluster
            ).order_by("kind", "normalized_value")
        )
        opportunities = tuple(
            _opportunity_data(authorization, row)
            for row in opportunities_for_crm(authorization).filter(person_id__in=cluster)
        )
        interactions = tuple(
            _interaction_data(row)
            for row in Interaction.objects.filter(
                organization_id=authorization.organization_id, person_id__in=cluster
            ).order_by("-occurred_at", "-id")
        )
        tasks = tuple(
            _task_data(row, include_history=True)
            for row in FollowUpTask.objects.filter(
                organization_id=authorization.organization_id, person_id__in=cluster
            ).order_by("due_at", "id")
        )
        consent = people_port.list_consents(actor, organization_reference, person_id=canonical_id)
        timeline: list[dict[str, Any]] = []
        for opportunity in opportunities:
            for history in opportunity_history_for_crm(authorization, UUID(str(opportunity["id"]))):
                timeline.append(
                    {
                        "type": "opportunity",
                        "at": history.occurred_at or history.created_at,
                        "data": _history_data(history),
                    }
                )
        timeline.extend(
            {"type": "interaction", "at": row["occurred_at"], "data": row} for row in interactions
        )
        for task in tasks:
            for history in task["history"]:
                timeline.append({"type": "task", "at": history["created_at"], "data": history})
        timeline.sort(key=lambda item: item["at"], reverse=True)
        return {
            "person": person,
            "opportunities": opportunities,
            "interactions": interactions,
            "tasks": tasks,
            "consent": consent,
            "timeline": tuple(timeline),
        }
