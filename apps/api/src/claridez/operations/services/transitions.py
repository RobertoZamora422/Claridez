from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils import timezone

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope

from ..baseline import BASELINE_KEYS
from ..errors import conflict
from ..models import EventPreparation, PreparationItem, PreparationTransition
from ..representations import preparation_representation
from .shared import (
    append_transition,
    check_revision,
    eligible_membership,
    get_preparation,
    increment_preparation,
)


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
        preparation = get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status == EventPreparation.Status.READY:
            return preparation_representation(preparation, now=timezone.now(), include_items=True)
        if preparation.status != EventPreparation.Status.PREPARING:
            raise conflict("invalid_transition", "La preparación no puede declararse lista.")
        check_revision(preparation, revision)
        if preparation.reservation.status != "confirmed":
            raise conflict("reservation_cancelled", "La reserva ya no está confirmada.")
        if preparation.responsible_membership_id is None:
            raise conflict("responsible_required", "Asigna un responsable principal.")
        eligible_membership(authorization.organization_id, preparation.responsible_membership_id)
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
        increment_preparation(preparation, fields=["status", "ready_at", "ready_by_membership"])
        append_transition(
            preparation,
            from_status=EventPreparation.Status.PREPARING,
            to_status=EventPreparation.Status.READY,
            cause=PreparationTransition.Cause.READINESS_DECLARED,
            actor_membership_id=authorization.membership_id,
            occurred_at=now,
        )
        return preparation_representation(
            get_preparation(authorization.organization_id, reservation_id),
            now=now,
            include_items=True,
        )


def execute_transition(
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
        preparation = get_preparation(authorization.organization_id, reservation_id, lock=True)
        if preparation.status == to_status:
            return preparation_representation(preparation, now=timezone.now(), include_items=True)
        if preparation.status != from_status:
            raise conflict("invalid_transition", "La transición operativa no está permitida.")
        check_revision(preparation, revision)
        if preparation.reservation.status != "confirmed":
            raise conflict("reservation_cancelled", "La reserva ya no está confirmada.")
        from ..advanced import phase_fact_gate, verification_gate

        phase = "setup" if to_status == EventPreparation.Status.IN_PROGRESS else "execution"
        verification_gate(preparation, phase)
        if phase == "setup":
            phase_fact_gate(preparation, phase)
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
        increment_preparation(preparation, fields=fields)
        append_transition(
            preparation,
            from_status=from_status,
            to_status=to_status,
            cause=cause,
            actor_membership_id=authorization.membership_id,
            occurred_at=now,
        )
        return preparation_representation(
            get_preparation(authorization.organization_id, reservation_id),
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
    return execute_transition(
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
    return execute_transition(
        actor,
        organization_reference,
        reservation_id=reservation_id,
        revision=revision,
        from_status=EventPreparation.Status.IN_PROGRESS,
        to_status=EventPreparation.Status.COMPLETED,
        cause=PreparationTransition.Cause.EXECUTION_COMPLETED,
    )
