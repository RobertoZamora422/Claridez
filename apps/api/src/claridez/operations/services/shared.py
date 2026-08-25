from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import F, Prefetch
from django.db.models.query import QuerySet

from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.models import Membership

from ..errors import conflict, unavailable
from ..models import EventPreparation, PreparationItem, PreparationTransition
from ..representations import item_representation

OPERATION_CAPABILITIES = frozenset(
    {
        Capability.OPERATION_READ,
        Capability.OPERATION_MANAGE,
        Capability.OPERATION_EXECUTE,
        Capability.OPERATION_TEMPLATE_READ,
        Capability.OPERATION_TEMPLATE_MANAGE,
        Capability.OPERATION_INCIDENT_READ,
        Capability.OPERATION_INCIDENT_MANAGE,
        Capability.OPERATION_CHANGE_AUTHORIZE,
        Capability.OPERATION_EVIDENCE_READ,
        Capability.OPERATION_EVIDENCE_MANAGE,
        Capability.OPERATION_CLOSE,
    }
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
UNSET = object()


def uuid_or_unavailable(value: UUID | str, resource: str = "El recurso") -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise unavailable(resource) from None


def preparation_rows(
    *, lock: bool = False, include_items: bool = True
) -> QuerySet[EventPreparation]:
    rows = EventPreparation.objects.select_related(
        "reservation__quotation_version",
        "reservation__event_request__person",
        "responsible_membership__user",
        "ready_by_membership__user",
        "started_by_membership__user",
        "completed_by_membership__user",
    )
    if include_items:
        rows = rows.prefetch_related(
            Prefetch(
                "items",
                queryset=PreparationItem.objects.select_related(
                    "responsible_membership__user", "resolved_by_membership__user"
                ).order_by("position", "id"),
            )
        )
    return rows.select_for_update(of=("self",)) if lock else rows


def get_preparation(
    organization_id: UUID, reservation_id: UUID | str, *, lock: bool = False
) -> EventPreparation:
    try:
        return preparation_rows(lock=lock).get(
            organization_id=organization_id,
            reservation_id=uuid_or_unavailable(reservation_id, "La preparación"),
        )
    except EventPreparation.DoesNotExist:
        raise unavailable("La preparación") from None


def eligible_membership(organization_id: UUID, membership_id: UUID | str) -> Membership:
    try:
        membership = Membership.objects.select_related("user").get(
            organization_id=organization_id,
            pk=uuid_or_unavailable(membership_id, "La membresía"),
            status=Membership.Status.ACTIVE,
            role__in=ELIGIBLE_ROLES,
        )
    except Membership.DoesNotExist:
        raise unavailable("La membresía") from None
    if Capability.OPERATION_MANAGE not in capabilities_for_role(membership.role):
        raise unavailable("La membresía")
    return membership


def check_revision(preparation: EventPreparation, revision: int) -> None:
    if preparation.revision != revision:
        raise conflict("stale_revision", "La preparación cambió. Vuelve a cargarla.")


def increment_preparation(preparation: EventPreparation, *, fields: list[str]) -> None:
    preparation.revision = F("revision") + 1
    preparation.save(update_fields=[*fields, "revision", "updated_at"])
    preparation.refresh_from_db()


def append_transition(
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


def item_after_reload(item: PreparationItem) -> dict[str, Any]:
    return item_representation(
        PreparationItem.objects.select_related(
            "responsible_membership__user", "resolved_by_membership__user"
        ).get(pk=item.pk)
    )
