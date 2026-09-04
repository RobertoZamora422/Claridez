"""Aplicación P15: comandos explícitos, revisiones append-only y ejecuciones acotadas."""

from __future__ import annotations

import hashlib
import json
from typing import cast
from uuid import UUID

from django.db import connection
from django.db.models import F, Q
from django.utils import timezone

from claridez.finance.public import periods_for_analytics
from claridez.identity.models import User
from claridez.organizations.analytics_contracts import evidence_watermark
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.public import settings_for_analytics
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from .errors import conflict, invalid, unavailable
from .models import (
    AnalyticsAuditEvent,
    ExecutionManifest,
    ExportArtifact,
    ExportJob,
    ReportDefinition,
    ReportExecution,
    ReportRevision,
)
from .pagination import page
from .presets import permitted_preset
from .query import (
    MetricSelection,
    allowed_catalog,
    authorize_selections,
    execute_query,
    output_payload,
    selection_from_payload,
    selection_payload,
)

MAX_HISTORY_ROWS = 100


def history_page(
    actor: User,
    organization_id: UUID,
    collection: str,
    *,
    report_id: UUID | None = None,
    cursor: str = "",
    limit: int = 50,
) -> dict[str, object]:
    capability = (
        Capability.ANALYTICS_CREATE_EXPORT
        if collection == "exports"
        else Capability.ANALYTICS_EXECUTE_REPORT
    )
    with authorized_tenant_scope(actor, organization_id, capability) as auth:
        if collection in {"reports", "revisions"}:
            report_rows = (
                ReportRevision.objects.select_related("report")
                .filter(
                    organization_id=auth.organization_id,
                )
                .filter(
                    Q(visibility="organization") | Q(report__owner_membership_id=auth.membership_id)
                )
            )
            if collection == "reports":
                report_rows = report_rows.filter(
                    number=F("report__current_revision"), report__archived=False
                )
            else:
                if report_id is None:
                    raise ValueError("report_id_required")
                report_rows = report_rows.filter(report_id=report_id)

            def report_value(row: ReportRevision) -> dict[str, object]:
                authorize_selections(auth, stored_selections(row.selection), capability)
                return _report_data(row)

            return page(
                report_rows,
                auth,
                f"{collection}:{report_id or ''}",
                report_value,
                cursor=cursor,
                limit=limit,
            )
        if collection == "executions":
            execution_rows = ReportExecution.objects.filter(
                organization_id=auth.organization_id,
                requested_by_membership_id=auth.membership_id,
            ).defer("result_snapshot")

            def execution_value(row: ReportExecution) -> dict[str, object]:
                authorize_selections(auth, stored_selections(row.selection), capability)
                return _execution_data(row, result=False)

            return page(
                execution_rows, auth, collection, execution_value, cursor=cursor, limit=limit
            )
        if collection == "exports":
            export_rows = (
                ExportJob.objects.select_related("execution")
                .filter(
                    organization_id=auth.organization_id,
                    requested_by_membership_id=auth.membership_id,
                )
                .defer("execution__result_snapshot")
            )

            def export_value(row: ExportJob) -> dict[str, object]:
                authorize_selections(auth, stored_selections(row.execution.selection), capability)
                return export_data(row)

            return page(export_rows, auth, collection, export_value, cursor=cursor, limit=limit)
        raise ValueError("unknown_history_collection")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def payload_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _lock(organization_id: UUID, key: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"analytics:{organization_id}:{key}"],
        )


def audit(
    authorization: TenantAuthorization,
    event: str,
    subject_id: UUID,
    detail: dict[str, object] | None = None,
) -> None:
    AnalyticsAuditEvent.objects.create(
        organization_id=authorization.organization_id,
        actor_membership_id=authorization.membership_id,
        event=event,
        subject_id=subject_id,
        detail=detail or {},
    )


def stored_selections(value: object) -> tuple[MetricSelection, ...]:
    if not isinstance(value, list):
        raise ValueError("stored_metric_selection_invalid")
    return tuple(selection_from_payload(cast(dict[str, object], row)) for row in value)


def _validate_definition(
    authorization: TenantAuthorization,
    selections: tuple[MetricSelection, ...],
    timezone_name: str,
    title: str,
    visibility: str,
) -> None:
    if not title.strip() or len(title) > 120 or any(ord(char) < 32 for char in title):
        raise invalid("invalid_report_title", "Escriba un título de hasta 120 caracteres.")
    if visibility not in ReportRevision.Visibility.values:
        raise invalid("invalid_report_visibility", "La visibilidad no es válida.")
    authorize_selections(authorization, selections, Capability.ANALYTICS_MANAGE_OWN_REPORT)
    if visibility == ReportRevision.Visibility.ORGANIZATION:
        authorization.require(Capability.ANALYTICS_MANAGE_SHARED_REPORT)
    now = timezone.now()
    for row in selections:
        row.source_query(timezone_name=timezone_name, knowledge_cutoff_at=now, executed_at=now)


def _report_data(revision: ReportRevision) -> dict[str, object]:
    return {
        "id": str(revision.report_id),
        "revision_id": str(revision.pk),
        "revision": revision.number,
        "title": revision.title,
        "visibility": revision.visibility,
        "timezone": revision.timezone_name,
        "selection": revision.selection,
        "owner_membership_id": str(revision.report.owner_membership_id),
        "archived": revision.report.archived,
        "created_at": revision.created_at.isoformat(),
        "definition_sha256": revision.definition_sha256,
    }


def _authorized_revision(
    authorization: TenantAuthorization, revision_id: UUID, *, manage: bool = False
) -> ReportRevision:
    revision = (
        ReportRevision.objects.select_related("report")
        .filter(
            organization_id=authorization.organization_id,
            pk=revision_id,
        )
        .filter(
            Q(visibility=ReportRevision.Visibility.ORGANIZATION)
            | Q(report__owner_membership_id=authorization.membership_id)
        )
        .first()
    )
    if revision is None:
        raise unavailable("El reporte no está disponible.")
    authorize_selections(
        authorization,
        stored_selections(revision.selection),
        Capability.ANALYTICS_MANAGE_OWN_REPORT if manage else Capability.ANALYTICS_EXECUTE_REPORT,
    )
    if manage:
        if revision.visibility == ReportRevision.Visibility.ORGANIZATION:
            authorization.require(Capability.ANALYTICS_MANAGE_SHARED_REPORT)
        elif revision.report.owner_membership_id != authorization.membership_id:
            raise unavailable("El reporte no está disponible.")
    return revision


def create_report(
    actor: User,
    organization_id: UUID,
    *,
    title: str,
    visibility: str,
    timezone_name: str,
    selections: tuple[MetricSelection, ...],
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_MANAGE_OWN_REPORT
    ) as auth:
        _validate_definition(auth, selections, timezone_name, title, visibility)
        definition = ReportDefinition.objects.create(
            organization_id=auth.organization_id, owner_membership_id=auth.membership_id
        )
        data = [selection_payload(row) for row in selections]
        revision = ReportRevision.objects.create(
            organization_id=auth.organization_id,
            report=definition,
            number=1,
            title=title.strip(),
            visibility=visibility,
            timezone_name=timezone_name,
            selection=data,
            definition_sha256=payload_hash(
                {
                    "title": title.strip(),
                    "visibility": visibility,
                    "timezone": timezone_name,
                    "selection": data,
                }
            ),
            authored_by_membership_id=auth.membership_id,
        )
        audit(auth, "report_created", definition.pk, {"revision_id": str(revision.pk)})
        return _report_data(revision)


def revise_report(
    actor: User,
    organization_id: UUID,
    report_id: UUID,
    *,
    expected_revision: int,
    title: str,
    visibility: str,
    timezone_name: str,
    selections: tuple[MetricSelection, ...],
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_MANAGE_OWN_REPORT
    ) as auth:
        definition = (
            ReportDefinition.objects.select_for_update()
            .filter(organization_id=auth.organization_id, pk=report_id)
            .first()
        )
        if definition is None:
            raise unavailable("El reporte no está disponible.")
        previous = ReportRevision.objects.filter(
            organization_id=auth.organization_id,
            report_id=definition.pk,
            number=definition.current_revision,
        ).first()
        if previous is None:
            raise unavailable("El reporte no está disponible.")
        _authorized_revision(auth, previous.pk, manage=True)
        if definition.current_revision != expected_revision:
            raise conflict("stale_revision", "El reporte tiene una revisión más reciente.")
        _validate_definition(auth, selections, timezone_name, title, visibility)
        data = [selection_payload(row) for row in selections]
        revision = ReportRevision.objects.create(
            organization_id=auth.organization_id,
            report=definition,
            number=expected_revision + 1,
            title=title.strip(),
            visibility=visibility,
            timezone_name=timezone_name,
            selection=data,
            definition_sha256=payload_hash(
                {
                    "title": title.strip(),
                    "visibility": visibility,
                    "timezone": timezone_name,
                    "selection": data,
                }
            ),
            authored_by_membership_id=auth.membership_id,
        )
        definition.current_revision = revision.number
        definition.save(update_fields=["current_revision", "updated_at"])
        audit(auth, "report_revised", definition.pk, {"revision_id": str(revision.pk)})
        return _report_data(revision)


def list_reports(actor: User, organization_id: UUID) -> tuple[dict[str, object], ...]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_EXECUTE_REPORT
    ) as auth:
        rows = (
            ReportRevision.objects.select_related("report")
            .filter(
                organization_id=auth.organization_id,
                number=F("report__current_revision"),
                report__archived=False,
            )
            .filter(
                Q(visibility="organization") | Q(report__owner_membership_id=auth.membership_id)
            )
            .order_by("-created_at", "id")[:MAX_HISTORY_ROWS]
        )
        result = []
        for row in rows:
            try:
                authorize_selections(
                    auth, stored_selections(row.selection), Capability.ANALYTICS_EXECUTE_REPORT
                )
            except AuthorizationDenied:
                continue
            result.append(_report_data(row))
        return tuple(result)


def report_revisions(
    actor: User, organization_id: UUID, report_id: UUID
) -> tuple[dict[str, object], ...]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_EXECUTE_REPORT
    ) as auth:
        rows = (
            ReportRevision.objects.select_related("report")
            .filter(organization_id=auth.organization_id, report_id=report_id)
            .filter(
                Q(visibility="organization") | Q(report__owner_membership_id=auth.membership_id)
            )
            .order_by("-number")[:MAX_HISTORY_ROWS]
        )
        result = []
        for row in rows:
            try:
                authorize_selections(
                    auth, stored_selections(row.selection), Capability.ANALYTICS_EXECUTE_REPORT
                )
            except AuthorizationDenied:
                continue
            result.append(_report_data(row))
        return tuple(result)


def dashboard_query(
    actor: User,
    organization_id: UUID,
    *,
    timezone_name: str,
    selections: tuple[MetricSelection, ...],
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_READ_DASHBOARD
    ) as auth:
        # Consulta interactiva: no inserta una ReportExecution, ni audit por cada refresh.
        return output_payload(
            execute_query(
                auth,
                selections,
                timezone_name=timezone_name,
                capability=Capability.ANALYTICS_READ_DASHBOARD,
            )
        )


def catalog_metadata(actor: User, organization_id: UUID) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_READ_DASHBOARD
    ) as auth:
        from .registry import CATALOG_HASH, CATALOG_VERSION

        organization_settings = settings_for_analytics(auth)
        metrics = list(allowed_catalog(auth))
        periods = (
            periods_for_analytics(auth)
            if Capability.FINANCE_READ in capabilities_for_role(auth.role)
            else ()
        )
        return {
            "catalog_version": CATALOG_VERSION,
            "catalog_hash": CATALOG_HASH,
            "profile": auth.role.value,
            "capabilities": sorted(
                row.value
                for row in capabilities_for_role(auth.role)
                if row.value.startswith("analytics:")
            ),
            "metrics": metrics,
            "preset": permitted_preset(auth.role.value, {str(row["metric_id"]) for row in metrics}),
            "server_now": timezone.now().isoformat(),
            "timezone": organization_settings.timezone_name,
            "currency": organization_settings.currency,
            "periods": [
                {
                    "id": str(row.id),
                    "starts_on": row.starts_on.isoformat(),
                    "ends_on": row.ends_on.isoformat(),
                    "currency": row.currency,
                    "closed": row.closed,
                }
                for row in periods
            ],
        }


def _execution_data(
    row: ReportExecution, *, result: bool, resolved: dict[str, object] | None = None
) -> dict[str, object]:
    data: dict[str, object] = {
        "id": str(row.pk),
        "report_revision_id": str(row.report_revision_id) if row.report_revision_id else None,
        "executed_at": row.executed_at.isoformat(),
        "knowledge_cutoff_at": row.knowledge_cutoff_at.isoformat(),
        "catalog_version": row.catalog_version,
        "catalog_hash": row.catalog_sha256,
        "result_sha256": row.result_sha256,
        "row_count": row.row_count,
        "timezone": row.timezone_name,
    }
    if result:
        if resolved is None:
            raise ValueError("execution_result_must_be_reconstructed")
        data["result"] = resolved
    return data


def authorized_execution(
    auth: TenantAuthorization, execution_id: UUID, capability: Capability
) -> ReportExecution:
    row = ReportExecution.objects.filter(
        organization_id=auth.organization_id,
        pk=execution_id,
        requested_by_membership_id=auth.membership_id,
    ).first()
    if row is None:
        raise unavailable("La ejecución no está disponible.")
    authorize_selections(auth, stored_selections(row.selection), capability)
    return row


def run_report(
    actor: User,
    organization_id: UUID,
    *,
    idempotency_key: UUID,
    report_revision_id: UUID | None = None,
    timezone_name: str | None = None,
    selections: tuple[MetricSelection, ...] = (),
) -> dict[str, object]:
    from .exporting import freeze_payload, reconstruct_execution

    if (report_revision_id is None) == (not selections):
        raise invalid(
            "invalid_execution_selection", "Indique una revisión o una selección métrica, no ambas."
        )
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_EXECUTE_REPORT
    ) as auth:
        if report_revision_id:
            revision = _authorized_revision(auth, report_revision_id)
            selections, timezone_name = (
                stored_selections(revision.selection),
                revision.timezone_name,
            )
        if not timezone_name:
            raise invalid("timezone_required", "La zona IANA es obligatoria.")
        authorize_selections(auth, selections, Capability.ANALYTICS_EXECUTE_REPORT)
        request_digest = payload_hash(
            {
                "revision_id": str(report_revision_id) if report_revision_id else None,
                "timezone": timezone_name,
                "selection": [selection_payload(item) for item in selections],
            }
        )
        _lock(auth.organization_id, f"execution:{auth.membership_id}:{idempotency_key}")
        replay = ReportExecution.objects.filter(
            organization_id=auth.organization_id,
            requested_by_membership_id=auth.membership_id,
            idempotency_key=idempotency_key,
        ).first()
        if replay is not None:
            if replay.request_sha256 != request_digest:
                raise conflict("idempotency_conflict", "La clave ya corresponde a otra ejecución.")
            return _execution_data(
                replay,
                result=True,
                resolved=reconstruct_execution(auth, replay, Capability.ANALYTICS_EXECUTE_REPORT),
            )
        output = execute_query(
            auth,
            selections,
            timezone_name=timezone_name,
            capability=Capability.ANALYTICS_EXECUTE_REPORT,
        )
        snapshot = output_payload(output)
        frozen = freeze_payload(snapshot)
        execution = ReportExecution.objects.create(
            organization_id=auth.organization_id,
            requested_by_membership_id=auth.membership_id,
            report_revision_id=report_revision_id,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
            catalog_version=output.catalog_version,
            catalog_sha256=output.catalog_hash,
            selection=snapshot["selection"],
            timezone_name=output.timezone_name,
            knowledge_cutoff_at=output.knowledge_cutoff_at,
            executed_at=output.executed_at,
            result_snapshot=frozen,
            result_sha256=payload_hash(snapshot),
            row_count=sum(len(item.result.points) for item in output.metrics),
            snapshot_byte_size=len(canonical_bytes(frozen)),
        )
        provenance = {
            "schema_version": 1,
            "catalog_hash": output.catalog_hash,
            "materialization": "source_requery_or_execution_scoped_snapshot",
            "result_sha256": execution.result_sha256,
            "sources": [
                {
                    "metric_id": item.metric_id,
                    "source_metric_id": item.result.source_metric_id,
                    "source_metric_version": item.result.source_metric_version,
                    "watermark": item.result.watermark,
                    "references_sha256": evidence_watermark(item.result.provenance),
                    "reference_count": len(item.result.provenance),
                    "source_kinds": sorted(
                        {reference.split(":", 1)[0] for reference in item.result.provenance}
                    ),
                    "coverage": item.result.coverage.value,
                    "coverage_reason": item.result.coverage_reason,
                }
                for item in output.metrics
            ],
        }
        ExecutionManifest.objects.create(
            organization_id=auth.organization_id,
            execution=execution,
            provenance=provenance,
            provenance_sha256=payload_hash(provenance),
        )
        audit(auth, "report_executed", execution.pk, {"result_sha256": execution.result_sha256})
        return _execution_data(execution, result=True, resolved=snapshot)


def execution_detail(actor: User, organization_id: UUID, execution_id: UUID) -> dict[str, object]:
    from .exporting import reconstruct_execution

    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_EXECUTE_REPORT
    ) as auth:
        execution = authorized_execution(auth, execution_id, Capability.ANALYTICS_EXECUTE_REPORT)
        return _execution_data(
            execution,
            result=True,
            resolved=reconstruct_execution(auth, execution, Capability.ANALYTICS_EXECUTE_REPORT),
        )


def execution_history(actor: User, organization_id: UUID) -> tuple[dict[str, object], ...]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_EXECUTE_REPORT
    ) as auth:
        rows = (
            ReportExecution.objects.filter(
                organization_id=auth.organization_id, requested_by_membership_id=auth.membership_id
            )
            .defer("result_snapshot")
            .order_by("-executed_at", "id")[:MAX_HISTORY_ROWS]
        )
        result = []
        for row in rows:
            try:
                authorize_selections(
                    auth, stored_selections(row.selection), Capability.ANALYTICS_EXECUTE_REPORT
                )
            except AuthorizationDenied:
                continue
            result.append(_execution_data(row, result=False))
        return tuple(result)


def create_export(
    actor: User, organization_id: UUID, execution_id: UUID, *, format: str, idempotency_key: UUID
) -> dict[str, object]:
    from .exporting import renderer_version

    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_CREATE_EXPORT
    ) as auth:
        if format not in ExportJob.Format.values:
            raise invalid("invalid_export_format", "Seleccione CSV, XLSX o PDF.")
        execution = authorized_execution(auth, execution_id, Capability.ANALYTICS_CREATE_EXPORT)
        request_digest = payload_hash({"execution_id": str(execution.pk), "format": format})
        _lock(auth.organization_id, f"export:{auth.membership_id}:{idempotency_key}")
        replay = ExportJob.objects.filter(
            organization_id=auth.organization_id,
            requested_by_membership_id=auth.membership_id,
            idempotency_key=idempotency_key,
        ).first()
        if replay is not None:
            if replay.request_sha256 != request_digest:
                raise conflict(
                    "idempotency_conflict", "La clave ya corresponde a otra exportación."
                )
            return export_data(replay)
        job = ExportJob.objects.create(
            organization_id=auth.organization_id,
            execution=execution,
            requested_by_membership_id=auth.membership_id,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
            format=format,
            renderer_version=renderer_version(),
        )
        audit(
            auth, "export_requested", job.pk, {"execution_id": str(execution.pk), "format": format}
        )
        return export_data(job)


def export_data(job: ExportJob) -> dict[str, object]:
    return {
        "id": str(job.pk),
        "execution_id": str(job.execution_id),
        "format": job.format,
        "state": job.state,
        "attempt_count": job.attempt_count,
        "error_code": job.last_error_code or None,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "next_attempt_at": job.next_attempt_at.isoformat() if job.state == "retry" else None,
    }


def export_history(actor: User, organization_id: UUID) -> tuple[dict[str, object], ...]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_CREATE_EXPORT
    ) as auth:
        rows = (
            ExportJob.objects.select_related("execution")
            .filter(
                organization_id=auth.organization_id, requested_by_membership_id=auth.membership_id
            )
            .defer("execution__result_snapshot")
            .order_by("-created_at", "id")[:MAX_HISTORY_ROWS]
        )
        result = []
        for row in rows:
            try:
                authorize_selections(
                    auth,
                    stored_selections(row.execution.selection),
                    Capability.ANALYTICS_CREATE_EXPORT,
                )
            except AuthorizationDenied:
                continue
            result.append(export_data(row))
        return tuple(result)


def export_status(actor: User, organization_id: UUID, job_id: UUID) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_CREATE_EXPORT
    ) as auth:
        job = (
            ExportJob.objects.select_related("execution")
            .filter(
                organization_id=auth.organization_id,
                pk=job_id,
                requested_by_membership_id=auth.membership_id,
            )
            .first()
        )
        if job is None:
            raise unavailable("La exportación no está disponible.")
        authorize_selections(
            auth, stored_selections(job.execution.selection), Capability.ANALYTICS_CREATE_EXPORT
        )
        return export_data(job)


def download_export(actor: User, organization_id: UUID, job_id: UUID) -> tuple[bytes, str, str]:
    from pathlib import Path

    from django.conf import settings

    from .exporting import revalidate_execution_scope
    from .storage import LocalAnalyticsStorage, PublishedObject

    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_DOWNLOAD_EXPORT
    ) as auth:
        job = (
            ExportJob.objects.select_related("execution")
            .filter(
                organization_id=auth.organization_id,
                pk=job_id,
                requested_by_membership_id=auth.membership_id,
            )
            .first()
        )
        if job is None:
            raise unavailable("La exportación no está disponible.")
        authorize_selections(
            auth, stored_selections(job.execution.selection), Capability.ANALYTICS_DOWNLOAD_EXPORT
        )
        revalidate_execution_scope(auth, job.execution)
        if job.state != ExportJob.State.COMPLETED:
            raise conflict("export_not_ready", "La exportación todavía no está disponible.")
        artifact = ExportArtifact.objects.filter(
            organization_id=auth.organization_id, job_id=job.pk
        ).first()
        if artifact is None:
            raise unavailable("El artefacto no está disponible.")
        metadata = PublishedObject(
            artifact.object_key, artifact.sha256, artifact.byte_size, artifact.format
        )
        content = LocalAnalyticsStorage(Path(settings.ANALYTICS_STORAGE_ROOT)).read(
            auth.organization_id, artifact.pk, metadata
        )
        audit(
            auth,
            "export_downloaded",
            job.pk,
            {"sha256": metadata.sha256, "byte_size": metadata.byte_size},
        )
        return content, metadata.format, metadata.sha256


def archive_report(
    actor: User, organization_id: UUID, report_id: UUID, *, expected_revision: int, archived: bool
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.ANALYTICS_MANAGE_OWN_REPORT
    ) as auth:
        report = (
            ReportDefinition.objects.select_for_update()
            .filter(organization_id=auth.organization_id, pk=report_id)
            .first()
        )
        if report is None:
            raise unavailable("El reporte no está disponible.")
        revision = ReportRevision.objects.filter(
            organization_id=auth.organization_id,
            report_id=report.pk,
            number=report.current_revision,
        ).first()
        if revision is None:
            raise unavailable("El reporte no está disponible.")
        revision = _authorized_revision(auth, revision.pk, manage=True)
        if report.current_revision != expected_revision:
            raise conflict("stale_revision", "El reporte tiene una revisión más reciente.")
        report.archived = archived
        report.save(update_fields=["archived", "updated_at"])
        revision.report = report
        audit(auth, "report_archived" if archived else "report_restored", report.pk)
        return _report_data(revision)
