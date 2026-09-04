"""Ledger PostgreSQL tenant-aware P15, at-least-once y publicación write-once."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.public import (
    active_organization_ids_for_analytics_worker,
    analytics_requester_actor_id,
)
from claridez.organizations.tenant_scope import authorized_tenant_scope, infrastructure_tenant_scope

from .exporting import (
    export_dataset,
    presentation_dataset,
    reconstruct_execution,
    renderer_version,
    revalidate_execution_scope,
)
from .models import AnalyticsAuditEvent, ExportArtifact, ExportAttempt, ExportJob
from .query import authorize_selections
from .render_process import render_bounded
from .services import stored_selections
from .storage import AnalyticsStorage, LocalAnalyticsStorage, PublishedObject, StorageIntegrityError

MAX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class JobClaim:
    organization_id: UUID
    job_id: UUID
    execution_id: UUID
    requester_membership_id: UUID
    artifact_identity: UUID
    format: str
    renderer_version: str
    attempt_number: int
    lease_token: UUID
    lease_expires_at: datetime


def _attempt(job: ExportJob, event: str, reason: str = "") -> None:
    if job.lease_token is None:
        raise RuntimeError("attempt_requires_claim_token")
    ExportAttempt.objects.create(
        organization_id=job.organization_id,
        job=job,
        number=job.attempt_count,
        lease_token=job.lease_token,
        event=event,
        reason_code=reason,
    )
    AnalyticsAuditEvent.objects.create(
        organization_id=job.organization_id,
        actor_membership_id=job.requested_by_membership_id,
        event="export_" + event,
        subject_id=job.pk,
        detail={"attempt": job.attempt_count, "reason_code": reason},
    )


def _finish(job: ExportJob, state: str, reason: str = "") -> None:
    now = timezone.now()
    _attempt(job, state, reason)
    job.state, job.last_error_code = state, reason
    job.lease_token, job.lease_expires_at = None, None
    job.completed_at = now if state == ExportJob.State.COMPLETED else None
    if state == ExportJob.State.RETRY:
        job.next_attempt_at = now + timedelta(seconds=min(300, 5 * (2 ** (job.attempt_count - 1))))
    job.save(
        update_fields=[
            "state",
            "last_error_code",
            "lease_token",
            "lease_expires_at",
            "completed_at",
            "next_attempt_at",
            "updated_at",
        ]
    )


def claim_next(organization_id: UUID) -> JobClaim | None:
    """Caller abre scope de infraestructura y lo confirma antes de materializar/renderizar."""
    if not connection.in_atomic_block:
        raise RuntimeError("claim_requires_tenant_transaction")
    now = timezone.now()
    job = (
        ExportJob.objects.select_for_update(skip_locked=True)
        .filter(organization_id=organization_id)
        .filter(
            Q(state__in=[ExportJob.State.QUEUED, ExportJob.State.RETRY], next_attempt_at__lte=now)
            | Q(state=ExportJob.State.RUNNING, lease_expires_at__lte=now)
        )
        .order_by("next_attempt_at", "created_at", "id")
        .first()
    )
    if job is None:
        return None
    if job.state == ExportJob.State.RUNNING:
        _attempt(job, "reclaimed", "lease_expired")
        if job.attempt_count >= MAX_ATTEMPTS:
            _finish(job, ExportJob.State.TERMINAL, "attempt_budget_exhausted")
            return None
    job.attempt_count += 1
    job.state = ExportJob.State.RUNNING
    job.lease_token = uuid4()
    job.lease_expires_at = now + timedelta(seconds=settings.ANALYTICS_EXPORT_LEASE_SECONDS)
    job.save(
        update_fields=["state", "attempt_count", "lease_token", "lease_expires_at", "updated_at"]
    )
    _attempt(job, "claimed")
    return JobClaim(
        organization_id,
        job.pk,
        job.execution_id,
        job.requested_by_membership_id,
        job.artifact_identity,
        job.format,
        job.renderer_version,
        job.attempt_count,
        job.lease_token,
        job.lease_expires_at,
    )


def _current_claim(claim: JobClaim, *, lock: bool = False) -> ExportJob | None:
    rows = ExportJob.objects.select_related("execution")
    if lock:
        rows = rows.select_for_update(of=("self",))
    return rows.filter(
        organization_id=claim.organization_id,
        pk=claim.job_id,
        state=ExportJob.State.RUNNING,
        lease_token=claim.lease_token,
        lease_expires_at__gt=timezone.now(),
    ).first()


def _requester(claim: JobClaim) -> User:
    actor_id = analytics_requester_actor_id(claim.organization_id, claim.requester_membership_id)
    if actor_id is None:
        raise AuthorizationDenied("El solicitante ya no está autorizado.")
    try:
        return User.objects.get(pk=actor_id, is_active=True)
    except User.DoesNotExist:
        raise AuthorizationDenied("El solicitante ya no está autorizado.") from None


def _finalize(claim: JobClaim, metadata: PublishedObject) -> bool:
    with infrastructure_tenant_scope(claim.organization_id, purpose="analytics_worker"):
        job = _current_claim(claim, lock=True)
        if job is None:
            return False
        with authorized_tenant_scope(
            _requester(claim), claim.organization_id, Capability.ANALYTICS_CREATE_EXPORT
        ) as auth:
            if auth.membership_id != claim.requester_membership_id:
                raise AuthorizationDenied("La membresía solicitante cambió.")
            authorize_selections(
                auth, stored_selections(job.execution.selection), Capability.ANALYTICS_CREATE_EXPORT
            )
            revalidate_execution_scope(auth, job.execution)
            existing = ExportArtifact.objects.filter(
                organization_id=claim.organization_id, job_id=claim.job_id
            ).first()
            if existing is not None:
                if (existing.object_key, existing.sha256, existing.byte_size, existing.format) != (
                    metadata.object_key,
                    metadata.sha256,
                    metadata.byte_size,
                    metadata.format,
                ):
                    raise StorageIntegrityError("published_artifact_metadata_mismatch")
            else:
                ExportArtifact.objects.create(
                    id=claim.artifact_identity,
                    organization_id=claim.organization_id,
                    job=job,
                    object_key=metadata.object_key,
                    sha256=metadata.sha256,
                    byte_size=metadata.byte_size,
                    format=metadata.format,
                    renderer_version=claim.renderer_version,
                )
            _finish(job, ExportJob.State.COMPLETED)
            return True


def _record_failure(claim: JobClaim, reason: str, *, terminal: bool) -> None:
    with infrastructure_tenant_scope(claim.organization_id, purpose="analytics_worker"):
        job = _current_claim(claim, lock=True)
        if job is not None:
            state = (
                ExportJob.State.TERMINAL
                if terminal or job.attempt_count >= MAX_ATTEMPTS
                else ExportJob.State.RETRY
            )
            _finish(job, state, reason)


def process_claim(claim: JobClaim, *, storage: AnalyticsStorage | None = None) -> None:
    if connection.in_atomic_block:
        raise RuntimeError("export_io_requires_committed_claim")
    deadline = monotonic() + settings.ANALYTICS_EXPORT_TIMEOUT_SECONDS
    try:
        if claim.renderer_version != renderer_version():
            raise StorageIntegrityError("renderer_version_unavailable")
        with infrastructure_tenant_scope(claim.organization_id, purpose="analytics_worker"):
            job = _current_claim(claim)
            if job is None:
                return
            with authorized_tenant_scope(
                _requester(claim), claim.organization_id, Capability.ANALYTICS_CREATE_EXPORT
            ) as auth:
                if auth.membership_id != claim.requester_membership_id:
                    raise AuthorizationDenied("La membresía solicitante cambió.")
                payload = reconstruct_execution(
                    auth, job.execution, Capability.ANALYTICS_CREATE_EXPORT
                )
                dataset = (presentation_dataset if claim.format == "pdf" else export_dataset)(
                    str(job.execution_id), payload
                )
        # No hay una transacción abierta durante el renderer ni durante I/O de storage.
        content = render_bounded(dataset, claim.format, timeout_seconds=deadline - monotonic())
        with infrastructure_tenant_scope(claim.organization_id, purpose="analytics_worker"):
            job = _current_claim(claim)
            if job is None:
                return
            with authorized_tenant_scope(
                _requester(claim), claim.organization_id, Capability.ANALYTICS_CREATE_EXPORT
            ) as auth:
                authorize_selections(
                    auth,
                    stored_selections(job.execution.selection),
                    Capability.ANALYTICS_CREATE_EXPORT,
                )
                revalidate_execution_scope(auth, job.execution)
        adapter = storage or LocalAnalyticsStorage(Path(settings.ANALYTICS_STORAGE_ROOT))
        if monotonic() >= deadline:
            raise ValueError("export_time_limit")
        metadata = adapter.publish(
            claim.organization_id, claim.artifact_identity, claim.format, content
        )
        _finalize(claim, metadata)
    except AuthorizationDenied:
        _record_failure(claim, "authorization_lost", terminal=True)
    except StorageIntegrityError:
        _record_failure(claim, "artifact_integrity_failure", terminal=True)
    except ValueError:
        _record_failure(claim, "export_contract_or_limit_failure", terminal=True)
    except OSError:
        _record_failure(claim, "storage_temporarily_unavailable", terminal=False)


def work_once(organization_id: UUID, *, storage: AnalyticsStorage | None = None) -> bool:
    if connection.in_atomic_block:
        raise RuntimeError("worker_requires_own_transaction")
    with infrastructure_tenant_scope(organization_id, purpose="analytics_worker"):
        claim = claim_next(organization_id)
    if claim is None:
        return False
    process_claim(claim, storage=storage)
    return True


def work_round() -> int:
    return sum(
        work_once(organization_id)
        for organization_id in active_organization_ids_for_analytics_worker()
    )
