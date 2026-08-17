from __future__ import annotations

import hashlib
import io
import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from claridez.organizations.tenant_scope import infrastructure_tenant_scope

from .config import document_settings
from .errors import DocumentsError
from .external_files import validate_upload
from .malware import ScanResult, malware_scanner
from .models import (
    ArtifactIntegrityEvent,
    DocumentJob,
    DocumentJobAttempt,
    ExternalFile,
    ExternalFileEvent,
    GeneratedArtifact,
    GeneratedDomainArtifact,
    IssuedInstrumentVersion,
    MalwareScanAttempt,
    PrivateDomainFile,
    PrivateDomainFileEvent,
    PrivateDomainScanAttempt,
)
from .rendering import render_pdf
from .storage import bytes_stream, opaque_evidence_key, private_storage

logger = logging.getLogger(__name__)


def enqueue_job(
    *,
    organization_id: uuid.UUID,
    job_type: str,
    target_id: uuid.UUID,
    idempotency_key: str,
    correlation_id: str,
) -> DocumentJob:
    return DocumentJob.objects.get_or_create(
        organization_id=organization_id,
        job_type=job_type,
        idempotency_key=idempotency_key,
        defaults={
            "target_id": target_id,
            "payload": {},
            "correlation_id": correlation_id,
            "next_attempt_at": timezone.now(),
        },
    )[0]


@transaction.atomic
def claim_job(organization_id: uuid.UUID, *, worker_id: str) -> DocumentJob | None:
    now = timezone.now()
    lease = timedelta(seconds=document_settings().job_lease_seconds)
    job = (
        DocumentJob.objects.select_for_update(skip_locked=True)
        .filter(organization_id=organization_id)
        .filter(state__in=[DocumentJob.State.QUEUED, DocumentJob.State.RETRY_WAIT])
        .filter(next_attempt_at__lte=now)
        .order_by("next_attempt_at", "created_at", "id")
        .first()
    )
    if job is None:
        job = (
            DocumentJob.objects.select_for_update(skip_locked=True)
            .filter(
                organization_id=organization_id,
                state=DocumentJob.State.RUNNING,
                lease_expires_at__lt=now,
            )
            .order_by("lease_expires_at", "id")
            .first()
        )
    if job is None:
        return None
    job.state = DocumentJob.State.RUNNING
    job.claimed_by = worker_id
    job.lease_expires_at = now + lease
    job.attempts += 1
    job.save(update_fields=["state", "claimed_by", "lease_expires_at", "attempts", "updated_at"])
    return job


@transaction.atomic
def _render(job: DocumentJob) -> str:
    version = IssuedInstrumentVersion.objects.select_related("template_version").get(
        organization_id=job.organization_id, pk=job.target_id
    )
    if GeneratedArtifact.objects.filter(issued_version=version, is_emitted_original=True).exists():
        return "succeeded"
    version.state = IssuedInstrumentVersion.State.RENDERING
    version.save(update_fields=["state"])
    html = (
        '<header class="document-header"><img src="claridez-asset:wordmark" '
        f'alt="Claridez"><strong>{version.template_version.title}</strong></header>'
        f"{version.resolved_variables['rendered_html']}"
    )
    rendered = render_pdf(html)
    key = opaque_evidence_key("generated", str(version.pk))
    storage = private_storage()
    if storage.exists(key):
        with storage.open(key) as existing:
            content = existing.read()
        if (
            hashlib.sha256(content).hexdigest() != rendered.sha256
            or len(content) != rendered.size_bytes
        ):
            raise DocumentsError("object_collision", "La evidencia existente no coincide.")
    else:
        storage.put(
            key=key,
            stream=bytes_stream(rendered.content),
            size_bytes=rendered.size_bytes,
            sha256=rendered.sha256,
            media_type="application/pdf",
        )
    artifact = GeneratedArtifact.objects.create(
        organization_id=job.organization_id,
        issued_version=version,
        sequence=1,
        is_emitted_original=True,
        storage_key=key,
        sha256=rendered.sha256,
        size_bytes=rendered.size_bytes,
        provenance={"job_id": str(job.pk), "source": "controlled_renderer"},
        renderer_name=rendered.renderer_name,
        renderer_version=rendered.renderer_version,
        render_environment=rendered.environment,
        stored_at=timezone.now(),
    )
    version.state = IssuedInstrumentVersion.State.ISSUED
    version.issued_at = timezone.now()
    version.save(update_fields=["state", "issued_at"])
    enqueue_job(
        organization_id=job.organization_id,
        job_type=DocumentJob.Type.VERIFY_ARTIFACT,
        target_id=artifact.pk,
        idempotency_key=f"verify:{artifact.pk}",
        correlation_id=job.correlation_id,
    )
    return "succeeded"


@transaction.atomic
def _scan(job: DocumentJob) -> str:
    row = ExternalFile.objects.select_for_update().get(
        organization_id=job.organization_id, pk=job.target_id
    )
    if row.state in {
        ExternalFile.State.CLEAN,
        ExternalFile.State.INFECTED,
        ExternalFile.State.REJECTED,
    }:
        return "succeeded"
    if row.state not in {ExternalFile.State.PENDING_SCAN, ExternalFile.State.SCAN_ERROR}:
        raise DocumentsError("invalid_file_state", "El archivo no puede analizarse.")
    started = timezone.now()
    with private_storage().open(row.storage_key) as stream:
        outcome = malware_scanner().scan(stream)
    finished = timezone.now()
    attempt = row.scan_attempts.count() + 1
    MalwareScanAttempt.objects.create(
        organization_id=job.organization_id,
        external_file=row,
        attempt=attempt,
        scanner_name=outcome.scanner_name,
        scanner_version=outcome.scanner_version,
        signatures_version=outcome.signatures_version,
        result=outcome.result,
        malware_name=outcome.malware_name,
        detail=outcome.detail[:500],
        started_at=started,
        finished_at=finished,
    )
    previous = row.state
    if outcome.result == ScanResult.CLEAN:
        row.state = ExternalFile.State.CLEAN
        row.available_at = finished
    elif outcome.result == ScanResult.INFECTED:
        row.state = ExternalFile.State.INFECTED
    elif outcome.result == ScanResult.UNSUPPORTED:
        row.state = ExternalFile.State.REJECTED
    else:
        row.state = ExternalFile.State.SCAN_ERROR
    row.validation_detail = outcome.detail[:500]
    row.save(update_fields=["state", "available_at", "validation_detail", "updated_at"])
    ExternalFileEvent.objects.create(
        organization_id=job.organization_id,
        external_file=row,
        from_state=previous,
        to_state=row.state,
        reason="malware_scan",
        detail=outcome.detail[:500],
        occurred_at=finished,
    )
    if row.state == ExternalFile.State.SCAN_ERROR:
        return "retry"
    return "succeeded"


@transaction.atomic
def _finalize_upload(job: DocumentJob) -> str:
    row = ExternalFile.objects.select_for_update().get(
        organization_id=job.organization_id, pk=job.target_id
    )
    if row.state in {
        ExternalFile.State.PENDING_SCAN,
        ExternalFile.State.CLEAN,
        ExternalFile.State.INFECTED,
        ExternalFile.State.REJECTED,
        ExternalFile.State.SCAN_ERROR,
    }:
        return "succeeded"
    if row.state != ExternalFile.State.UPLOADING:
        raise DocumentsError("invalid_file_state", "El upload no puede finalizarse.")
    try:
        with private_storage().open(row.storage_key) as stream:
            size = 0
            digest = hashlib.sha256()
            content = bytearray()
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > row.size_bytes or size > document_settings().max_upload_bytes:
                    break
                digest.update(chunk)
                content.extend(chunk)
    except DocumentsError:
        return "retry"
    now = timezone.now()
    if size != row.size_bytes or digest.hexdigest() != row.sha256:
        row.state = ExternalFile.State.REJECTED
        row.validation_detail = "upload_integrity_mismatch"
        row.save(update_fields=["state", "validation_detail", "updated_at"])
        ExternalFileEvent.objects.create(
            organization_id=job.organization_id,
            external_file=row,
            from_state=ExternalFile.State.UPLOADING,
            to_state=ExternalFile.State.REJECTED,
            reason="upload_integrity_mismatch",
            occurred_at=now,
        )
        return "dead"
    try:
        validated = validate_upload(
            display_name=row.display_name,
            declared_media_type=row.declared_media_type,
            stream=io.BytesIO(content),
        )
    except DocumentsError as error:
        row.state = ExternalFile.State.REJECTED
        row.validation_detail = error.code
        row.save(update_fields=["state", "validation_detail", "updated_at"])
        ExternalFileEvent.objects.create(
            organization_id=job.organization_id,
            external_file=row,
            from_state=ExternalFile.State.UPLOADING,
            to_state=ExternalFile.State.REJECTED,
            reason="structural_validation_failed",
            detail=error.code,
            occurred_at=now,
        )
        return "dead"
    row.detected_media_type = validated.media_type
    row.state = ExternalFile.State.QUARANTINED
    row.save(update_fields=["detected_media_type", "state", "updated_at"])
    ExternalFileEvent.objects.create(
        organization_id=job.organization_id,
        external_file=row,
        from_state=ExternalFile.State.UPLOADING,
        to_state=ExternalFile.State.QUARANTINED,
        reason="upload_stored",
        occurred_at=now,
    )
    row.state = ExternalFile.State.PENDING_SCAN
    row.save(update_fields=["state", "updated_at"])
    ExternalFileEvent.objects.create(
        organization_id=job.organization_id,
        external_file=row,
        from_state=ExternalFile.State.QUARANTINED,
        to_state=ExternalFile.State.PENDING_SCAN,
        reason="validation_passed",
        occurred_at=now,
    )
    enqueue_job(
        organization_id=job.organization_id,
        job_type=DocumentJob.Type.SCAN_EXTERNAL_FILE,
        target_id=row.pk,
        idempotency_key=f"scan:{row.pk}",
        correlation_id=job.correlation_id,
    )
    return "succeeded"


@transaction.atomic
def _verify(job: DocumentJob) -> str:
    artifact = GeneratedArtifact.objects.select_for_update().get(
        organization_id=job.organization_id, pk=job.target_id
    )
    now = timezone.now()
    try:
        with private_storage().open(artifact.storage_key) as stream:
            digest = hashlib.sha256()
            size = 0
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        observed = digest.hexdigest()
        result = (
            ArtifactIntegrityEvent.Result.VERIFIED
            if observed == artifact.sha256 and size == artifact.size_bytes
            else ArtifactIntegrityEvent.Result.MISMATCH
        )
    except DocumentsError:
        observed, size, result = "", None, ArtifactIntegrityEvent.Result.MISSING
    ArtifactIntegrityEvent.objects.create(
        organization_id=job.organization_id,
        artifact=artifact,
        result=result,
        expected_sha256=artifact.sha256,
        observed_sha256=observed,
        observed_size_bytes=size,
        occurred_at=now,
    )
    if result == ArtifactIntegrityEvent.Result.VERIFIED:
        artifact.verified_at = now
        artifact.save(update_fields=["verified_at"])
    else:
        artifact.state = GeneratedArtifact.State.INTEGRITY_FAILED
        artifact.save(update_fields=["state"])
        return "dead"
    return "succeeded"


@transaction.atomic
def _finalize_domain_upload(job: DocumentJob) -> str:
    row = PrivateDomainFile.objects.select_for_update().get(
        organization_id=job.organization_id, pk=job.target_id
    )
    terminal = {
        PrivateDomainFile.State.PENDING_SCAN,
        PrivateDomainFile.State.CLEAN,
        PrivateDomainFile.State.INFECTED,
        PrivateDomainFile.State.REJECTED,
        PrivateDomainFile.State.SCAN_ERROR,
    }
    if row.state in terminal:
        return "succeeded"
    if row.state != PrivateDomainFile.State.UPLOADING:
        raise DocumentsError("invalid_file_state", "El upload no puede finalizarse.")
    try:
        with private_storage().open(row.storage_key) as stream:
            content = stream.read(document_settings().max_upload_bytes + 1)
    except DocumentsError:
        return "retry"
    now = timezone.now()
    if len(content) != row.size_bytes or hashlib.sha256(content).hexdigest() != row.sha256:
        row.state = PrivateDomainFile.State.REJECTED
        row.validation_detail = "upload_integrity_mismatch"
        row.save(update_fields=["state", "validation_detail", "updated_at"])
        PrivateDomainFileEvent.objects.create(
            organization_id=job.organization_id,
            domain_file=row,
            from_state=PrivateDomainFile.State.UPLOADING,
            to_state=row.state,
            reason="upload_integrity_mismatch",
            occurred_at=now,
        )
        return "dead"
    try:
        validated = validate_upload(
            display_name=row.display_name,
            declared_media_type=row.declared_media_type,
            stream=io.BytesIO(content),
        )
    except DocumentsError as error:
        row.state = PrivateDomainFile.State.REJECTED
        row.validation_detail = error.code
        row.save(update_fields=["state", "validation_detail", "updated_at"])
        PrivateDomainFileEvent.objects.create(
            organization_id=job.organization_id,
            domain_file=row,
            from_state=PrivateDomainFile.State.UPLOADING,
            to_state=row.state,
            reason="structural_validation_failed",
            detail=error.code,
            occurred_at=now,
        )
        return "dead"
    row.detected_media_type = validated.media_type
    row.state = PrivateDomainFile.State.QUARANTINED
    row.save(update_fields=["detected_media_type", "state", "updated_at"])
    PrivateDomainFileEvent.objects.create(
        organization_id=job.organization_id,
        domain_file=row,
        from_state=PrivateDomainFile.State.UPLOADING,
        to_state=row.state,
        reason="upload_stored",
        occurred_at=now,
    )
    row.state = PrivateDomainFile.State.PENDING_SCAN
    row.save(update_fields=["state", "updated_at"])
    PrivateDomainFileEvent.objects.create(
        organization_id=job.organization_id,
        domain_file=row,
        from_state=PrivateDomainFile.State.QUARANTINED,
        to_state=row.state,
        reason="validation_passed",
        occurred_at=now,
    )
    enqueue_job(
        organization_id=job.organization_id,
        job_type=DocumentJob.Type.SCAN_DOMAIN_FILE,
        target_id=row.pk,
        idempotency_key=f"scan-domain:{row.pk}",
        correlation_id=job.correlation_id,
    )
    return "succeeded"


@transaction.atomic
def _scan_domain_file(job: DocumentJob) -> str:
    row = PrivateDomainFile.objects.select_for_update().get(
        organization_id=job.organization_id, pk=job.target_id
    )
    if row.state in {
        PrivateDomainFile.State.CLEAN,
        PrivateDomainFile.State.INFECTED,
        PrivateDomainFile.State.REJECTED,
    }:
        return "succeeded"
    if row.state not in {
        PrivateDomainFile.State.PENDING_SCAN,
        PrivateDomainFile.State.SCAN_ERROR,
    }:
        raise DocumentsError("invalid_file_state", "El archivo no puede analizarse.")
    started = timezone.now()
    with private_storage().open(row.storage_key) as stream:
        outcome = malware_scanner().scan(stream)
    finished = timezone.now()
    PrivateDomainScanAttempt.objects.create(
        organization_id=job.organization_id,
        domain_file=row,
        attempt=row.scan_attempts.count() + 1,
        scanner_name=outcome.scanner_name,
        scanner_version=outcome.scanner_version,
        signatures_version=outcome.signatures_version,
        result=outcome.result,
        malware_name=outcome.malware_name,
        detail=outcome.detail[:500],
        started_at=started,
        finished_at=finished,
    )
    previous = row.state
    if outcome.result == ScanResult.CLEAN:
        row.state = PrivateDomainFile.State.CLEAN
        row.available_at = finished
    elif outcome.result == ScanResult.INFECTED:
        row.state = PrivateDomainFile.State.INFECTED
    elif outcome.result == ScanResult.UNSUPPORTED:
        row.state = PrivateDomainFile.State.REJECTED
    else:
        row.state = PrivateDomainFile.State.SCAN_ERROR
    row.validation_detail = outcome.detail[:500]
    row.save(update_fields=["state", "available_at", "validation_detail", "updated_at"])
    PrivateDomainFileEvent.objects.create(
        organization_id=job.organization_id,
        domain_file=row,
        from_state=previous,
        to_state=row.state,
        reason="malware_scan",
        detail=outcome.detail[:500],
        occurred_at=finished,
    )
    return "retry" if row.state == PrivateDomainFile.State.SCAN_ERROR else "succeeded"


@transaction.atomic
def _render_domain_artifact(job: DocumentJob) -> str:
    artifact = GeneratedDomainArtifact.objects.select_for_update().get(
        organization_id=job.organization_id, pk=job.target_id
    )
    if artifact.state == GeneratedDomainArtifact.State.AVAILABLE:
        return "succeeded"
    if artifact.state != GeneratedDomainArtifact.State.PENDING_RENDER:
        raise DocumentsError("invalid_artifact_state", "El artefacto no puede renderizarse.")
    rendered = render_pdf(str(artifact.render_payload.get("html", "")))
    key = opaque_evidence_key("generated", str(artifact.pk))
    storage = private_storage()
    if storage.exists(key):
        with storage.open(key) as existing:
            content = existing.read()
        if hashlib.sha256(content).hexdigest() != rendered.sha256:
            raise DocumentsError("object_collision", "La evidencia existente no coincide.")
    else:
        storage.put(
            key=key,
            stream=bytes_stream(rendered.content),
            size_bytes=rendered.size_bytes,
            sha256=rendered.sha256,
            media_type="application/pdf",
        )
    artifact.storage_key = key
    artifact.sha256 = rendered.sha256
    artifact.size_bytes = rendered.size_bytes
    artifact.renderer_name = rendered.renderer_name
    artifact.renderer_version = rendered.renderer_version
    artifact.render_environment = rendered.environment
    artifact.stored_at = timezone.now()
    artifact.state = GeneratedDomainArtifact.State.AVAILABLE
    artifact.save(
        update_fields=[
            "storage_key",
            "sha256",
            "size_bytes",
            "renderer_name",
            "renderer_version",
            "render_environment",
            "stored_at",
            "state",
            "updated_at",
        ]
    )
    enqueue_job(
        organization_id=job.organization_id,
        job_type=DocumentJob.Type.VERIFY_DOMAIN_ARTIFACT,
        target_id=artifact.pk,
        idempotency_key=f"verify-domain:{artifact.pk}",
        correlation_id=job.correlation_id,
    )
    return "succeeded"


@transaction.atomic
def _verify_domain_artifact(job: DocumentJob) -> str:
    artifact = GeneratedDomainArtifact.objects.select_for_update().get(
        organization_id=job.organization_id, pk=job.target_id
    )
    if artifact.storage_key is None or artifact.size_bytes is None:
        raise DocumentsError("artifact_not_available", "El artefacto no está disponible.")
    try:
        with private_storage().open(artifact.storage_key) as stream:
            content = stream.read()
    except DocumentsError:
        artifact.state = GeneratedDomainArtifact.State.INTEGRITY_FAILED
        artifact.save(update_fields=["state", "updated_at"])
        return "dead"
    if (
        len(content) != artifact.size_bytes
        or hashlib.sha256(content).hexdigest() != artifact.sha256
    ):
        artifact.state = GeneratedDomainArtifact.State.INTEGRITY_FAILED
        artifact.save(update_fields=["state", "updated_at"])
        return "dead"
    artifact.verified_at = timezone.now()
    artifact.save(update_fields=["verified_at", "updated_at"])
    return "succeeded"


HANDLERS = {
    DocumentJob.Type.FINALIZE_EXTERNAL_UPLOAD: _finalize_upload,
    DocumentJob.Type.FINALIZE_DOMAIN_UPLOAD: _finalize_domain_upload,
    DocumentJob.Type.RENDER_ISSUED_VERSION: _render,
    DocumentJob.Type.RENDER_DOMAIN_ARTIFACT: _render_domain_artifact,
    DocumentJob.Type.SCAN_EXTERNAL_FILE: _scan,
    DocumentJob.Type.SCAN_DOMAIN_FILE: _scan_domain_file,
    DocumentJob.Type.VERIFY_ARTIFACT: _verify,
    DocumentJob.Type.VERIFY_DOMAIN_ARTIFACT: _verify_domain_artifact,
}


def _mark_render_terminal_failure(job: DocumentJob) -> None:
    if job.job_type == DocumentJob.Type.RENDER_DOMAIN_ARTIFACT:
        GeneratedDomainArtifact.objects.filter(
            organization_id=job.organization_id,
            pk=job.target_id,
            state=GeneratedDomainArtifact.State.PENDING_RENDER,
        ).update(state=GeneratedDomainArtifact.State.RENDER_FAILED)
        return
    if job.job_type != DocumentJob.Type.RENDER_ISSUED_VERSION:
        return
    IssuedInstrumentVersion.objects.filter(
        organization_id=job.organization_id,
        pk=job.target_id,
        state__in=[
            IssuedInstrumentVersion.State.PENDING_RENDER,
            IssuedInstrumentVersion.State.RENDERING,
        ],
    ).update(state=IssuedInstrumentVersion.State.RENDER_FAILED)


def execute_job(job: DocumentJob, *, worker_id: str) -> None:
    started = timezone.now()
    try:
        with transaction.atomic():
            locked = DocumentJob.objects.select_for_update().get(pk=job.pk)
            if locked.state != DocumentJob.State.RUNNING or locked.claimed_by != worker_id:
                return
        outcome = HANDLERS[DocumentJob.Type(locked.job_type)](locked)
        with transaction.atomic():
            locked = DocumentJob.objects.select_for_update().get(pk=job.pk)
            if locked.state != DocumentJob.State.RUNNING or locked.claimed_by != worker_id:
                return
            if outcome in {"retry", "dead"}:
                retryable = outcome == "retry" and locked.attempts < locked.max_attempts
                locked.state = DocumentJob.State.RETRY_WAIT if retryable else DocumentJob.State.DEAD
                locked.next_attempt_at = timezone.now() + timedelta(
                    seconds=min(300, 2**locked.attempts)
                )
                locked.lease_expires_at = None
                locked.last_error_code = (
                    "scanner_retryable_error" if outcome == "retry" else "integrity_terminal"
                )
                locked.save(
                    update_fields=[
                        "state",
                        "next_attempt_at",
                        "lease_expires_at",
                        "last_error_code",
                        "updated_at",
                    ]
                )
                DocumentJobAttempt.objects.create(
                    organization_id=locked.organization_id,
                    job=locked,
                    attempt=locked.attempts,
                    worker_id=worker_id,
                    outcome="retry" if retryable else "dead",
                    error_code=locked.last_error_code,
                    started_at=started,
                    finished_at=timezone.now(),
                )
                if not retryable:
                    _mark_render_terminal_failure(locked)
                return
            locked.state = DocumentJob.State.SUCCEEDED
            locked.completed_at = timezone.now()
            locked.lease_expires_at = None
            locked.save(update_fields=["state", "completed_at", "lease_expires_at", "updated_at"])
            DocumentJobAttempt.objects.create(
                organization_id=locked.organization_id,
                job=locked,
                attempt=locked.attempts,
                worker_id=worker_id,
                outcome="succeeded",
                started_at=started,
                finished_at=timezone.now(),
            )
    except Exception as error:
        with transaction.atomic():
            locked = DocumentJob.objects.select_for_update().get(pk=job.pk)
            retryable = locked.attempts < locked.max_attempts
            locked.state = DocumentJob.State.RETRY_WAIT if retryable else DocumentJob.State.DEAD
            locked.next_attempt_at = timezone.now() + timedelta(
                seconds=min(300, 2**locked.attempts)
            )
            locked.lease_expires_at = None
            locked.last_error_code = (
                error.code if isinstance(error, DocumentsError) else type(error).__name__
            )[:80]
            locked.last_error_detail = str(error)[:500]
            locked.save(
                update_fields=[
                    "state",
                    "next_attempt_at",
                    "lease_expires_at",
                    "last_error_code",
                    "last_error_detail",
                    "updated_at",
                ]
            )
            DocumentJobAttempt.objects.create(
                organization_id=locked.organization_id,
                job=locked,
                attempt=locked.attempts,
                worker_id=worker_id,
                outcome="retry" if retryable else "dead",
                error_code=locked.last_error_code,
                detail=locked.last_error_detail,
                started_at=started,
                finished_at=timezone.now(),
            )
            if not retryable:
                _mark_render_terminal_failure(locked)
        logger.exception("document_job_failed", extra={"job_id": str(job.pk)})


def work_once(organization_id: uuid.UUID, *, worker_id: str) -> bool:
    with infrastructure_tenant_scope(organization_id, purpose="document_worker"):
        job = claim_job(organization_id, worker_id=worker_id)
        if job is None:
            return False
        execute_job(job, worker_id=worker_id)
        return True
