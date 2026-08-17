from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

import pytest
from pypdf import PdfWriter

from claridez.documents.config import document_settings
from claridez.documents.domain_assets import (
    download_payment_support,
    download_receipt_pdf,
    receive_payment_support,
)
from claridez.documents.errors import DocumentsError
from claridez.documents.jobs import work_once
from claridez.documents.malware import ScanOutcome, ScanResult
from claridez.documents.models import ContractualInstrument, ContractualRecord
from claridez.documents.rendering import RenderedPDF
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.receivables.models import Receipt, ReceivableObligation, ReceivedPayment
from claridez.receivables.services import issue_receipt_authorized, obligation_balance
from tests.test_receivables import _confirmed, _owner

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_document_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("CLARIDEZ_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
    monkeypatch.setenv(
        "CLARIDEZ_DOCUMENT_TOKEN_HMAC_KEY",
        "test-only-receivables-document-key-with-adequate-length",
    )
    document_settings.cache_clear()
    yield
    document_settings.cache_clear()


def _pdf() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(output)
    return output.getvalue()


class _CleanScanner:
    def scan(self, _stream: BinaryIO) -> ScanOutcome:
        return ScanOutcome(ScanResult.CLEAN, "fake", detail="clean")


def test_payment_support_and_receipt_pdf_reuse_private_document_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, creation, _, _, _, _ = _confirmed("receivables-documents")
    foreign_owner, foreign = _owner("receivables-documents-foreign")
    organization_id = creation.organization.pk
    content = _pdf()
    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_RECORD_PAYMENT
    ) as authorization:
        payment = ReceivedPayment.objects.get()
        file_projection = receive_payment_support(
            authorization,
            payment_id=payment.pk,
            display_name="comprobante.pdf",
            declared_media_type="application/pdf",
            source=io.BytesIO(content),
            correlation_id="p10-payment-support",
        )
        assert file_projection.state == "uploading"
        assert not hasattr(file_projection, "storage_key")

    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_READ
    ) as authorization:
        with pytest.raises(DocumentsError) as unavailable:
            download_payment_support(
                authorization,
                payment_id=payment.pk,
                file_id=file_projection.id,
            )
        assert unavailable.value.code == "file_not_clean"
    with authorized_tenant_scope(
        foreign_owner, foreign.organization.pk, Capability.RECEIVABLES_READ
    ) as authorization:
        with pytest.raises(DocumentsError) as cross_tenant:
            download_payment_support(
                authorization,
                payment_id=payment.pk,
                file_id=file_projection.id,
            )
        assert cross_tenant.value.code == "resource_not_available"

    assert work_once(organization_id, worker_id="p10-document-worker")
    monkeypatch.setattr("claridez.documents.jobs.malware_scanner", lambda: _CleanScanner())
    assert work_once(organization_id, worker_id="p10-document-worker")
    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_READ
    ) as authorization:
        downloaded, media_type, name = download_payment_support(
            authorization,
            payment_id=payment.pk,
            file_id=file_projection.id,
        )
        assert (downloaded, media_type, name) == (
            content,
            "application/pdf",
            "comprobante.pdf",
        )
        obligation = ReceivableObligation.objects.get()
        balance_before_pdf = obligation_balance(obligation)

    rendered = b"%PDF-1.7\n% P10 receipt artifact\n"
    digest = hashlib.sha256(rendered).hexdigest()
    monkeypatch.setattr(
        "claridez.documents.jobs.render_pdf",
        lambda _html: RenderedPDF(
            rendered,
            digest,
            len(rendered),
            "WeasyPrint",
            "69.0",
            "claridez-render-weasyprint-69.0-debian12-v1",
        ),
    )
    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_ISSUE_RECEIPT
    ) as authorization:
        receipt = issue_receipt_authorized(
            authorization, payment_id=payment.pk, idempotency_key=uuid4()
        )
        artifact_id = UUID(str(receipt.document_artifact_id))
        assert "storage_key" not in receipt.snapshot
    assert work_once(organization_id, worker_id="p10-document-worker")
    assert work_once(organization_id, worker_id="p10-document-worker")
    with authorized_tenant_scope(
        owner, organization_id, Capability.RECEIVABLES_READ
    ) as authorization:
        pdf, media_type, filename = download_receipt_pdf(
            authorization,
            receipt_id=receipt.pk,
            artifact_id=artifact_id,
        )
        assert pdf == rendered
        assert media_type == "application/pdf"
        assert filename == f"recibo-{receipt.pk}.pdf"
        assert obligation_balance(ReceivableObligation.objects.get()) == balance_before_pdf
        assert Receipt.objects.count() == 1
        assert ContractualRecord.objects.count() == 0
        assert ContractualInstrument.objects.count() == 0
