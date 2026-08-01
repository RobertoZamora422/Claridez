from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import F, Prefetch
from django.db.models.query import QuerySet
from django.utils import timezone

from claridez.commercial.models import Reservation
from claridez.commercial.normalization import canonical_optional_text, canonical_text
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.models import Membership, OrganizationSettings
from claridez.organizations.tenant_scope import authorized_tenant_scope

from .baseline import (
    BASELINE,
    BASELINE_KEYS,
    BASELINE_VERSION,
    baseline_item_id,
    baseline_request_id,
    due_date,
    transition_id,
)
from .errors import conflict, invalid, unavailable
from .models import EventPreparation, PreparationItem, PreparationTransition
from .representations import preparation_representation

OPERATION_CAPABILITIES = frozenset(
    {Capability.OPERATION_READ, Capability.OPERATION_MANAGE, Capability.OPERATION_EXECUTE}
)
EDITABLE_PREPARATION_STATES = {
    EventPreparation.Status.PREPARING,
    EventPreparation.Status.READY,
}
ELIGIBLE_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.ADMINISTRATOR,
    Membership.Role.OPERATIONS,
}
_UNSET = object()


def _uuid(value: UUID | str, resource: str = "El recurso") -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise unavailable(resource) from None


def _preparation_rows(*, lock: bool = False) -> QuerySet[EventPreparation]:
    rows = EventPreparation.objects.select_related(
        "reservation__quotation_version",
        "reservation__event_request__person",
        "responsible_membership__user",
        "ready_by_membership__user",
        "started_by_membership__user",
        "completed_by_membership__user",
    ).prefetch_related(
        Prefetch(
            "items",
            queryset=PreparationItem.objects.select_related(
                "responsible_membership__user", "resolved_by_membership__user"
            ).order_by("position", "id"),
        )
    )
    return rows.select_for_update(of=("self",)) if lock else rows


def _get_preparation(
    organization_id: UUID, reservation_id: UUID | str, *, lock: bool = False
) -> EventPreparation:
    try:
        return _preparation_rows(lock=lock).get(
            organization_id=organization_id,
            reservation_id=_uuid(reservation_id, "La preparación"),
        )
    except EventPreparation.DoesNotExist:
        raise unavailable("La preparación") from None


def _eligible_membership(organization_id: UUID, membership_id: UUID | str) -> Membership:
    try:
        membership = Membership.objects.select_related("user").get(
            organization_id=organization_id,
            pk=_uuid(membership_id, "La membresía"),
            status=Membership.Status.ACTIVE,
            role__in=ELIGIBLE_ROLES,
        )
    except Membership.DoesNotExist:
        raise unavailable("La membresía") from None
    if Capability.OPERATION_MANAGE not in capabilities_for_role(membership.role):
        raise unavailable("La membresía")
    return membership


def _check_revision(preparation: EventPreparation, revision: int) -> None:
    if preparation.revision != revision:
        raise conflict("stale_revision", "La preparación cambió. Vuelve a cargarla.")


def _increment_preparation(preparation: EventPreparation, *, fields: list[str]) -> None:
    preparation.revision = F("revision") + 1
    preparation.save(update_fields=[*fields, "revision", "updated_at"])
    preparation.refresh_from_db()


def _transition(
    preparation: EventPreparation,
    *,
    from_status: str | None,
    to_status: str,
    cause: str,
    actor_membership_id: UUID,
    occurred_at: datetime,
    identifier: UUID | None = None,
) -> PreparationTransition:
    values: dict[str, Any] = {
        "organization_id": preparation.organization_id,
        "preparation_id": preparation.pk,
        "from_status": from_status,
        "to_status": to_status,
        "cause": cause,
        "actor_membership_id": actor_membership_id,
        "preparation_revision": preparation.revision,
        "occurred_at": occurred_at,
    }
    if identifier is not None:
        values["id"] = identifier
    return PreparationTransition.objects.create(**values)


def initialize_preparation(
    reservation: Reservation, *, actor_membership_id: UUID, occurred_at: datetime
) -> EventPreparation:
    """Crear el agregado base; solo lo invoca el coordinador de confirmación."""
    preparation = EventPreparation.objects.create(
        reservation=reservation,
        organization_id=reservation.organization_id,
        status=EventPreparation.Status.PREPARING,
        baseline_version=BASELINE_VERSION,
        revision=1,
    )
    starts_at = reservation.quotation_version.event_starts_at_snapshot
    items = [
        PreparationItem(
            id=baseline_item_id(reservation.pk, definition.key),
            organization_id=reservation.organization_id,
            preparation=preparation,
            client_request_id=baseline_request_id(reservation.pk, definition.key),
            baseline_key=definition.key,
            section=definition.section,
            position=position,
            title=definition.title,
            is_required=True,
            due_on=due_date(
                starts_at=starts_at,
                timezone_name=reservation.event_timezone,
                confirmed_at=occurred_at,
                days_before=definition.days_before,
            ),
        )
        for position, definition in enumerate(BASELINE, start=1)
    ]
    PreparationItem.objects.bulk_create(items)
    _transition(
        preparation,
        from_status=None,
        to_status=EventPreparation.Status.PREPARING,
        cause=PreparationTransition.Cause.INITIALIZED,
        actor_membership_id=actor_membership_id,
        occurred_at=occurred_at,
        identifier=transition_id(reservation.pk, PreparationTransition.Cause.INITIALIZED),
    )
    return preparation


def validate_initialized_preparation(reservation: Reservation) -> EventPreparation:
    try:
        preparation = EventPreparation.objects.select_for_update().get(
            organization_id=reservation.organization_id, reservation_id=reservation.pk
        )
    except EventPreparation.DoesNotExist:
        raise conflict(
            "operation_integrity_conflict", "La reserva no tiene una preparación operativa íntegra."
        ) from None
    keys = list(
        PreparationItem.objects.filter(
            organization_id=reservation.organization_id, preparation_id=reservation.pk
        ).values_list("baseline_key", flat=True)
    )
    initialized_count = PreparationTransition.objects.filter(
        organization_id=reservation.organization_id,
        preparation_id=reservation.pk,
        cause=PreparationTransition.Cause.INITIALIZED,
    ).count()
    if set(filter(None, keys)) != BASELINE_KEYS or len(keys) < 7 or initialized_count != 1:
        raise conflict(
            "operation_integrity_conflict", "La reserva no tiene una preparación operativa íntegra."
        )
    return preparation


def cancel_preparation(
    preparation: EventPreparation, *, actor_membership_id: UUID, occurred_at: datetime
) -> None:
    if preparation.status == EventPreparation.Status.CANCELLED:
        return
    if preparation.status == EventPreparation.Status.IN_PROGRESS:
        raise conflict("operation_already_started", "El evento ya está en ejecución.")
    if preparation.status == EventPreparation.Status.COMPLETED:
        raise conflict("operation_already_completed", "El evento ya fue completado.")
    if preparation.status not in EDITABLE_PREPARATION_STATES:
        raise conflict("invalid_transition", "La preparación no puede cancelarse.")
    previous = preparation.status
    preparation.status = EventPreparation.Status.CANCELLED
    _increment_preparation(preparation, fields=["status"])
    _transition(
        preparation,
        from_status=previous,
        to_status=EventPreparation.Status.CANCELLED,
        cause=PreparationTransition.Cause.COMMERCIAL_CANCELLATION,
        actor_membership_id=actor_membership_id,
        occurred_at=occurred_at,
    )


def operation_capabilities(actor: User, organization_reference: UUID | str) -> tuple[str, ...]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.ORGANIZATION_ACCESS
    ) as authorization:
        available = capabilities_for_role(authorization.role) & OPERATION_CAPABILITIES
        return tuple(sorted(capability.value for capability in available))


def list_assignees(actor: User, organization_reference: UUID | str) -> list[dict[str, Any]]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_MANAGE
    ) as authorization:
        memberships = (
            Membership.objects.select_related("user")
            .filter(
                organization_id=authorization.organization_id,
                status=Membership.Status.ACTIVE,
                role__in=ELIGIBLE_ROLES,
            )
            .order_by("user__display_name", "id")
        )
        return [
            {
                "membership_id": membership.pk,
                "display_name": membership.user.display_name or "Miembro del equipo",
                "role": membership.role,
            }
            for membership in memberships
        ]


def read_event(
    actor: User, organization_reference: UUID | str, *, reservation_id: UUID | str
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_READ
    ) as authorization:
        preparation = _get_preparation(authorization.organization_id, reservation_id)
        return preparation_representation(preparation, now=timezone.now(), include_items=True)


def list_events(
    actor: User,
    organization_reference: UUID | str,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    statuses: list[str] | None = None,
    attention: str | None = None,
    responsible_membership_id: UUID | None = None,
    offset: int = 0,
    page_size: int = 25,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_READ
    ) as authorization:
        rows = _preparation_rows().filter(organization_id=authorization.organization_id)
        organization_timezone = ZoneInfo(
            OrganizationSettings.objects.only("timezone")
            .get(organization_id=authorization.organization_id)
            .timezone
        )
        if statuses:
            rows = rows.filter(status__in=statuses)
        else:
            rows = rows.exclude(
                status__in=[EventPreparation.Status.COMPLETED, EventPreparation.Status.CANCELLED]
            )
        if responsible_membership_id:
            rows = rows.filter(responsible_membership_id=responsible_membership_id)
        if from_date:
            rows = rows.filter(
                reservation__quotation_version__event_ends_at_snapshot__gte=datetime.combine(
                    from_date, time.min, tzinfo=organization_timezone
                )
            )
        if to_date:
            rows = rows.filter(
                reservation__quotation_version__event_starts_at_snapshot__lt=datetime.combine(
                    to_date + timedelta(days=1), time.min, tzinfo=organization_timezone
                )
            )
        if from_date is None and to_date is None:
            local_today = timezone.now().astimezone(organization_timezone).date()
            rows = rows.filter(
                reservation__quotation_version__event_starts_at_snapshot__lt=datetime.combine(
                    local_today + timedelta(days=31), time.min, tzinfo=organization_timezone
                )
            )
        rows = rows.order_by(
            "reservation__quotation_version__event_starts_at_snapshot", "reservation_id"
        )
        now = timezone.now()
        represented = [
            preparation_representation(row, now=now, include_items=False) for row in rows
        ]
        if attention:
            key = {
                "overdue": "is_overdue",
                "upcoming": "is_upcoming",
                "blocked": "has_blockers",
                "ready": "is_ready",
                "unassigned": None,
            }.get(attention)
            if attention == "unassigned":
                represented = [
                    row for row in represented if row["preparation"]["responsible"] is None
                ]
            elif key:
                represented = [row for row in represented if row["preparation"]["attention"][key]]
        page = represented[offset : offset + page_size]
        next_offset = offset + page_size if offset + page_size < len(represented) else None
        return {"results": page, "next_cursor": str(next_offset) if next_offset else None}


def update_preparation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    revision: int,
    operational_notes: str,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_MANAGE
    ) as authorization:
        preparation = _get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status not in EDITABLE_PREPARATION_STATES:
            raise conflict("invalid_transition", "La preparación ya no puede editarse.")
        _check_revision(preparation, revision)
        try:
            notes = canonical_optional_text(
                operational_notes, field="Las notas operativas", max_length=4000
            )
        except ValueError as error:
            raise invalid(str(error)) from error
        if preparation.operational_notes != notes:
            preparation.operational_notes = notes
            _increment_preparation(preparation, fields=["operational_notes"])
        return preparation_representation(
            _get_preparation(authorization.organization_id, reservation_id),
            now=timezone.now(),
            include_items=True,
        )


def assign_preparation(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    revision: int,
    responsible_membership_id: UUID | str,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_MANAGE
    ) as authorization:
        preparation = _get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status in {
            EventPreparation.Status.COMPLETED,
            EventPreparation.Status.CANCELLED,
        }:
            raise conflict("invalid_transition", "La preparación ya no puede asignarse.")
        _check_revision(preparation, revision)
        responsible = _eligible_membership(authorization.organization_id, responsible_membership_id)
        if preparation.responsible_membership_id != responsible.pk:
            preparation.responsible_membership = responsible
            _increment_preparation(preparation, fields=["responsible_membership"])
        return preparation_representation(
            _get_preparation(authorization.organization_id, reservation_id),
            now=timezone.now(),
            include_items=True,
        )


def _canonical_item_values(
    values: dict[str, Any], *, current: PreparationItem | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        if "title" in values:
            result["title"] = canonical_text(values["title"], field="El título", max_length=160)
        if "notes" in values:
            result["notes"] = canonical_optional_text(
                values.get("notes"), field="Las notas", max_length=2000
            )
        if "status_note" in values:
            result["status_note"] = canonical_optional_text(
                values.get("status_note"), field="La explicación", max_length=500
            )
    except ValueError as error:
        raise invalid(str(error)) from error
    for field in ("section", "is_required", "due_on", "status"):
        if field in values:
            result[field] = values[field]
    status = result.get("status", current.status if current else PreparationItem.Status.PENDING)
    status_note = result.get("status_note", current.status_note if current else "")
    if status in {PreparationItem.Status.BLOCKED, PreparationItem.Status.NOT_APPLICABLE}:
        if not status_note:
            raise invalid("La explicación es obligatoria para este estado.")
    elif status_note:
        raise invalid("La explicación solo se admite para bloqueado o no aplica.")
    if (
        current is not None
        and current.baseline_key == "final_readiness_review"
        and status == PreparationItem.Status.NOT_APPLICABLE
    ):
        raise conflict(
            "invalid_item_transition", "La revisión final no puede marcarse como no aplica."
        )
    return result


def create_item(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    client_request_id: UUID,
    values: dict[str, Any],
    place_before_item_id: UUID | None = None,
) -> tuple[dict[str, Any], bool]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_MANAGE
    ) as authorization:
        preparation = _get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status not in EDITABLE_PREPARATION_STATES:
            raise conflict("invalid_transition", "El checklist ya no puede editarse.")
        canonical = _canonical_item_values(values)
        if (
            "responsible_membership_id" in values
            and values["responsible_membership_id"] is not None
        ):
            canonical["responsible_membership_id"] = _eligible_membership(
                authorization.organization_id, values["responsible_membership_id"]
            ).pk
        existing = PreparationItem.objects.filter(
            organization_id=authorization.organization_id,
            preparation=preparation,
            client_request_id=client_request_id,
        ).first()
        if existing is not None:
            comparable = {
                "title": existing.title,
                "section": existing.section,
                "is_required": existing.is_required,
                "due_on": existing.due_on,
                "notes": existing.notes,
                "status": existing.status,
                "status_note": existing.status_note,
                "responsible_membership_id": existing.responsible_membership_id,
            }
            expected = {**comparable, **canonical}
            if comparable != expected:
                raise conflict(
                    "idempotency_conflict", "El identificador ya se usó con otro contenido."
                )
            return {
                "item": _item_after_reload(existing),
                "preparation_revision": preparation.revision,
            }, False
        ordered_items = list(
            PreparationItem.objects.select_for_update()
            .filter(preparation=preparation)
            .order_by("position", "id")
        )
        position = len(ordered_items) + 1
        if place_before_item_id is not None:
            before_id = _uuid(place_before_item_id)
            try:
                position = next(
                    existing_item.position
                    for existing_item in ordered_items
                    if existing_item.pk == before_id
                )
            except StopIteration:
                raise unavailable("El ítem de referencia") from None
            offset = len(ordered_items) + 1
            PreparationItem.objects.filter(preparation=preparation).update(
                position=F("position") + offset
            )
        was_ready = preparation.status == EventPreparation.Status.READY
        reopens_ready = was_ready and bool(canonical.get("is_required", True))
        if reopens_ready:
            _increment_preparation(preparation, fields=[])
            _reopen(preparation, authorization.membership_id, timezone.now())
        item = PreparationItem.objects.create(
            organization_id=authorization.organization_id,
            preparation=preparation,
            client_request_id=client_request_id,
            position=position,
            status=PreparationItem.Status.PENDING,
            status_note="",
            **canonical,
        )
        if position <= len(ordered_items):
            now = timezone.now()
            for existing_item in ordered_items:
                final_position = (
                    existing_item.position + 1
                    if existing_item.position >= position
                    else existing_item.position
                )
                update_values: dict[str, Any] = {"position": final_position}
                if final_position != existing_item.position:
                    update_values.update(revision=F("revision") + 1, updated_at=now)
                PreparationItem.objects.filter(pk=existing_item.pk).update(**update_values)
        if not reopens_ready:
            _increment_preparation(preparation, fields=[])
        return {
            "item": _item_after_reload(item),
            "preparation_revision": preparation.revision,
            "preparation": {"status": preparation.status, "revision": preparation.revision},
        }, True


def _item_after_reload(item: PreparationItem) -> dict[str, Any]:
    from .representations import item_representation

    return item_representation(
        PreparationItem.objects.select_related(
            "responsible_membership__user", "resolved_by_membership__user"
        ).get(pk=item.pk)
    )


def _reopen(
    preparation: EventPreparation, actor_membership_id: UUID, occurred_at: datetime
) -> None:
    """Reabrir sin incrementar: el comando de ítem ya consumió el único incremento agregado."""
    if preparation.status != EventPreparation.Status.READY:
        return
    preparation.status = EventPreparation.Status.PREPARING
    preparation.ready_at = None
    preparation.ready_by_membership_id = None
    preparation.save(update_fields=["status", "ready_at", "ready_by_membership", "updated_at"])
    _transition(
        preparation,
        from_status=EventPreparation.Status.READY,
        to_status=EventPreparation.Status.PREPARING,
        cause=PreparationTransition.Cause.CHECKLIST_REOPENED,
        actor_membership_id=actor_membership_id,
        occurred_at=occurred_at,
    )


def update_item(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    item_id: UUID | str,
    revision: int,
    values: dict[str, Any],
    place_before_item_id: UUID | None | object = _UNSET,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_MANAGE
    ) as authorization:
        preparation = _get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status not in EDITABLE_PREPARATION_STATES:
            raise conflict("invalid_transition", "El checklist ya no puede editarse.")
        try:
            item = PreparationItem.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=_uuid(item_id),
            )
        except PreparationItem.DoesNotExist:
            raise unavailable("El ítem") from None
        if item.revision != revision:
            raise conflict("stale_revision", "El ítem cambió. Vuelve a cargarlo.")
        canonical = _canonical_item_values(values, current=item)
        if "responsible_membership_id" in values:
            canonical["responsible_membership_id"] = (
                _eligible_membership(
                    authorization.organization_id, values["responsible_membership_id"]
                ).pk
                if values["responsible_membership_id"] is not None
                else None
            )
        changed = {
            field: value for field, value in canonical.items() if getattr(item, field) != value
        }
        ordered_items = list(
            PreparationItem.objects.select_for_update()
            .filter(preparation=preparation)
            .order_by("position", "id")
        )
        reordered_ids = [ordered_item.pk for ordered_item in ordered_items]
        reordered = False
        if place_before_item_id is not _UNSET:
            reordered_ids.remove(item.pk)
            if place_before_item_id is None:
                reordered_ids.append(item.pk)
            else:
                if not isinstance(place_before_item_id, (UUID, str)):
                    raise unavailable("El ítem de referencia")
                before_id = _uuid(place_before_item_id)
                if before_id == item.pk:
                    reordered_ids.insert(item.position - 1, item.pk)
                else:
                    try:
                        before_index = reordered_ids.index(before_id)
                    except ValueError:
                        raise unavailable("El ítem de referencia") from None
                    reordered_ids.insert(before_index, item.pk)
            reordered = reordered_ids != [ordered_item.pk for ordered_item in ordered_items]
        if not changed and not reordered:
            return {"item": _item_after_reload(item), "preparation_revision": preparation.revision}
        now = timezone.now()
        old_status = item.status
        new_status = changed.get("status", item.status)
        content_changed = any(
            field in changed for field in ("title", "notes", "section", "is_required")
        )
        if (
            old_status in {PreparationItem.Status.COMPLETED, PreparationItem.Status.NOT_APPLICABLE}
            and content_changed
        ):
            changed["status"] = PreparationItem.Status.PENDING
            changed["status_note"] = ""
            new_status = PreparationItem.Status.PENDING
        if new_status in {PreparationItem.Status.COMPLETED, PreparationItem.Status.NOT_APPLICABLE}:
            if new_status != old_status or content_changed:
                changed["resolved_at"] = now
                changed["resolved_by_membership_id"] = authorization.membership_id
        else:
            changed["resolved_at"] = None
            changed["resolved_by_membership_id"] = None
        effective_required = bool(changed.get("is_required", item.is_required))
        invalidates_ready = preparation.status == EventPreparation.Status.READY and (
            (
                content_changed
                and old_status
                in {
                    PreparationItem.Status.COMPLETED,
                    PreparationItem.Status.NOT_APPLICABLE,
                }
            )
            or new_status == PreparationItem.Status.BLOCKED
            or (
                effective_required
                and new_status
                not in {
                    PreparationItem.Status.COMPLETED,
                    PreparationItem.Status.NOT_APPLICABLE,
                }
            )
        )
        if invalidates_ready:
            _increment_preparation(preparation, fields=[])
            _reopen(preparation, authorization.membership_id, now)
        if reordered:
            old_positions = {
                ordered_item.pk: ordered_item.position for ordered_item in ordered_items
            }
            offset = len(ordered_items) + 1
            PreparationItem.objects.filter(preparation=preparation).update(
                position=F("position") + offset
            )
            for final_position, ordered_id in enumerate(reordered_ids, start=1):
                update_values: dict[str, Any] = {"position": final_position}
                if ordered_id != item.pk and old_positions[ordered_id] != final_position:
                    update_values.update(revision=F("revision") + 1, updated_at=now)
                PreparationItem.objects.filter(pk=ordered_id).update(**update_values)
            item.position = reordered_ids.index(item.pk) + 1
        for field, value in changed.items():
            setattr(item, field, value)
        item.revision = F("revision") + 1
        update_fields = [*changed, "revision", "updated_at"]
        if reordered:
            update_fields.append("position")
        item.save(update_fields=update_fields)
        if not invalidates_ready:
            _increment_preparation(preparation, fields=[])
        return {
            "item": _item_after_reload(item),
            "preparation_revision": preparation.revision,
            "preparation": {"status": preparation.status, "revision": preparation.revision},
        }


def mark_ready(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    revision: int,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_MANAGE
    ) as authorization:
        preparation = _get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status == EventPreparation.Status.READY:
            return preparation_representation(preparation, now=timezone.now(), include_items=True)
        if preparation.status != EventPreparation.Status.PREPARING:
            raise conflict("invalid_transition", "La preparación no puede declararse lista.")
        _check_revision(preparation, revision)
        if preparation.reservation.status != Reservation.Status.CONFIRMED:
            raise conflict("reservation_cancelled", "La reserva ya no está confirmada.")
        if preparation.responsible_membership_id is None:
            raise conflict("responsible_required", "Asigna un responsable principal.")
        _eligible_membership(authorization.organization_id, preparation.responsible_membership_id)
        items = list(PreparationItem.objects.select_for_update().filter(preparation=preparation))
        baseline_keys = {item.baseline_key for item in items if item.baseline_key}
        if baseline_keys != BASELINE_KEYS:
            raise conflict("baseline_incomplete", "El checklist base está incompleto.")
        if any(item.status == PreparationItem.Status.BLOCKED for item in items):
            raise conflict("blocked_items", "Existen ítems bloqueados.")
        resolved = {PreparationItem.Status.COMPLETED, PreparationItem.Status.NOT_APPLICABLE}
        if any(item.is_required and item.status not in resolved for item in items):
            raise conflict("required_items_pending", "Existen requisitos obligatorios pendientes.")
        final = next(item for item in items if item.baseline_key == "final_readiness_review")
        if final.status != PreparationItem.Status.COMPLETED:
            raise conflict("required_items_pending", "La revisión final debe completarse.")
        now = timezone.now()
        preparation.status = EventPreparation.Status.READY
        preparation.ready_at = now
        preparation.ready_by_membership_id = authorization.membership_id
        _increment_preparation(preparation, fields=["status", "ready_at", "ready_by_membership"])
        _transition(
            preparation,
            from_status=EventPreparation.Status.PREPARING,
            to_status=EventPreparation.Status.READY,
            cause=PreparationTransition.Cause.READINESS_DECLARED,
            actor_membership_id=authorization.membership_id,
            occurred_at=now,
        )
        return preparation_representation(
            _get_preparation(authorization.organization_id, reservation_id),
            now=now,
            include_items=True,
        )


def _execute_transition(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    revision: int,
    from_status: str,
    to_status: str,
    cause: str,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_EXECUTE
    ) as authorization:
        preparation = _get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status == to_status:
            return preparation_representation(preparation, now=timezone.now(), include_items=True)
        if preparation.status != from_status:
            raise conflict("invalid_transition", "La transición operativa no está permitida.")
        _check_revision(preparation, revision)
        if preparation.reservation.status != Reservation.Status.CONFIRMED:
            raise conflict("reservation_cancelled", "La reserva ya no está confirmada.")
        now = timezone.now()
        preparation.status = to_status
        fields = ["status"]
        if to_status == EventPreparation.Status.IN_PROGRESS:
            preparation.started_at = now
            preparation.started_by_membership_id = authorization.membership_id
            fields += ["started_at", "started_by_membership"]
        else:
            preparation.completed_at = now
            preparation.completed_by_membership_id = authorization.membership_id
            fields += ["completed_at", "completed_by_membership"]
        _increment_preparation(preparation, fields=fields)
        _transition(
            preparation,
            from_status=from_status,
            to_status=to_status,
            cause=cause,
            actor_membership_id=authorization.membership_id,
            occurred_at=now,
        )
        return preparation_representation(
            _get_preparation(authorization.organization_id, reservation_id),
            now=now,
            include_items=True,
        )


def start_event(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    revision: int,
) -> dict[str, Any]:
    return _execute_transition(
        actor,
        organization_reference,
        reservation_id=reservation_id,
        revision=revision,
        from_status=EventPreparation.Status.READY,
        to_status=EventPreparation.Status.IN_PROGRESS,
        cause=PreparationTransition.Cause.EXECUTION_STARTED,
    )


def complete_event(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    revision: int,
) -> dict[str, Any]:
    return _execute_transition(
        actor,
        organization_reference,
        reservation_id=reservation_id,
        revision=revision,
        from_status=EventPreparation.Status.IN_PROGRESS,
        to_status=EventPreparation.Status.COMPLETED,
        cause=PreparationTransition.Cause.EXECUTION_COMPLETED,
    )
