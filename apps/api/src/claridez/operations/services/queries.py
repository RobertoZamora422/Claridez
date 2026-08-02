from __future__ import annotations

import base64
import binascii
import json
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import BooleanField, Case, Count, Exists, OuterRef, Q, Value, When
from django.utils import timezone

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.models import Membership, OrganizationSettings
from claridez.organizations.tenant_scope import authorized_tenant_scope

from ..errors import invalid
from ..models import EventPreparation, PreparationItem
from ..representations import preparation_representation
from .shared import ELIGIBLE_ROLES, OPERATION_CAPABILITIES, get_preparation, preparation_rows


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
        preparation = get_preparation(authorization.organization_id, reservation_id)
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
    cursor: str | None = None,
    page_size: int = 25,
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_reference, Capability.OPERATION_READ
    ) as authorization:
        now = timezone.now()
        rows = preparation_rows(include_items=False).filter(
            organization_id=authorization.organization_id
        )
        organization_timezone = ZoneInfo(
            OrganizationSettings.objects.only("timezone")
            .get(organization_id=authorization.organization_id)
            .timezone
        )
        today = now.astimezone(organization_timezone).date()
        unresolved_statuses = [
            PreparationItem.Status.PENDING,
            PreparationItem.Status.IN_PROGRESS,
            PreparationItem.Status.BLOCKED,
        ]
        required_overdue = PreparationItem.objects.filter(
            organization_id=authorization.organization_id,
            preparation_id=OuterRef("pk"),
            is_required=True,
            due_on__lt=today,
            status__in=unresolved_statuses,
        )
        starts_at_field = "reservation__quotation_version__event_starts_at_snapshot"
        upcoming_limit = datetime.combine(
            today + timedelta(days=8), time.min, tzinfo=organization_timezone
        )
        rows = rows.annotate(
            attention_pending_count=Count(
                "items",
                filter=Q(
                    items__status__in=[
                        PreparationItem.Status.PENDING,
                        PreparationItem.Status.IN_PROGRESS,
                    ]
                ),
            ),
            attention_overdue_count=Count(
                "items",
                filter=Q(items__due_on__lt=today, items__status__in=unresolved_statuses),
            ),
            attention_blocked_count=Count(
                "items", filter=Q(items__status=PreparationItem.Status.BLOCKED)
            ),
            attention_required_overdue=Exists(required_overdue),
            attention_responsible_unavailable=Case(
                When(responsible_membership_id__isnull=True, then=Value(False)),
                When(
                    responsible_membership__status=Membership.Status.ACTIVE,
                    responsible_membership__role__in=ELIGIBLE_ROLES,
                    then=Value(False),
                ),
                default=Value(True),
                output_field=BooleanField(),
            ),
        ).annotate(
            attention_is_overdue=Case(
                When(
                    Q(status=EventPreparation.Status.PREPARING)
                    & (Q(attention_required_overdue=True) | Q(**{f"{starts_at_field}__lte": now})),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            ),
            attention_is_upcoming=Case(
                When(
                    **{
                        f"{starts_at_field}__gt": now,
                        f"{starts_at_field}__lt": upcoming_limit,
                    },
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            ),
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
            rows = rows.filter(
                reservation__quotation_version__event_starts_at_snapshot__lt=datetime.combine(
                    today + timedelta(days=31), time.min, tzinfo=organization_timezone
                )
            )
        if attention == "overdue":
            rows = rows.filter(attention_is_overdue=True)
        elif attention == "upcoming":
            rows = rows.filter(attention_is_upcoming=True)
        elif attention == "blocked":
            rows = rows.filter(attention_blocked_count__gt=0)
        elif attention == "ready":
            rows = rows.filter(status=EventPreparation.Status.READY)
        elif attention == "unassigned":
            rows = rows.filter(responsible_membership_id__isnull=True)
        if cursor:
            cursor_starts_at, cursor_reservation_id = decode_event_cursor(cursor)
            rows = rows.filter(
                Q(**{f"{starts_at_field}__gt": cursor_starts_at})
                | Q(
                    **{
                        starts_at_field: cursor_starts_at,
                        "reservation_id__gt": cursor_reservation_id,
                    }
                )
            )
        rows = rows.order_by(starts_at_field, "reservation_id")
        page_rows = list(rows[: page_size + 1])
        has_next = len(page_rows) > page_size
        page_rows = page_rows[:page_size]
        page = [preparation_representation(row, now=now, include_items=False) for row in page_rows]
        next_cursor = None
        if has_next and page_rows:
            last = page_rows[-1]
            next_cursor = encode_event_cursor(
                last.reservation.quotation_version.event_starts_at_snapshot,
                last.reservation_id,
            )
        return {"results": page, "next_cursor": next_cursor}


def encode_event_cursor(starts_at: datetime, reservation_id: UUID) -> str:
    raw = json.dumps(
        {"starts_at": starts_at.isoformat(), "reservation_id": str(reservation_id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_event_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        starts_at = datetime.fromisoformat(payload["starts_at"])
        reservation_id = UUID(payload["reservation_id"])
        if starts_at.tzinfo is None:
            raise ValueError
    except (binascii.Error, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise invalid("El cursor no es válido.") from None
    return starts_at, reservation_id
