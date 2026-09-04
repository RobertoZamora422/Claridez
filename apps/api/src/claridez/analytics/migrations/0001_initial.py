import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("organizations", "0004_venues_and_spaces"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReportDefinition",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("current_revision", models.PositiveIntegerField(default=1)),
                ("archived", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "owner_membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="analytics_reports",
                        to="organizations.membership",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ReportExecution",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("idempotency_key", models.UUIDField()),
                ("request_sha256", models.CharField(max_length=64)),
                ("catalog_version", models.CharField(max_length=32)),
                ("catalog_sha256", models.CharField(max_length=64)),
                ("selection", models.JSONField()),
                ("timezone_name", models.CharField(max_length=64)),
                ("knowledge_cutoff_at", models.DateTimeField()),
                ("executed_at", models.DateTimeField()),
                ("result_snapshot", models.JSONField()),
                ("result_sha256", models.CharField(max_length=64)),
                ("row_count", models.PositiveIntegerField()),
                ("snapshot_byte_size", models.PositiveIntegerField()),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "requested_by_membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="analytics_executions",
                        to="organizations.membership",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ExportJob",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("idempotency_key", models.UUIDField()),
                ("request_sha256", models.CharField(max_length=64)),
                ("artifact_identity", models.UUIDField(default=uuid.uuid4)),
                (
                    "format",
                    models.CharField(
                        choices=[("csv", "CSV"), ("xlsx", "XLSX"), ("pdf", "PDF")], max_length=4
                    ),
                ),
                ("renderer_version", models.CharField(max_length=64)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("queued", "En cola"),
                            ("running", "Procesando"),
                            ("retry", "Esperando reintento"),
                            ("completed", "Disponible"),
                            ("terminal", "Fallo definitivo"),
                        ],
                        default="queued",
                        max_length=12,
                    ),
                ),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("lease_token", models.UUIDField(blank=True, null=True)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, max_length=64)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "requested_by_membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="analytics_exports",
                        to="organizations.membership",
                    ),
                ),
                (
                    "execution",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="exports",
                        to="analytics.reportexecution",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ExecutionManifest",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("schema_version", models.PositiveIntegerField(default=1)),
                ("provenance", models.JSONField()),
                ("provenance_sha256", models.CharField(max_length=64)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "execution",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="manifest",
                        to="analytics.reportexecution",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ReportRevision",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("number", models.PositiveIntegerField()),
                ("title", models.CharField(max_length=120)),
                (
                    "visibility",
                    models.CharField(
                        choices=[("private", "Privada"), ("organization", "Organización")],
                        max_length=16,
                    ),
                ),
                ("selection", models.JSONField()),
                ("timezone_name", models.CharField(max_length=64)),
                ("definition_sha256", models.CharField(max_length=64)),
                (
                    "authored_by_membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="analytics_report_revisions",
                        to="organizations.membership",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revisions",
                        to="analytics.reportdefinition",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="reportexecution",
            name="report_revision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="executions",
                to="analytics.reportrevision",
            ),
        ),
        migrations.CreateModel(
            name="AnalyticsAuditEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("event", models.CharField(max_length=40)),
                ("subject_id", models.UUIDField()),
                ("detail", models.JSONField(default=dict)),
                (
                    "actor_membership",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="analytics_audit_events",
                        to="organizations.membership",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["organization", "subject_id", "created_at"],
                        name="analytics_audit_subject_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="analytics_audit_org_id_uq"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ExportAttempt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("number", models.PositiveIntegerField()),
                ("lease_token", models.UUIDField()),
                ("event", models.CharField(max_length=16)),
                ("reason_code", models.CharField(blank=True, max_length=64)),
                ("occurred_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="attempts",
                        to="analytics.exportjob",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="analytics_attempt_org_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "job", "number", "event"),
                        name="analytics_attempt_event_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("number__gte", 1), ("number__lte", 5)),
                        name="analytics_attempt_number_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "event__in",
                                ["claimed", "completed", "retry", "terminal", "reclaimed"],
                            )
                        ),
                        name="analytics_attempt_event_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ExportArtifact",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("object_key", models.CharField(max_length=96)),
                ("sha256", models.CharField(max_length=64)),
                ("byte_size", models.PositiveIntegerField()),
                (
                    "format",
                    models.CharField(
                        choices=[("csv", "CSV"), ("xlsx", "XLSX"), ("pdf", "PDF")], max_length=4
                    ),
                ),
                ("renderer_version", models.CharField(max_length=64)),
                (
                    "organization",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="organizations.organization",
                    ),
                ),
                (
                    "job",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="artifact",
                        to="analytics.exportjob",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "id"), name="analytics_artifact_org_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("organization", "object_key"), name="analytics_artifact_key_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("byte_size__gt", 0), ("byte_size__lte", 20971520)),
                        name="analytics_artifact_size_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("format__in", ["csv", "xlsx", "pdf"])),
                        name="analytics_artifact_format_ck",
                    ),
                ],
            },
        ),
        migrations.AddIndex(
            model_name="reportdefinition",
            index=models.Index(
                fields=["organization", "owner_membership", "-created_at"],
                name="analytics_report_owner_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="reportdefinition",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="analytics_report_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="reportdefinition",
            constraint=models.CheckConstraint(
                condition=models.Q(("current_revision__gte", 1)),
                name="analytics_report_revision_ck",
            ),
        ),
        migrations.AddIndex(
            model_name="exportjob",
            index=models.Index(
                condition=models.Q(("state__in", ["queued", "retry"])),
                fields=["organization", "next_attempt_at", "created_at", "id"],
                name="analytics_job_ready_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="exportjob",
            index=models.Index(
                condition=models.Q(("state", "running")),
                fields=["organization", "lease_expires_at", "id"],
                name="analytics_job_reclaim_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="exportjob",
            index=models.Index(
                fields=["organization", "requested_by_membership", "-created_at"],
                name="analytics_job_history_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="exportjob",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="analytics_job_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="exportjob",
            constraint=models.UniqueConstraint(
                fields=("organization", "artifact_identity"), name="analytics_job_artifact_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="exportjob",
            constraint=models.UniqueConstraint(
                fields=("organization", "requested_by_membership", "idempotency_key"),
                name="analytics_job_replay_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="exportjob",
            constraint=models.CheckConstraint(
                condition=models.Q(("format__in", ["csv", "xlsx", "pdf"])),
                name="analytics_job_format_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="exportjob",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("state__in", ["queued", "running", "retry", "completed", "terminal"])
                ),
                name="analytics_job_state_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="exportjob",
            constraint=models.CheckConstraint(
                condition=models.Q(("attempt_count__lte", 5)), name="analytics_job_attempts_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="exportjob",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("lease_expires_at__isnull", False),
                        ("lease_token__isnull", False),
                        ("state", "running"),
                    ),
                    models.Q(
                        models.Q(("state", "running"), _negated=True),
                        ("lease_expires_at__isnull", True),
                        ("lease_token__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="analytics_job_lease_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="exportjob",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("completed_at__isnull", False), ("state", "completed")),
                    models.Q(
                        models.Q(("state", "completed"), _negated=True),
                        ("completed_at__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="analytics_job_completed_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="executionmanifest",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="analytics_manifest_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="executionmanifest",
            constraint=models.CheckConstraint(
                condition=models.Q(("schema_version", 1)), name="analytics_manifest_version_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="reportrevision",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="analytics_revision_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="reportrevision",
            constraint=models.UniqueConstraint(
                fields=("organization", "report", "number"), name="analytics_revision_number_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="reportrevision",
            constraint=models.CheckConstraint(
                condition=models.Q(("number__gte", 1)), name="analytics_revision_number_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="reportrevision",
            constraint=models.CheckConstraint(
                condition=models.Q(("visibility__in", ["private", "organization"])),
                name="analytics_revision_visibility_ck",
            ),
        ),
        migrations.AddIndex(
            model_name="reportexecution",
            index=models.Index(
                fields=["organization", "requested_by_membership", "-executed_at"],
                name="analytics_execution_hist_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="reportexecution",
            constraint=models.UniqueConstraint(
                fields=("organization", "id"), name="analytics_execution_org_id_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="reportexecution",
            constraint=models.UniqueConstraint(
                fields=("organization", "requested_by_membership", "idempotency_key"),
                name="analytics_execution_replay_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="reportexecution",
            constraint=models.CheckConstraint(
                condition=models.Q(("knowledge_cutoff_at__lte", models.F("executed_at"))),
                name="analytics_execution_cutoff_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="reportexecution",
            constraint=models.CheckConstraint(
                condition=models.Q(("row_count__lte", 25000)), name="analytics_execution_rows_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="reportexecution",
            constraint=models.CheckConstraint(
                condition=models.Q(("snapshot_byte_size__lte", 20971520)),
                name="analytics_execution_size_ck",
            ),
        ),
    ]
