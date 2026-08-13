from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, BinaryIO
from uuid import UUID

from claridez.identity.models import User
from claridez.operations.public import has_document_relationship
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.tenant_scope import TenantAuthorization, authorized_tenant_scope

from . import contractual_records, retention, templates
from .artifacts import verify_external_file, verify_generated_artifact
from .errors import forbidden
from .external_access import create_grant, revoke_grant
from .materiality import materiality_policy
from .models import (
    AcceptanceEvidence,
    ContractualRecord,
    DocumentJob,
    DocumentTemplate,
    ExternalAccessGrant,
    ExternalFile,
    GeneratedArtifact,
    LegalHold,
    RetentionAssignment,
    RetentionEvent,
    RetentionPolicy,
)
from .snapshots import build_contractual_snapshot
from .uploads import receive_external_file


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


def document_capabilities(actor: User, organization_id: UUID) -> tuple[str, ...]:
    with authorized_tenant_scope(actor, organization_id, Capability.ORGANIZATION_ACCESS) as auth:
        values = (
            Capability.DOCUMENT_TEMPLATE_READ,
            Capability.DOCUMENT_TEMPLATE_MANAGE,
            Capability.CONTRACTUAL_RECORD_READ,
            Capability.CONTRACTUAL_INSTRUMENT_ISSUE,
            Capability.CONTRACTUAL_ACCEPTANCE_READ,
            Capability.DOCUMENT_ARTIFACT_DOWNLOAD,
            Capability.DOCUMENT_EXTERNAL_FILE_MANAGE,
            Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE,
            Capability.DOCUMENT_RETENTION_READ,
            Capability.DOCUMENT_RETENTION_MANAGE,
        )
        granted = capabilities_for_role(auth.role)
        return tuple(value.value for value in values if value in granted)


def _template_data(row: DocumentTemplate) -> dict[str, Any]:
    return {
        "id": str(row.pk),
        "name": row.name,
        "kind": row.kind,
        "is_active": row.is_active,
        "revision": row.revision,
        "versions": [
            {
                "id": str(version.pk),
                "version": version.version,
                "status": version.status,
                "title": version.title,
                "body_html": version.body_html,
                "variable_schema": version.variable_schema,
                "source_sha256": version.source_sha256,
                "assets_sha256": version.assets_sha256,
                "published_at": (
                    version.published_at.isoformat() if version.published_at else None
                ),
            }
            for version in row.versions.all().order_by("version", "id")
        ],
    }


def list_templates(actor: User, organization_id: UUID) -> list[dict[str, Any]]:
    with authorized_tenant_scope(actor, organization_id, Capability.DOCUMENT_TEMPLATE_READ):
        rows = DocumentTemplate.objects.prefetch_related("versions").order_by("name", "id")
        return [_template_data(row) for row in rows]


def create_template(actor: User, organization_id: UUID, **data: Any) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_TEMPLATE_MANAGE
    ) as auth:
        row, _ = templates.create_template(auth, **data)
        row = DocumentTemplate.objects.prefetch_related("versions").get(pk=row.pk)
        return _template_data(row)


def create_template_version(
    actor: User, organization_id: UUID, *, template_id: UUID, **data: Any
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_TEMPLATE_MANAGE
    ) as auth:
        row = templates.create_draft_version(auth, template_id=template_id, **data)
        return {"id": str(row.pk), "version": row.version, "status": row.status}


def update_template_version(
    actor: User, organization_id: UUID, *, version_id: UUID, **data: Any
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_TEMPLATE_MANAGE
    ) as auth:
        row = templates.update_draft(auth, version_id=version_id, **data)
        return {"id": str(row.pk), "version": row.version, "status": row.status}


def publish_template_version(
    actor: User, organization_id: UUID, *, version_id: UUID
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_TEMPLATE_MANAGE
    ) as auth:
        row = templates.publish_version(auth, version_id)
        return {"id": str(row.pk), "version": row.version, "status": row.status}


def inactivate_template_version(
    actor: User, organization_id: UUID, *, version_id: UUID
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_TEMPLATE_MANAGE
    ) as auth:
        row = templates.inactivate_version(auth, version_id)
        return {"id": str(row.pk), "version": row.version, "status": row.status}


def set_template_active(
    actor: User, organization_id: UUID, *, template_id: UUID, active: bool
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_TEMPLATE_MANAGE
    ) as auth:
        row = templates.set_template_active(auth, template_id, active=active)
        return {"id": str(row.pk), "is_active": row.is_active, "revision": row.revision}


def preview_document(actor: User, organization_id: UUID, **data: Any) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.CONTRACTUAL_INSTRUMENT_ISSUE
    ) as auth:
        auth.require(Capability.SALES_READ)
        return contractual_records.preview(auth, **data)


def _require_record_scope(auth: TenantAuthorization, root_id: UUID) -> None:
    if auth.role == "operations":
        auth.require(Capability.OPERATION_READ)
        if not has_document_relationship(auth.organization_id, root_id):
            raise forbidden("No existe una relación operativa para este expediente.")
    else:
        auth.require(Capability.SALES_READ)


def _record_data(record: ContractualRecord, auth: TenantAuthorization) -> dict[str, Any]:
    granted = capabilities_for_role(auth.role)
    can_read_acceptance = Capability.CONTRACTUAL_ACCEPTANCE_READ in granted
    can_manage_external_access = Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE in granted
    can_manage_external_files = Capability.DOCUMENT_EXTERNAL_FILE_MANAGE in granted
    instruments = []
    for instrument in record.instruments.all().order_by("created_at", "id"):
        versions = []
        for version in instrument.issued_versions.all().order_by("version", "id"):
            artifact = next(
                (item for item in version.artifacts.all() if item.is_emitted_original),
                None,
            )
            acceptance = (
                AcceptanceEvidence.objects.filter(issued_version=version).first()
                if can_read_acceptance
                else None
            )
            grants = (
                ExternalAccessGrant.objects.filter(issued_version=version).order_by(
                    "-created_at", "-id"
                )
                if can_manage_external_access
                else ()
            )
            versions.append(
                {
                    "id": str(version.pk),
                    "version": version.version,
                    "state": version.state,
                    "snapshot_sha256": version.snapshot_sha256,
                    "template_version_id": str(version.template_version_id),
                    "current_reservation_id": str(version.current_reservation_id),
                    "quotation_version_id": str(version.quotation_version_id),
                    "issued_at": version.issued_at.isoformat() if version.issued_at else None,
                    "artifact": (
                        {
                            "id": str(artifact.pk),
                            "sha256": artifact.sha256,
                            "size_bytes": artifact.size_bytes,
                            "media_type": artifact.media_type,
                            "state": artifact.state,
                            "verified_at": (
                                artifact.verified_at.isoformat() if artifact.verified_at else None
                            ),
                        }
                        if artifact
                        else None
                    ),
                    "acceptance": (
                        {
                            "id": str(acceptance.pk),
                            "accepted_at": acceptance.accepted_at.isoformat(),
                            "artifact_sha256": acceptance.artifact_sha256,
                            "mechanism_version": acceptance.mechanism_version,
                        }
                        if acceptance
                        else None
                    ),
                    "grants": [
                        {
                            "id": str(grant.pk),
                            "purpose": grant.purpose,
                            "expires_at": grant.expires_at.isoformat(),
                            "revoked_at": (
                                grant.revoked_at.isoformat() if grant.revoked_at else None
                            ),
                            "exchange_count": grant.exchange_count,
                            "max_exchanges": grant.max_exchanges,
                        }
                        for grant in grants
                    ],
                }
            )
        instruments.append(
            {
                "id": str(instrument.pk),
                "instrument_type": instrument.instrument_type,
                "title": instrument.title,
                "status": instrument.status,
                "versions": versions,
            }
        )
    files = (
        [
            {
                "id": str(row.pk),
                "display_name": row.display_name,
                "media_type": row.detected_media_type,
                "sha256": row.sha256,
                "size_bytes": row.size_bytes,
                "state": row.state,
                "validation_detail": row.validation_detail,
            }
            for row in record.external_files.all().order_by("created_at", "id")
        ]
        if can_manage_external_files
        else []
    )
    latest = (
        record.instruments.filter(issued_versions__isnull=False)
        .values_list("issued_versions__id", flat=True)
        .order_by("-issued_versions__created_at", "-issued_versions__id")
        .first()
    )
    materiality: dict[str, Any] | None = None
    if latest is not None:
        previous = record.instruments.values_list("issued_versions__snapshot", flat=True).get(
            issued_versions__id=latest
        )
        current, current_hash, _, _ = build_contractual_snapshot(
            auth, root_reservation_id=record.root_reservation_id
        )
        assessment = materiality_policy().assess(previous, current)
        materiality = {
            "policy_version": assessment.policy_version,
            "status": assessment.status,
            "changes": list(assessment.changes),
            "requires_new_issue": assessment.requires_new_issue,
            "requires_new_acceptance": assessment.requires_new_acceptance,
            "legal_instrument_outcome": assessment.legal_instrument_outcome,
            "current_snapshot_sha256": current_hash,
        }
    return {
        "status": "contractual_record_exists",
        "id": str(record.pk),
        "root_reservation_id": str(record.root_reservation_id),
        "instruments": instruments,
        "external_files": files,
        "materiality": materiality,
    }


def read_record_state(
    actor: User, organization_id: UUID, *, root_reservation_id: UUID
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.CONTRACTUAL_RECORD_READ
    ) as auth:
        _require_record_scope(auth, root_reservation_id)
        record = (
            ContractualRecord.objects.prefetch_related(
                "instruments__issued_versions__artifacts", "external_files"
            )
            .filter(root_reservation_id=root_reservation_id)
            .first()
        )
        if record is None:
            return {
                "status": "no_contract_issued",
                "label": "sin contrato emitido",
                "root_reservation_id": str(root_reservation_id),
                "instruments": [],
                "external_files": [],
            }
        return _record_data(record, auth)


def create_record(
    actor: User, organization_id: UUID, *, root_reservation_id: UUID
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.CONTRACTUAL_INSTRUMENT_ISSUE
    ) as auth:
        auth.require(Capability.SALES_MANAGE)
        record, created = contractual_records.get_or_create_record(
            auth, root_reservation_id=root_reservation_id
        )
        return {**_record_data(record, auth), "created": created}


def create_instrument(actor: User, organization_id: UUID, **data: Any) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.CONTRACTUAL_INSTRUMENT_ISSUE
    ) as auth:
        auth.require(Capability.SALES_MANAGE)
        record = ContractualRecord.objects.get(pk=data["record_id"])
        _require_record_scope(auth, record.root_reservation_id)
        row = contractual_records.create_instrument(auth, **data)
        return {
            "id": str(row.pk),
            "record_id": str(row.record_id),
            "instrument_type": row.instrument_type,
            "title": row.title,
            "status": row.status,
        }


def issue_instrument(actor: User, organization_id: UUID, **data: Any) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.CONTRACTUAL_INSTRUMENT_ISSUE
    ) as auth:
        auth.require(Capability.SALES_MANAGE)
        row = contractual_records.issue_version(auth, **data)
        return {
            "id": str(row.pk),
            "version": row.version,
            "state": row.state,
            "snapshot_sha256": row.snapshot_sha256,
            "job": {
                "state": DocumentJob.objects.get(
                    job_type=DocumentJob.Type.RENDER_ISSUED_VERSION,
                    target_id=row.pk,
                ).state
            },
        }


def upload_external_file(
    actor: User, organization_id: UUID, *, source: BinaryIO, **data: Any
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_EXTERNAL_FILE_MANAGE
    ) as auth:
        auth.require(Capability.SALES_READ)
        row = receive_external_file(auth, source=source, **data)
        return {
            "id": str(row.pk),
            "display_name": row.display_name,
            "state": row.state,
            "sha256": row.sha256,
            "size_bytes": row.size_bytes,
        }


def create_external_grant(actor: User, organization_id: UUID, **data: Any) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE
    ) as auth:
        auth.require(Capability.SALES_READ)
        secret = create_grant(auth, **data)
        return {
            "id": str(secret.grant.pk),
            "purpose": secret.grant.purpose,
            "expires_at": secret.grant.expires_at.isoformat(),
            "token": secret.token,
        }


def revoke_external_grant(actor: User, organization_id: UUID, *, grant_id: UUID) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE
    ) as auth:
        row = revoke_grant(auth, grant_id=grant_id)
        if row.revoked_at is None:
            raise RuntimeError("revoked grant missing timestamp")
        return {"id": str(row.pk), "revoked_at": row.revoked_at.isoformat()}


def list_retention(actor: User, organization_id: UUID) -> dict[str, Any]:
    with authorized_tenant_scope(actor, organization_id, Capability.DOCUMENT_RETENTION_READ):
        return {
            "policies": [
                {
                    "id": str(row.pk),
                    "key": row.key,
                    "version": row.version,
                    "name": row.name,
                    "classification": row.classification,
                    "status": row.status,
                    "rules": row.rules,
                }
                for row in RetentionPolicy.objects.order_by("key", "version", "id")
            ],
            "assignments": [
                {
                    "id": str(row.pk),
                    "policy_id": str(row.policy_id),
                    "target_type": row.target_type,
                    "target_id": str(row.target_id),
                    "state": row.state,
                    "eligible_at": row.eligible_at.isoformat() if row.eligible_at else None,
                }
                for row in RetentionAssignment.objects.order_by("created_at", "id")
            ],
            "holds": [
                {
                    "id": str(row.pk),
                    "assignment_id": str(row.assignment_id),
                    "reason": row.reason,
                    "placed_at": row.placed_at.isoformat(),
                    "released_at": row.released_at.isoformat() if row.released_at else None,
                    "release_reason": row.release_reason,
                }
                for row in LegalHold.objects.order_by("-placed_at", "id")
            ],
            "events": [
                {
                    "id": str(row.pk),
                    "assignment_id": str(row.assignment_id),
                    "kind": row.kind,
                    "evidence": row.evidence,
                    "occurred_at": row.occurred_at.isoformat(),
                }
                for row in RetentionEvent.objects.order_by("-occurred_at", "id")
            ],
        }


def create_retention_policy(actor: User, organization_id: UUID, **data: Any) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_RETENTION_MANAGE
    ) as auth:
        row = retention.create_policy(auth, **data)
        return {"id": str(row.pk), "status": row.status}


def activate_retention_policy(
    actor: User, organization_id: UUID, *, policy_id: UUID
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_RETENTION_MANAGE
    ) as auth:
        row = retention.activate_policy(auth, policy_id=policy_id)
        if row.approved_at is None:
            raise RuntimeError("active retention policy missing timestamp")
        return {"id": str(row.pk), "status": row.status, "approved_at": row.approved_at.isoformat()}


def assign_retention_policy(actor: User, organization_id: UUID, **data: Any) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_RETENTION_MANAGE
    ) as auth:
        row = retention.assign_policy(auth, **data)
        return {"id": str(row.pk), "state": row.state}


def evaluate_retention_eligibility(
    actor: User, organization_id: UUID, *, assignment_id: UUID, **data: Any
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_RETENTION_MANAGE
    ) as auth:
        row = retention.evaluate_eligibility(auth, assignment_id=assignment_id, **data)
        return {
            "id": str(row.pk),
            "state": row.state,
            "eligible_at": row.eligible_at.isoformat() if row.eligible_at else None,
            "physical_disposition": "not_implemented",
        }


def place_legal_hold(actor: User, organization_id: UUID, **data: Any) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_RETENTION_MANAGE
    ) as auth:
        row = retention.place_hold(auth, **data)
        return {"id": str(row.pk), "placed_at": row.placed_at.isoformat()}


def release_legal_hold(actor: User, organization_id: UUID, **data: Any) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_RETENTION_MANAGE
    ) as auth:
        row = retention.release_hold(auth, **data)
        if row.released_at is None:
            raise RuntimeError("released legal hold missing timestamp")
        return {"id": str(row.pk), "released_at": row.released_at.isoformat()}


def download_artifact(
    actor: User, organization_id: UUID, *, artifact_id: UUID
) -> tuple[bytes, str, str]:
    result = None
    media_type = ""
    filename = ""
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_ARTIFACT_DOWNLOAD
    ) as auth:
        artifact = GeneratedArtifact.objects.select_related(
            "issued_version__instrument__record"
        ).get(pk=artifact_id)
        _require_record_scope(auth, artifact.issued_version.instrument.record.root_reservation_id)
        if artifact.state != GeneratedArtifact.State.AVAILABLE:
            raise forbidden("El artefacto no está disponible.")
        result = verify_generated_artifact(artifact)
        media_type = artifact.media_type
        filename = f"documento-{artifact.pk}.pdf"
    if result is None or result.content is None:
        raise forbidden("La entrega se bloqueó por una falla de integridad.")
    return result.content, media_type, filename


def download_external_file(
    actor: User, organization_id: UUID, *, external_file_id: UUID
) -> tuple[bytes, str, str]:
    result = None
    media_type = ""
    filename = ""
    with authorized_tenant_scope(
        actor, organization_id, Capability.DOCUMENT_EXTERNAL_FILE_MANAGE
    ) as auth:
        auth.require(Capability.SALES_READ)
        row = ExternalFile.objects.get(pk=external_file_id)
        if row.state != ExternalFile.State.CLEAN:
            raise forbidden("El archivo externo aún no es seguro para entrega.")
        result = verify_external_file(row)
        media_type = row.detected_media_type
        filename = row.display_name
    if result is None or result.content is None:
        raise forbidden("La entrega se bloqueó por una falla de integridad.")
    return result.content, media_type, filename
