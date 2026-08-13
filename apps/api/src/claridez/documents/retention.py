from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from claridez.organizations.tenant_scope import TenantAuthorization

from .errors import conflict
from .models import (
    ContractualRecord,
    ExternalFile,
    GeneratedArtifact,
    IssuedInstrumentVersion,
    LegalHold,
    RetentionAssignment,
    RetentionEvent,
    RetentionPolicy,
)


def _target_exists(organization_id: UUID, target_type: str, target_id: UUID) -> bool:
    filters = {"organization_id": organization_id, "pk": target_id}
    if target_type == "contractual_record":
        return ContractualRecord.objects.filter(**filters).exists()
    if target_type == "issued_version":
        return IssuedInstrumentVersion.objects.filter(**filters).exists()
    if target_type == "generated_artifact":
        return GeneratedArtifact.objects.filter(**filters).exists()
    if target_type == "external_file":
        return ExternalFile.objects.filter(**filters).exists()
    return False


@transaction.atomic
def create_policy(
    authorization: TenantAuthorization,
    *,
    key: str,
    version: int,
    name: str,
    classification: str,
    rules: dict[str, Any],
) -> RetentionPolicy:
    return RetentionPolicy.objects.create(
        organization_id=authorization.organization_id,
        key=key,
        version=version,
        name=name,
        classification=classification,
        rules=rules,
    )


@transaction.atomic
def activate_policy(authorization: TenantAuthorization, *, policy_id: UUID) -> RetentionPolicy:
    policy = RetentionPolicy.objects.select_for_update().get(
        organization_id=authorization.organization_id, pk=policy_id
    )
    if policy.status != RetentionPolicy.Status.DRAFT:
        raise conflict("retention_policy_state", "Solo una política borrador puede activarse.")
    if not isinstance(policy.rules, dict) or not policy.rules.get("basis"):
        raise conflict(
            "retention_policy_incomplete",
            "La política debe referenciar expresamente su fundamento aprobado.",
        )
    policy.status = RetentionPolicy.Status.ACTIVE
    policy.approved_at = timezone.now()
    policy.approved_by_membership_id = authorization.membership_id
    policy.save(update_fields=["status", "approved_at", "approved_by_membership"])
    return policy


@transaction.atomic
def assign_policy(
    authorization: TenantAuthorization,
    *,
    policy_id: UUID,
    target_type: str,
    target_id: UUID,
) -> RetentionAssignment:
    policy = RetentionPolicy.objects.get(
        organization_id=authorization.organization_id, pk=policy_id
    )
    if policy.status != RetentionPolicy.Status.ACTIVE:
        raise conflict("retention_policy_not_active", "La política de retención no está activa.")
    if not _target_exists(authorization.organization_id, target_type, target_id):
        raise conflict("retention_target_invalid", "El objetivo de retención no existe.")
    assignment = RetentionAssignment.objects.create(
        organization_id=authorization.organization_id,
        policy=policy,
        target_type=target_type,
        target_id=target_id,
    )
    RetentionEvent.objects.create(
        organization_id=authorization.organization_id,
        assignment=assignment,
        kind="policy_assigned",
        actor_membership_id=authorization.membership_id,
        evidence={"policy_id": str(policy.pk), "policy_version": policy.version},
        occurred_at=timezone.now(),
    )
    return assignment


@transaction.atomic
def evaluate_eligibility(
    authorization: TenantAuthorization,
    *,
    assignment_id: UUID,
    eligible_at: datetime,
    rationale: str,
) -> RetentionAssignment:
    assignment = RetentionAssignment.objects.select_for_update().get(
        organization_id=authorization.organization_id, pk=assignment_id
    )
    if LegalHold.objects.filter(assignment=assignment, released_at__isnull=True).exists():
        raise conflict(
            "retention_legal_hold",
            "La elegibilidad no puede cambiar mientras exista un legal hold activo.",
        )
    now = timezone.now()
    assignment.eligible_at = eligible_at
    assignment.evaluated_at = now
    assignment.state = (
        RetentionAssignment.State.ELIGIBLE
        if eligible_at <= now
        else RetentionAssignment.State.RETAIN
    )
    assignment.save(update_fields=["eligible_at", "evaluated_at", "state"])
    RetentionEvent.objects.create(
        organization_id=authorization.organization_id,
        assignment=assignment,
        kind="eligibility_evaluated",
        actor_membership_id=authorization.membership_id,
        evidence={
            "eligible_at": eligible_at.isoformat(),
            "result": assignment.state,
            "rationale": " ".join(rationale.split()),
            "physical_disposition": "not_implemented",
        },
        occurred_at=now,
    )
    return assignment


@transaction.atomic
def place_hold(
    authorization: TenantAuthorization, *, assignment_id: UUID, reason: str
) -> LegalHold:
    assignment = RetentionAssignment.objects.select_for_update().get(
        organization_id=authorization.organization_id, pk=assignment_id
    )
    if LegalHold.objects.filter(assignment=assignment, released_at__isnull=True).exists():
        raise conflict("legal_hold_exists", "Ya existe un legal hold activo.")
    now = timezone.now()
    hold = LegalHold.objects.create(
        organization_id=authorization.organization_id,
        assignment=assignment,
        reason=" ".join(reason.split()),
        placed_at=now,
        placed_by_membership_id=authorization.membership_id,
    )
    assignment.state = RetentionAssignment.State.HELD
    assignment.evaluated_at = now
    assignment.save(update_fields=["state", "evaluated_at"])
    RetentionEvent.objects.create(
        organization_id=authorization.organization_id,
        assignment=assignment,
        kind="legal_hold_placed",
        actor_membership_id=authorization.membership_id,
        evidence={"hold_id": str(hold.pk), "reason": hold.reason},
        occurred_at=now,
    )
    return hold


@transaction.atomic
def release_hold(authorization: TenantAuthorization, *, hold_id: UUID, reason: str) -> LegalHold:
    hold = (
        LegalHold.objects.select_for_update()
        .select_related("assignment")
        .get(organization_id=authorization.organization_id, pk=hold_id)
    )
    if hold.released_at is not None:
        raise conflict("legal_hold_released", "El legal hold ya fue liberado.")
    now = timezone.now()
    hold.released_at = now
    hold.released_by_membership_id = authorization.membership_id
    hold.release_reason = " ".join(reason.split())
    hold.save(update_fields=["released_at", "released_by_membership", "release_reason"])
    assignment = hold.assignment
    assignment.state = (
        RetentionAssignment.State.ELIGIBLE
        if assignment.eligible_at is not None and assignment.eligible_at <= now
        else RetentionAssignment.State.RETAIN
    )
    assignment.evaluated_at = now
    assignment.save(update_fields=["state", "evaluated_at"])
    RetentionEvent.objects.create(
        organization_id=authorization.organization_id,
        assignment=assignment,
        kind="legal_hold_released",
        actor_membership_id=authorization.membership_id,
        evidence={"hold_id": str(hold.pk), "reason": hold.release_reason},
        occurred_at=now,
    )
    return hold
