from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from claridez.commercial.services.operations_projection import operational_event_projection
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.models import Membership

from .models import EventPreparation, PreparationItem

ACTIVE_PHONE_STATES = {
    EventPreparation.Status.PREPARING,
    EventPreparation.Status.READY,
    EventPreparation.Status.IN_PROGRESS,
}
TERMINAL_STATES = {EventPreparation.Status.COMPLETED, EventPreparation.Status.CANCELLED}


def membership_summary(
    membership: Membership | None, *, require_manage: bool = True
) -> dict[str, Any] | None:
    if membership is None:
        return None
    available = membership.status == Membership.Status.ACTIVE
    if require_manage:
        available = available and Capability.OPERATION_MANAGE in capabilities_for_role(
            membership.role
        )
    return {
        "membership_id": membership.pk,
        "display_name": membership.user.display_name or "Miembro del equipo",
        "role": membership.role,
        "available": available,
    }


def item_representation(item: PreparationItem) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": item.pk,
        "client_request_id": item.client_request_id,
        "baseline_key": item.baseline_key,
        "section": item.section,
        "position": item.position,
        "title": item.title,
        "is_required": item.is_required,
        "responsible": membership_summary(item.responsible_membership),
        "due_on": item.due_on,
        "status": item.status,
        "notes": item.notes,
        "status_note": item.status_note,
        "revision": item.revision,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }
    if item.status in {PreparationItem.Status.COMPLETED, PreparationItem.Status.NOT_APPLICABLE}:
        result["resolved_at"] = item.resolved_at
        result["resolved_by"] = membership_summary(item.resolved_by_membership)
    return result


def attention_summary(preparation: EventPreparation, *, now: datetime) -> dict[str, Any]:
    timezone_name = preparation.reservation.event_timezone
    local_now = now.astimezone(ZoneInfo(timezone_name))
    today = local_now.date()
    items = list(preparation.items.all())
    pending = sum(
        item.status in {PreparationItem.Status.PENDING, PreparationItem.Status.IN_PROGRESS}
        for item in items
    )
    overdue = sum(
        item.due_on is not None
        and item.due_on < today
        and item.status
        not in {PreparationItem.Status.COMPLETED, PreparationItem.Status.NOT_APPLICABLE}
        for item in items
    )
    blocked = sum(item.status == PreparationItem.Status.BLOCKED for item in items)
    required_overdue = any(
        item.is_required
        and item.due_on is not None
        and item.due_on < today
        and item.status
        not in {PreparationItem.Status.COMPLETED, PreparationItem.Status.NOT_APPLICABLE}
        for item in items
    )
    starts_at = preparation.reservation.quotation_version.event_starts_at_snapshot
    upcoming = local_now < starts_at.astimezone(ZoneInfo(timezone_name)) and (
        starts_at.astimezone(ZoneInfo(timezone_name)).date() - today
    ).days in range(0, 8)
    responsible = preparation.responsible_membership
    responsible_unavailable = responsible is not None and not bool(
        membership_summary(responsible)["available"]  # type: ignore[index]
    )
    return {
        "pending_count": pending,
        "overdue_count": overdue,
        "blocked_count": blocked,
        "is_overdue": preparation.status == EventPreparation.Status.PREPARING
        and (required_overdue or now >= starts_at),
        "is_upcoming": upcoming,
        "is_ready": preparation.status == EventPreparation.Status.READY,
        "has_blockers": blocked > 0,
        "responsible_unavailable": responsible_unavailable,
    }


def preparation_representation(
    preparation: EventPreparation, *, now: datetime, include_items: bool
) -> dict[str, Any]:
    projection = operational_event_projection(
        preparation.reservation,
        include_phone=preparation.status in ACTIVE_PHONE_STATES and include_items,
    )
    payload: dict[str, Any] = {
        "reservation_id": preparation.reservation_id,
        "event": projection["event"],
        "contact": projection["contact"],
        "preparation": {
            "status": preparation.status,
            "revision": preparation.revision,
            "responsible": membership_summary(preparation.responsible_membership),
            "operational_notes": preparation.operational_notes if include_items else "",
            "baseline_version": preparation.baseline_version,
            "ready_at": preparation.ready_at,
            "ready_by": membership_summary(preparation.ready_by_membership),
            "started_at": preparation.started_at,
            "started_by": membership_summary(preparation.started_by_membership),
            "completed_at": preparation.completed_at,
            "completed_by": membership_summary(preparation.completed_by_membership),
            "created_at": preparation.created_at,
            "updated_at": preparation.updated_at,
            "attention": attention_summary(preparation, now=now),
        },
    }
    if include_items:
        payload["preparation"]["items"] = [
            item_representation(item) for item in preparation.items.all()
        ]
    return payload
