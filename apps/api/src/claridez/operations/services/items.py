from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import F
from django.utils import timezone

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope

from ..errors import conflict, invalid, unavailable
from ..models import EventPreparation, PreparationItem, PreparationTransition
from ..normalization import canonical_optional_text, canonical_text
from .shared import (
    EDITABLE_PREPARATION_STATES,
    UNSET,
    append_transition,
    eligible_membership,
    get_preparation,
    increment_preparation,
    item_after_reload,
    uuid_or_unavailable,
)


def canonical_item_values(
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
        preparation = get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status not in EDITABLE_PREPARATION_STATES:
            raise conflict("invalid_transition", "El checklist ya no puede editarse.")
        canonical = canonical_item_values(values)
        if (
            "responsible_membership_id" in values
            and values["responsible_membership_id"] is not None
        ):
            canonical["responsible_membership_id"] = eligible_membership(
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
                "item": item_after_reload(existing),
                "preparation_revision": preparation.revision,
            }, False
        ordered_items = list(
            PreparationItem.objects.select_for_update()
            .filter(preparation=preparation)
            .order_by("position", "id")
        )
        position = len(ordered_items) + 1
        if place_before_item_id is not None:
            before_id = uuid_or_unavailable(place_before_item_id)
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
            increment_preparation(preparation, fields=[])
            reopen(preparation, authorization.membership_id, timezone.now())
        item = PreparationItem.objects.create(
            organization_id=authorization.organization_id,
            preparation=preparation,
            client_request_id=client_request_id,
            source_kind=PreparationItem.SourceKind.MANUAL,
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
            increment_preparation(preparation, fields=[])
        return {
            "item": item_after_reload(item),
            "preparation_revision": preparation.revision,
            "preparation": {"status": preparation.status, "revision": preparation.revision},
        }, True


def reopen(preparation: EventPreparation, actor_membership_id: UUID, occurred_at: datetime) -> None:
    """Reabrir sin incrementar: el comando de ítem ya consumió el único incremento agregado."""
    if preparation.status != EventPreparation.Status.READY:
        return
    preparation.status = EventPreparation.Status.PREPARING
    preparation.ready_at = None
    preparation.ready_by_membership_id = None
    preparation.save(update_fields=["status", "ready_at", "ready_by_membership", "updated_at"])
    append_transition(
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
    place_before_item_id: UUID | None | object = UNSET,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_MANAGE
    ) as authorization:
        preparation = get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status not in EDITABLE_PREPARATION_STATES:
            raise conflict("invalid_transition", "El checklist ya no puede editarse.")
        try:
            item = PreparationItem.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                preparation=preparation,
                pk=uuid_or_unavailable(item_id),
            )
        except PreparationItem.DoesNotExist:
            raise unavailable("El ítem") from None
        if item.revision != revision:
            raise conflict("stale_revision", "El ítem cambió. Vuelve a cargarlo.")
        canonical = canonical_item_values(values, current=item)
        if item.source_kind == PreparationItem.SourceKind.P13_TEMPLATE_READINESS and (
            set(canonical) & {"title", "section", "is_required", "due_on"}
            or place_before_item_id is not UNSET
        ):
            raise conflict(
                "authorized_change_required",
                "La definición de plantilla requiere un cambio operativo autorizado.",
            )
        if "responsible_membership_id" in values:
            canonical["responsible_membership_id"] = (
                eligible_membership(
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
        if place_before_item_id is not UNSET:
            reordered_ids.remove(item.pk)
            if place_before_item_id is None:
                reordered_ids.append(item.pk)
            else:
                if not isinstance(place_before_item_id, (UUID, str)):
                    raise unavailable("El ítem de referencia")
                before_id = uuid_or_unavailable(place_before_item_id)
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
            return {"item": item_after_reload(item), "preparation_revision": preparation.revision}
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
                in {PreparationItem.Status.COMPLETED, PreparationItem.Status.NOT_APPLICABLE}
            )
            or new_status == PreparationItem.Status.BLOCKED
            or (
                effective_required
                and new_status
                not in {PreparationItem.Status.COMPLETED, PreparationItem.Status.NOT_APPLICABLE}
            )
        )
        if invalidates_ready:
            increment_preparation(preparation, fields=[])
            reopen(preparation, authorization.membership_id, now)
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
            increment_preparation(preparation, fields=[])
        return {
            "item": item_after_reload(item),
            "preparation_revision": preparation.revision,
            "preparation": {"status": preparation.status, "revision": preparation.revision},
        }
