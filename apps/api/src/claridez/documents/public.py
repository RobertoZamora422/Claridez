"""Puerto público estrecho e inmutable del estado documental."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from claridez.organizations.capabilities import Capability
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
from .models import (
    AcceptanceEvidence,
    ContractualRecord,
    GeneratedArtifact,
    IssuedInstrumentVersion,
)


@dataclass(frozen=True, slots=True)
class PortalDocumentAuthorization:
    organization_id: UUID
    event_request_id: UUID
    principal_reference: UUID
    grant_reference: UUID
    action: str


@dataclass(frozen=True, slots=True)
class PortalDocumentProjection:
    issued_version_id: UUID
    artifact_id: UUID
    title: str
    instrument_type: str
    version: int
    issued_at: datetime | None
    artifact_sha256: str
    size_bytes: int
    media_type: str
    is_current: bool
    accepted_at: datetime | None
    acceptance_manifestation_text: str
    acceptance_manifestation_version: str


@dataclass(frozen=True, slots=True)
class DocumentReminderDecision:
    issued_version_id: UUID
    instrument_id: UUID
    root_reservation_id: UUID
    source_version: int


def document_reminder_decision(
    authorization: TenantAuthorization, issued_version_id: UUID
) -> DocumentReminderDecision:
    """Decide desde Documents si una versión emitida vigente sigue pendiente de aceptación."""
    authorization.require(Capability.DOCUMENT_EXTERNAL_ACCESS_MANAGE)
    try:
        row = IssuedInstrumentVersion.objects.select_related(
            "instrument", "instrument__record"
        ).get(
            organization_id=authorization.organization_id,
            pk=issued_version_id,
            state=IssuedInstrumentVersion.State.ISSUED,
        )
    except IssuedInstrumentVersion.DoesNotExist:
        raise DocumentsPortError(
            "reminder_not_applicable",
            "La versión documental no admite recordatorio.",
            status_code=409,
        ) from None
    current_version = (
        IssuedInstrumentVersion.objects.filter(
            organization_id=authorization.organization_id,
            instrument=row.instrument,
            state=IssuedInstrumentVersion.State.ISSUED,
        )
        .order_by("-version", "-id")
        .first()
    )
    accepted = AcceptanceEvidence.objects.filter(
        organization_id=authorization.organization_id,
        issued_version=row,
    ).exists()
    if current_version is None or current_version.pk != row.pk or accepted:
        raise DocumentsPortError(
            "reminder_not_applicable",
            "La versión documental ya no está pendiente.",
            status_code=409,
        )
    return DocumentReminderDecision(
        issued_version_id=row.pk,
        instrument_id=row.instrument_id,
        root_reservation_id=row.instrument.record.root_reservation_id,
        source_version=row.version,
    )


def _portal_record(authorization: PortalDocumentAuthorization) -> ContractualRecord | None:
    from claridez.scheduling.public import client_schedule

    schedule = client_schedule(authorization.organization_id, authorization.event_request_id)
    if schedule is None:
        return None
    return ContractualRecord.objects.filter(
        organization_id=authorization.organization_id,
        root_reservation_id=schedule.root_reservation_id,
    ).first()


def portal_documents(
    authorization: PortalDocumentAuthorization,
) -> tuple[PortalDocumentProjection, ...]:
    if authorization.action != "read":
        raise DocumentsPortError("forbidden", "La autorización documental no es válida.")
    record = _portal_record(authorization)
    if record is None:
        return ()
    versions = list(
        IssuedInstrumentVersion.objects.select_related("instrument", "template_version")
        .filter(
            organization_id=authorization.organization_id,
            instrument__record=record,
            state=IssuedInstrumentVersion.State.ISSUED,
        )
        .order_by("instrument_id", "version", "id")
    )
    current_by_instrument: dict[UUID, int] = {}
    for version in versions:
        current_by_instrument[version.instrument_id] = max(
            current_by_instrument.get(version.instrument_id, 0), version.version
        )
    from .acceptance import MANIFESTATION_TEXT, MANIFESTATION_VERSION

    result: list[PortalDocumentProjection] = []
    for version in versions:
        artifact = GeneratedArtifact.objects.filter(
            organization_id=authorization.organization_id,
            issued_version=version,
            is_emitted_original=True,
            state=GeneratedArtifact.State.AVAILABLE,
            verified_at__isnull=False,
        ).first()
        if artifact is None:
            continue
        acceptance = (
            AcceptanceEvidence.objects.filter(
                organization_id=authorization.organization_id,
                issued_version=version,
                artifact=artifact,
            )
            .order_by("accepted_at", "id")
            .first()
        )
        result.append(
            PortalDocumentProjection(
                issued_version_id=version.pk,
                artifact_id=artifact.pk,
                title=version.template_version.title,
                instrument_type=version.instrument.instrument_type,
                version=version.version,
                issued_at=version.issued_at,
                artifact_sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                media_type=artifact.media_type,
                is_current=current_by_instrument[version.instrument_id] == version.version,
                accepted_at=acceptance.accepted_at if acceptance else None,
                acceptance_manifestation_text=MANIFESTATION_TEXT,
                acceptance_manifestation_version=MANIFESTATION_VERSION,
            )
        )
    return tuple(result)


def download_portal_document(
    authorization: PortalDocumentAuthorization,
    *,
    issued_version_id: UUID,
    artifact_id: UUID,
    expected_sha256: str,
) -> tuple[bytes, str, str]:
    if authorization.action != "download":
        raise DocumentsPortError("forbidden", "La autorización documental no es válida.")
    readable = portal_documents(
        PortalDocumentAuthorization(
            organization_id=authorization.organization_id,
            event_request_id=authorization.event_request_id,
            principal_reference=authorization.principal_reference,
            grant_reference=authorization.grant_reference,
            action="read",
        )
    )
    if not any(
        item.issued_version_id == issued_version_id
        and item.artifact_id == artifact_id
        and item.artifact_sha256 == expected_sha256
        for item in readable
    ):
        raise DocumentsPortError("not_found", "El documento no está disponible.", status_code=404)
    from .artifacts import verify_generated_artifact

    artifact = GeneratedArtifact.objects.get(
        organization_id=authorization.organization_id, pk=artifact_id
    )
    verified = verify_generated_artifact(artifact)
    if not verified.verified or verified.content is None:
        raise DocumentsPortError("integrity_failed", "La entrega fue bloqueada.", status_code=409)
    return verified.content, artifact.media_type, f"documento-{artifact.pk}.pdf"


def accept_portal_document(
    authorization: PortalDocumentAuthorization,
    *,
    issued_version_id: UUID,
    artifact_id: UUID,
    expected_sha256: str,
    manifestation_text: str,
    manifestation_version: str,
    idempotency_key: UUID,
    timezone_name: str,
    request_id: str,
    correlation_id: str,
    ip_address: str | None,
    user_agent: str | None,
) -> AcceptanceEvidence:
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from .acceptance import MANIFESTATION_TEXT, MANIFESTATION_VERSION
    from .config import document_settings

    if authorization.action != "accept":
        raise DocumentsPortError("forbidden", "La autorización documental no es válida.")
    current = portal_documents(
        PortalDocumentAuthorization(
            organization_id=authorization.organization_id,
            event_request_id=authorization.event_request_id,
            principal_reference=authorization.principal_reference,
            grant_reference=authorization.grant_reference,
            action="read",
        )
    )
    selected = next(
        (
            item
            for item in current
            if item.issued_version_id == issued_version_id
            and item.artifact_id == artifact_id
            and item.artifact_sha256 == expected_sha256
        ),
        None,
    )
    if selected is None or not selected.is_current:
        raise DocumentsPortError("not_found", "El documento no está disponible.", status_code=404)
    if manifestation_text != MANIFESTATION_TEXT or manifestation_version != MANIFESTATION_VERSION:
        raise DocumentsPortError("invalid_manifestation", "La manifestación no coincide.")
    collection_policy = document_settings()
    try:
        with transaction.atomic():
            IssuedInstrumentVersion.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                pk=issued_version_id,
            )
            existing_acceptance = (
                AcceptanceEvidence.objects.filter(
                    organization_id=authorization.organization_id,
                    issued_version_id=issued_version_id,
                    artifact_id=artifact_id,
                )
                .order_by("accepted_at", "id")
                .first()
            )
            if existing_acceptance is not None:
                return existing_acceptance
            return AcceptanceEvidence.objects.create(
                organization_id=authorization.organization_id,
                challenge=None,
                provenance=AcceptanceEvidence.Provenance.PORTAL_SESSION,
                portal_principal_reference=authorization.principal_reference,
                portal_grant_reference=authorization.grant_reference,
                portal_idempotency_key=idempotency_key,
                issued_version_id=issued_version_id,
                artifact_id=artifact_id,
                artifact_sha256=expected_sha256,
                manifestation_text=manifestation_text,
                manifestation_version=manifestation_version,
                acceptor_projection={"principal_reference": str(authorization.principal_reference)},
                attribution_method="portal_contact_control",
                authentication_result={"portal_session": True},
                mechanism_version="portal-p14-v1",
                accepted_at=timezone.now(),
                timezone_name=timezone_name,
                ip_address=(
                    ip_address if collection_policy.capture_acceptance_ip_address else None
                ),
                user_agent=(
                    user_agent[:500]
                    if collection_policy.capture_acceptance_user_agent and user_agent
                    else None
                ),
                request_id=request_id[:128],
                correlation_id=correlation_id[:128],
            )
    except IntegrityError:
        existing = AcceptanceEvidence.objects.filter(
            organization_id=authorization.organization_id,
            portal_idempotency_key=idempotency_key,
        ).first()
        if (
            existing
            and existing.issued_version_id == issued_version_id
            and existing.artifact_id == artifact_id
        ):
            return existing
        raise DocumentsPortError(
            "idempotency_conflict", "La clave ya fue utilizada.", status_code=409
        ) from None


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
    "DocumentReminderDecision",
    "PortalDocumentAuthorization",
    "PortalDocumentProjection",
    "DocumentsPortError",
    "GeneratedArtifactProjection",
    "PrivateFileProjection",
    "documentary_status",
    "document_reminder_decision",
    "download_payment_support",
    "download_operational_evidence",
    "download_receipt_pdf",
    "list_payment_supports",
    "list_operational_evidence",
    "receipt_pdf_status",
    "receive_payment_support",
    "receive_operational_evidence",
    "request_receipt_pdf",
    "portal_documents",
    "download_portal_document",
    "accept_portal_document",
)
