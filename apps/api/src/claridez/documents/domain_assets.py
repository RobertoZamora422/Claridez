"""Plataforma binaria privada para dominios no contractuales."""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import dataclass
from typing import BinaryIO
from uuid import UUID

from django.db import transaction

from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import TenantAuthorization

from .config import document_settings
from .errors import DocumentsError
from .external_files import buffered_upload, inspect_upload
from .models import DocumentJob, GeneratedDomainArtifact, PrivateDomainFile
from .storage import opaque_object_key, private_storage, stream_sha256

RECEIVABLES_DOMAIN = "receivables"
PAYMENT_SUPPORT_PURPOSE = "payment_support"
RECEIPT_PDF_PURPOSE = "receipt_pdf"


@dataclass(frozen=True, slots=True)
class PrivateFileProjection:
    id: UUID
    owner_id: UUID
    purpose: str
    display_name: str
    media_type: str
    sha256: str
    size_bytes: int
    state: str


@dataclass(frozen=True, slots=True)
class GeneratedArtifactProjection:
    id: UUID
    owner_id: UUID
    purpose: str
    media_type: str
    sha256: str
    size_bytes: int | None
    state: str


def _file_projection(row: PrivateDomainFile) -> PrivateFileProjection:
    return PrivateFileProjection(
        id=row.pk,
        owner_id=row.owner_id,
        purpose=row.purpose,
        display_name=row.display_name,
        media_type=row.detected_media_type,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        state=row.state,
    )


def _artifact_projection(row: GeneratedDomainArtifact) -> GeneratedArtifactProjection:
    return GeneratedArtifactProjection(
        id=row.pk,
        owner_id=row.owner_id,
        purpose=row.purpose,
        media_type=row.media_type,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        state=row.state,
    )


def receive_payment_support(
    authorization: TenantAuthorization,
    *,
    payment_id: UUID,
    display_name: str,
    declared_media_type: str,
    source: BinaryIO,
    correlation_id: str,
) -> PrivateFileProjection:
    authorization.require(Capability.RECEIVABLES_RECORD_PAYMENT)
    buffered = buffered_upload(source, max_bytes=document_settings().max_upload_bytes)
    validated = inspect_upload(
        display_name=display_name,
        declared_media_type=declared_media_type,
        stream=buffered,
    )
    size, digest = stream_sha256(buffered)
    key = opaque_object_key("quarantine")
    with transaction.atomic():
        row = PrivateDomainFile.objects.create(
            organization_id=authorization.organization_id,
            owner_domain=RECEIVABLES_DOMAIN,
            owner_id=payment_id,
            purpose=PAYMENT_SUPPORT_PURPOSE,
            display_name=validated.display_name,
            storage_key=key,
            declared_media_type=declared_media_type,
            detected_media_type=validated.media_type,
            extension=validated.extension,
            sha256=digest,
            size_bytes=size,
            state=PrivateDomainFile.State.UPLOADING,
            uploaded_by_membership_id=authorization.membership_id,
        )
        from .jobs import enqueue_job

        enqueue_job(
            organization_id=authorization.organization_id,
            job_type=DocumentJob.Type.FINALIZE_DOMAIN_UPLOAD,
            target_id=row.pk,
            idempotency_key=f"finalize-domain-upload:{row.pk}",
            correlation_id=correlation_id[:128],
        )
    private_storage().put(
        key=key,
        stream=buffered,
        size_bytes=size,
        sha256=digest,
        media_type=validated.media_type,
    )
    return _file_projection(row)


def list_payment_supports(
    authorization: TenantAuthorization, payment_id: UUID
) -> tuple[PrivateFileProjection, ...]:
    authorization.require(Capability.RECEIVABLES_READ)
    return tuple(
        _file_projection(row)
        for row in PrivateDomainFile.objects.filter(
            organization_id=authorization.organization_id,
            owner_domain=RECEIVABLES_DOMAIN,
            owner_id=payment_id,
            purpose=PAYMENT_SUPPORT_PURPOSE,
        ).order_by("created_at", "id")
    )


def request_receipt_pdf(
    authorization: TenantAuthorization,
    *,
    receipt_id: UUID,
    snapshot: dict[str, object],
    correlation_id: str,
) -> GeneratedArtifactProjection:
    authorization.require(Capability.RECEIVABLES_ISSUE_RECEIPT)
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    payment_value = snapshot.get("payment")
    organization_value = snapshot.get("organization")
    applications_value = snapshot.get("applications")
    payment = payment_value if isinstance(payment_value, dict) else {}
    organization = organization_value if isinstance(organization_value, dict) else {}
    applications = applications_value if isinstance(applications_value, list) else []
    rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(str(item.get("obligation_id", ""))),
            html.escape(str(item.get("amount", ""))),
            html.escape(str(payment.get("currency", ""))),
        )
        for item in applications
        if isinstance(item, dict)
    )
    rendered_html = (
        "<main><h1>Recibo/comprobante de cobro — no factura</h1>"
        f"<p><strong>{html.escape(str(organization.get('name', 'Claridez')))}</strong></p>"
        f"<p>Pago: {html.escape(str(payment.get('id', '')))}</p>"
        f"<p>Importe recibido: {html.escape(str(payment.get('amount', '')))} "
        f"{html.escape(str(payment.get('currency', '')))}</p>"
        f"<p>Fecha reportada: {html.escape(str(payment.get('reported_at', '')))}</p>"
        "<table><thead><tr><th>Obligación</th><th>Aplicado</th><th>Moneda</th></tr>"
        f"</thead><tbody>{rows}</tbody></table>"
        "<p>Este comprobante no es factura ni documento tributario.</p></main>"
    )
    with transaction.atomic():
        row, _ = GeneratedDomainArtifact.objects.get_or_create(
            organization_id=authorization.organization_id,
            owner_domain=RECEIVABLES_DOMAIN,
            owner_id=receipt_id,
            purpose=RECEIPT_PDF_PURPOSE,
            defaults={
                "source_snapshot_sha256": digest,
                "render_payload": {"html": rendered_html},
            },
        )
        if row.source_snapshot_sha256 != digest:
            raise DocumentsError(
                "artifact_source_conflict",
                "El recibo ya posee una solicitud documental con otra fuente.",
                status_code=409,
            )
        from .jobs import enqueue_job

        enqueue_job(
            organization_id=authorization.organization_id,
            job_type=DocumentJob.Type.RENDER_DOMAIN_ARTIFACT,
            target_id=row.pk,
            idempotency_key=f"render-domain-artifact:{row.pk}",
            correlation_id=correlation_id[:128],
        )
    return _artifact_projection(row)


def receipt_pdf_status(
    authorization: TenantAuthorization, artifact_id: UUID
) -> GeneratedArtifactProjection:
    authorization.require(Capability.RECEIVABLES_READ)
    try:
        row = GeneratedDomainArtifact.objects.get(
            organization_id=authorization.organization_id,
            pk=artifact_id,
            owner_domain=RECEIVABLES_DOMAIN,
            purpose=RECEIPT_PDF_PURPOSE,
        )
    except GeneratedDomainArtifact.DoesNotExist:
        raise DocumentsError(
            "resource_not_available", "El artefacto no está disponible.", status_code=404
        ) from None
    return _artifact_projection(row)


def _verified_content(*, key: str, expected_sha256: str, expected_size: int) -> bytes:
    try:
        with private_storage().open(key) as stream:
            content = stream.read()
    except DocumentsError:
        raise
    if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_sha256:
        raise DocumentsError(
            "integrity_mismatch", "La integridad del archivo no coincide.", status_code=409
        )
    return content


def download_payment_support(
    authorization: TenantAuthorization, *, payment_id: UUID, file_id: UUID
) -> tuple[bytes, str, str]:
    authorization.require(Capability.RECEIVABLES_READ)
    try:
        row = PrivateDomainFile.objects.get(
            organization_id=authorization.organization_id,
            pk=file_id,
            owner_domain=RECEIVABLES_DOMAIN,
            owner_id=payment_id,
            purpose=PAYMENT_SUPPORT_PURPOSE,
        )
    except PrivateDomainFile.DoesNotExist:
        raise DocumentsError(
            "resource_not_available", "El archivo no está disponible.", status_code=404
        ) from None
    if row.state != PrivateDomainFile.State.CLEAN:
        raise DocumentsError(
            "file_not_clean", "El archivo todavía no es seguro para entrega.", status_code=409
        )
    return (
        _verified_content(
            key=row.storage_key, expected_sha256=row.sha256, expected_size=row.size_bytes
        ),
        row.detected_media_type,
        row.display_name,
    )


def download_receipt_pdf(
    authorization: TenantAuthorization, *, receipt_id: UUID, artifact_id: UUID
) -> tuple[bytes, str, str]:
    authorization.require(Capability.RECEIVABLES_READ)
    try:
        row = GeneratedDomainArtifact.objects.get(
            organization_id=authorization.organization_id,
            pk=artifact_id,
            owner_domain=RECEIVABLES_DOMAIN,
            owner_id=receipt_id,
            purpose=RECEIPT_PDF_PURPOSE,
        )
    except GeneratedDomainArtifact.DoesNotExist:
        raise DocumentsError(
            "resource_not_available", "El PDF no está disponible.", status_code=404
        ) from None
    if (
        row.state != GeneratedDomainArtifact.State.AVAILABLE
        or row.storage_key is None
        or row.size_bytes is None
    ):
        raise DocumentsError(
            "artifact_not_available", "El PDF aún no está disponible.", status_code=409
        )
    return (
        _verified_content(
            key=row.storage_key, expected_sha256=row.sha256, expected_size=row.size_bytes
        ),
        row.media_type,
        f"recibo-{receipt_id}.pdf",
    )
