# ruff: noqa: DJ008
"""Estado privado P15. No hay hechos de negocio, fórmulas configurables ni caché transversal."""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, db_index=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class ReportDefinition(TenantModel):
    owner_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="analytics_reports"
    )
    current_revision = models.PositiveIntegerField(default=1)
    archived = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="analytics_report_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(current_revision__gte=1), name="analytics_report_revision_ck"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "owner_membership", "-created_at"],
                name="analytics_report_owner_idx",
            )
        ]


class ReportRevision(TenantModel):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Privada"
        ORGANIZATION = "organization", "Organización"

    report = models.ForeignKey(ReportDefinition, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=120)
    visibility = models.CharField(max_length=16, choices=Visibility.choices)
    selection = models.JSONField()
    timezone_name = models.CharField(max_length=64)
    definition_sha256 = models.CharField(max_length=64)
    authored_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="analytics_report_revisions",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="analytics_revision_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "report", "number"], name="analytics_revision_number_uq"
            ),
            models.CheckConstraint(condition=Q(number__gte=1), name="analytics_revision_number_ck"),
            models.CheckConstraint(
                condition=Q(visibility__in=["private", "organization"]),
                name="analytics_revision_visibility_ck",
            ),
        ]


class ReportExecution(TenantModel):
    report_revision = models.ForeignKey(
        ReportRevision, on_delete=models.PROTECT, related_name="executions", null=True, blank=True
    )
    requested_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="analytics_executions"
    )
    idempotency_key = models.UUIDField()
    request_sha256 = models.CharField(max_length=64)
    catalog_version = models.CharField(max_length=32)
    catalog_sha256 = models.CharField(max_length=64)
    selection = models.JSONField()
    timezone_name = models.CharField(max_length=64)
    knowledge_cutoff_at = models.DateTimeField()
    executed_at = models.DateTimeField()
    result_snapshot = models.JSONField()
    result_sha256 = models.CharField(max_length=64)
    row_count = models.PositiveIntegerField()
    snapshot_byte_size = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="analytics_execution_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "requested_by_membership", "idempotency_key"],
                name="analytics_execution_replay_uq",
            ),
            models.CheckConstraint(
                condition=Q(knowledge_cutoff_at__lte=models.F("executed_at")),
                name="analytics_execution_cutoff_ck",
            ),
            models.CheckConstraint(
                condition=Q(row_count__lte=25000), name="analytics_execution_rows_ck"
            ),
            models.CheckConstraint(
                condition=Q(snapshot_byte_size__lte=20971520), name="analytics_execution_size_ck"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "requested_by_membership", "-executed_at"],
                name="analytics_execution_hist_idx",
            )
        ]


class ExecutionManifest(TenantModel):
    execution = models.OneToOneField(
        ReportExecution, on_delete=models.PROTECT, related_name="manifest"
    )
    schema_version = models.PositiveIntegerField(default=1)
    provenance = models.JSONField()
    provenance_sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="analytics_manifest_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(schema_version=1), name="analytics_manifest_version_ck"
            ),
        ]


class ExportJob(TenantModel):
    class Format(models.TextChoices):
        CSV = "csv", "CSV"
        XLSX = "xlsx", "XLSX"
        PDF = "pdf", "PDF"

    class State(models.TextChoices):
        QUEUED = "queued", "En cola"
        RUNNING = "running", "Procesando"
        RETRY = "retry", "Esperando reintento"
        COMPLETED = "completed", "Disponible"
        TERMINAL = "terminal", "Fallo definitivo"

    execution = models.ForeignKey(ReportExecution, on_delete=models.PROTECT, related_name="exports")
    requested_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="analytics_exports"
    )
    idempotency_key = models.UUIDField()
    request_sha256 = models.CharField(max_length=64)
    artifact_identity = models.UUIDField(default=uuid.uuid4)
    format = models.CharField(max_length=4, choices=Format.choices)
    renderer_version = models.CharField(max_length=64)
    state = models.CharField(max_length=12, choices=State.choices, default=State.QUEUED)
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="analytics_job_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "artifact_identity"], name="analytics_job_artifact_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "requested_by_membership", "idempotency_key"],
                name="analytics_job_replay_uq",
            ),
            models.CheckConstraint(
                condition=Q(format__in=["csv", "xlsx", "pdf"]), name="analytics_job_format_ck"
            ),
            models.CheckConstraint(
                condition=Q(state__in=["queued", "running", "retry", "completed", "terminal"]),
                name="analytics_job_state_ck",
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__lte=5), name="analytics_job_attempts_ck"
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="running", lease_token__isnull=False, lease_expires_at__isnull=False)
                    | (
                        ~Q(state="running")
                        & Q(lease_token__isnull=True, lease_expires_at__isnull=True)
                    )
                ),
                name="analytics_job_lease_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="completed", completed_at__isnull=False)
                    | (~Q(state="completed") & Q(completed_at__isnull=True))
                ),
                name="analytics_job_completed_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "next_attempt_at", "created_at", "id"],
                condition=Q(state__in=["queued", "retry"]),
                name="analytics_job_ready_idx",
            ),
            models.Index(
                fields=["organization", "lease_expires_at", "id"],
                condition=Q(state="running"),
                name="analytics_job_reclaim_idx",
            ),
            models.Index(
                fields=["organization", "requested_by_membership", "-created_at"],
                name="analytics_job_history_idx",
            ),
        ]


class ExportAttempt(TenantModel):
    job = models.ForeignKey(ExportJob, on_delete=models.PROTECT, related_name="attempts")
    number = models.PositiveIntegerField()
    lease_token = models.UUIDField()
    event = models.CharField(max_length=16)
    reason_code = models.CharField(max_length=64, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="analytics_attempt_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "job", "number", "event"], name="analytics_attempt_event_uq"
            ),
            models.CheckConstraint(
                condition=Q(number__gte=1, number__lte=5), name="analytics_attempt_number_ck"
            ),
            models.CheckConstraint(
                condition=Q(event__in=["claimed", "completed", "retry", "terminal", "reclaimed"]),
                name="analytics_attempt_event_ck",
            ),
        ]


class ExportArtifact(TenantModel):
    job = models.OneToOneField(ExportJob, on_delete=models.PROTECT, related_name="artifact")
    object_key = models.CharField(max_length=96)
    sha256 = models.CharField(max_length=64)
    byte_size = models.PositiveIntegerField()
    format = models.CharField(max_length=4, choices=ExportJob.Format.choices)
    renderer_version = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="analytics_artifact_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "object_key"], name="analytics_artifact_key_uq"
            ),
            models.CheckConstraint(
                condition=Q(byte_size__gt=0, byte_size__lte=20971520),
                name="analytics_artifact_size_ck",
            ),
            models.CheckConstraint(
                condition=Q(format__in=["csv", "xlsx", "pdf"]), name="analytics_artifact_format_ck"
            ),
        ]


class AnalyticsAuditEvent(TenantModel):
    actor_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="analytics_audit_events",
        null=True,
        blank=True,
    )
    event = models.CharField(max_length=40)
    subject_id = models.UUIDField()
    detail = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="analytics_audit_org_id_uq")
        ]
        indexes = [
            models.Index(
                fields=["organization", "subject_id", "created_at"],
                name="analytics_audit_subject_idx",
            )
        ]
