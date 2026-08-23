"""Coordinación neutral de reprogramación Scheduling/Operations/Resources."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope


def reschedule_with_resources(
    actor: User,
    organization_reference: UUID | str,
    *,
    reservation_id: UUID | str,
    revision: int,
    idempotency_key: UUID,
    space_id: UUID,
    starts_at_local: datetime,
    ends_at_local: datetime,
    timezone_name: str,
    reason: str,
    commercial_terms_unchanged: bool,
    carry_free_item_ids: tuple[UUID, ...] = (),
    carry_resource_assignment_ids: tuple[UUID, ...] = (),
) -> dict[str, Any]:
    import claridez.resources.public as resources_port
    import claridez.scheduling.public as scheduling_port

    expired_error: scheduling_port.SchedulingError | None = None
    result: dict[str, Any] | None = None
    with transaction.atomic():
        try:
            result = scheduling_port.reschedule_command(
                actor,
                organization_reference,
                reservation_id=reservation_id,
                revision=revision,
                idempotency_key=idempotency_key,
                space_id=space_id,
                starts_at_local=starts_at_local,
                ends_at_local=ends_at_local,
                timezone_name=timezone_name,
                reason=reason,
                commercial_terms_unchanged=commercial_terms_unchanged,
                carry_free_item_ids=carry_free_item_ids,
                carry_resource_assignment_ids=carry_resource_assignment_ids,
            )
        except scheduling_port.SchedulingError as error:
            if error.code != "hold_expired":
                raise
            # Scheduling deliberately persists expiry before returning its
            # conflict. Catch inside the outer coordinator so that expiry and
            # the PostgreSQL resource release commit together, then surface
            # the same domain error after the transaction commits.
            expired_error = error
        if result is not None and carry_resource_assignment_ids:
            with authorized_tenant_scope(
                actor, organization_reference, Capability.RESOURCE_RESERVE
            ) as authorization:
                successor_id = UUID(str(result["reservation"]["id"]))
                carried = resources_port.transfer_assignments_authorized(
                    authorization,
                    previous_reservation_id=UUID(str(reservation_id)),
                    successor_reservation_id=successor_id,
                    assignment_ids=carry_resource_assignment_ids,
                )
            result["carried_resource_assignment_ids"] = carried
        elif result is not None:
            result["carried_resource_assignment_ids"] = ()
    if expired_error is not None:
        raise expired_error
    if result is None:
        raise scheduling_port.SchedulingError(
            "schedule_integrity_conflict",
            "La reprogramación no produjo un resultado.",
            status=409,
        )
    return result


__all__ = ("reschedule_with_resources",)
