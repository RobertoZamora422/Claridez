"""Puerto público estrecho e inmutable del estado documental."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from claridez.organizations.tenant_scope import TenantAuthorization

from .domain_assets import (
    GeneratedArtifactProjection,
    PrivateFileProjection,
    download_operational_evidence,
    download_payment_support,
    download_receipt_pdf,
    list_operational_evidence,
    list_payment_supports,
    receipt_pdf_status,
    receive_operational_evidence,
    receive_payment_support,
    request_receipt_pdf,
)
from .errors import DocumentsError as DocumentsPortError
from .models import AcceptanceEvidence, ContractualRecord, GeneratedArtifact


@dataclass(frozen=True, slots=True)
class DocumentaryStatusProjection:
    root_reservation_id: UUID
    contractual_record_id: UUID | None
    instrument_count: int
    latest_issued_version_id: UUID | None
    latest_artifact_sha256: str | None
    latest_acceptance_at: datetime | None
    label: str


def documentary_status(
    authorization: TenantAuthorization, root_reservation_id: UUID
) -> DocumentaryStatusProjection:
    record = ContractualRecord.objects.filter(
        organization_id=authorization.organization_id,
        root_reservation_id=root_reservation_id,
    ).first()
    if record is None:
        return DocumentaryStatusProjection(
            root_reservation_id=root_reservation_id,
            contractual_record_id=None,
            instrument_count=0,
            latest_issued_version_id=None,
            latest_artifact_sha256=None,
            latest_acceptance_at=None,
            label="sin contrato emitido",
        )
    artifact = (
        GeneratedArtifact.objects.filter(
            organization_id=authorization.organization_id,
            issued_version__instrument__record=record,
            is_emitted_original=True,
        )
        .select_related("issued_version")
        .order_by("-created_at", "-id")
        .first()
    )
    acceptance = (
        AcceptanceEvidence.objects.filter(
            organization_id=authorization.organization_id,
            issued_version__instrument__record=record,
        )
        .order_by("-accepted_at", "-id")
        .first()
    )
    return DocumentaryStatusProjection(
        root_reservation_id=root_reservation_id,
        contractual_record_id=record.pk,
        instrument_count=record.instruments.count(),
        latest_issued_version_id=artifact.issued_version_id if artifact else None,
        latest_artifact_sha256=artifact.sha256 if artifact else None,
        latest_acceptance_at=acceptance.accepted_at if acceptance else None,
        label="expediente contractual",
    )


__all__ = (
    "DocumentaryStatusProjection",
    "DocumentsPortError",
    "GeneratedArtifactProjection",
    "PrivateFileProjection",
    "documentary_status",
    "download_payment_support",
    "download_operational_evidence",
    "download_receipt_pdf",
    "list_payment_supports",
    "list_operational_evidence",
    "receipt_pdf_status",
    "receive_payment_support",
    "receive_operational_evidence",
    "request_receipt_pdf",
)
