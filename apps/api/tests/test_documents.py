from __future__ import annotations

import hashlib
import io
import socket
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Lock
from typing import Any, BinaryIO, cast
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from django.utils import timezone
from pypdf import PdfWriter

from claridez.commercial.services import confirm_reservation
from claridez.documents.acceptance import (
    MANIFESTATION_VERSION,
    AcceptanceRequestEvidence,
    accept,
)
from claridez.documents.config import REPOSITORY_ROOT, document_settings
from claridez.documents.errors import DocumentsError
from claridez.documents.external_access import create_acceptance_challenge, exchange_grant
from claridez.documents.external_files import validate_upload
from claridez.documents.jobs import work_once
from claridez.documents.malware import ClamDScanner, ScanOutcome, ScanResult
from claridez.documents.materiality import ExplicitReviewPolicy
from claridez.documents.models import (
    AcceptanceEvidence,
    DocumentJob,
    DocumentJobAttempt,
    ExternalAccessEvent,
    ExternalFile,
    GeneratedArtifact,
    IssuedInstrumentVersion,
    MalwareScanAttempt,
    RetentionEvent,
)
from claridez.documents.rendering import (
    MAX_RENDER_PAGES,
    RenderedPDF,
    render_pdf,
    validate_rendered_pdf,
)
from claridez.documents.services import (
    activate_retention_policy,
    assign_retention_policy,
    create_external_grant,
    create_instrument,
    create_record,
    create_retention_policy,
    create_template,
    evaluate_retention_eligibility,
    issue_instrument,
    place_legal_hold,
    preview_document,
    publish_template_version,
    read_record_state,
    release_legal_hold,
    revoke_external_grant,
    upload_external_file,
)
from claridez.documents.storage import (
    FilesystemPrivateStorage,
    PrivateObjectStorage,
    S3PrivateStorage,
    bytes_stream,
    opaque_evidence_key,
    private_storage,
)
from claridez.documents.variables import (
    VariableDeclaration,
    resolve_template,
    sanitize_template_html,
    validate_variable_schema,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.models import Membership
from claridez.organizations.services import add_membership
from claridez.organizations.tenant_scope import authorized_tenant_scope
from tests.document_fixtures import DocumentCase, build_document_case

pytestmark = pytest.mark.django_db

BODY = (
    "<h1>{{ organization.name }}</h1>"
    "<p>{{ counterparty.full_name }}</p>"
    "{{ quotation.lines_table }}"
    "<p>{{ quotation.currency }} {{ quotation.total }}</p>"
)
SCHEMA = {
    "version": "claridez-vars-v1",
    "variables": [
        {"name": "organization.name", "required": True},
        {"name": "counterparty.full_name", "required": True},
        {"name": "quotation.lines_table", "required": True},
        {"name": "quotation.currency", "required": True},
        {"name": "quotation.total", "required": True},
    ],
}


@pytest.fixture(autouse=True)
def isolated_document_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("CLARIDEZ_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
    monkeypatch.setenv(
        "CLARIDEZ_DOCUMENT_TOKEN_HMAC_KEY", "test-only-document-hmac-key-with-adequate-length"
    )
    document_settings.cache_clear()
    yield
    document_settings.cache_clear()


def test_record_read_requires_document_capability_source_capability_and_real_relationship(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_document_case("document-conjunctive-auth")
    root_id = UUID(str(case.reservation["root_id"]))
    confirm_reservation(
        case.owner,
        case.organization_id,
        reservation_id=case.reservation["id"],
        kind="external_deposit",
        recognized_amount=Decimal("100.00"),
        reported_at=timezone.now(),
        reference="Comprobante sintético",
    )
    operations_user = User.objects.create_user(
        email=f"operations-{uuid4()}@example.test",
        password="Test-only-Password-2026!",
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    add_membership(
        organization_id=case.organization_id,
        user_id=operations_user.pk,
        role=Membership.Role.OPERATIONS,
    )
    assert (
        read_record_state(
            operations_user,
            case.organization_id,
            root_reservation_id=root_id,
        )["status"]
        == "no_contract_issued"
    )

    monkeypatch.setattr(
        "claridez.documents.services.has_document_relationship",
        lambda _organization_id, _root_id: False,
    )
    with pytest.raises(DocumentsError, match="relaci.n operativa") as denied_relation:
        read_record_state(
            operations_user,
            case.organization_id,
            root_reservation_id=root_id,
        )
    assert denied_relation.value.code == "forbidden"

    finance_user = User.objects.create_user(
        email=f"finance-{uuid4()}@example.test",
        password="Test-only-Password-2026!",
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    add_membership(
        organization_id=case.organization_id,
        user_id=finance_user.pk,
        role=Membership.Role.FINANCE,
    )
    with pytest.raises(AuthorizationDenied):
        read_record_state(
            finance_user,
            case.organization_id,
            root_reservation_id=root_id,
        )


def _published_template(case: DocumentCase) -> tuple[str, str]:
    owner = case.owner
    organization_id = case.organization_id
    template = create_template(
        owner,
        organization_id,
        name="Contrato de evento",
        title="Contrato de prestación de servicios",
        body_html=BODY,
        variable_schema=SCHEMA,
    )
    version_id = template["versions"][0]["id"]
    publish_template_version(owner, organization_id, version_id=UUID(version_id))
    return template["id"], version_id


def _pdf() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(output)
    return output.getvalue()


def test_relative_storage_root_is_shared_from_repository_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLARIDEZ_DOCUMENT_STORAGE_ROOT", ".runtime/test-documents")
    document_settings.cache_clear()

    expected_root = (REPOSITORY_ROOT / ".runtime/test-documents").resolve()
    assert document_settings().storage_root == expected_root


def test_closed_template_language_fails_closed() -> None:
    declarations = validate_variable_schema(SCHEMA, BODY)
    assert len(declarations) == 5
    with pytest.raises(DocumentsError, match="no está permitido"):
        sanitize_template_html('<img src="file:///etc/passwd">')
    with pytest.raises(DocumentsError):
        sanitize_template_html("<script>alert(1)</script>")
    with pytest.raises(DocumentsError, match="desconocida"):
        validate_variable_schema(
            {
                "version": "claridez-vars-v1",
                "variables": [{"name": "organization.__class__", "required": True}],
            },
            "<p>{{ organization.__class__ }}</p>",
        )
    with pytest.raises(DocumentsError) as missing:
        resolve_template(
            body_html="<p>{{ counterparty.email }}</p>",
            declarations=(VariableDeclaration("counterparty.email", True, None),),
            values={"counterparty.email": None},
        )
    assert missing.value.code == "missing_required_variable"


def test_private_filesystem_is_opaque_integrity_checked_and_non_overwriting(tmp_path: Path) -> None:
    storage = FilesystemPrivateStorage(tmp_path / "objects")
    content = b"private evidence"
    digest = hashlib.sha256(content).hexdigest()
    stored = storage.put(
        key="generated/aa/bbcc",
        stream=bytes_stream(content),
        size_bytes=len(content),
        sha256=digest,
        media_type="application/pdf",
    )
    assert stored.sha256 == digest
    with storage.open(stored.key) as stream:
        assert stream.read() == content
    with pytest.raises(DocumentsError, match="sobrescribirse"):
        storage.put(
            key=stored.key,
            stream=bytes_stream(content),
            size_bytes=len(content),
            sha256=digest,
            media_type="application/pdf",
        )
    with pytest.raises(DocumentsError):
        storage.open("../escape")


def test_s3_adapter_requests_own_checksum_encryption_and_conditional_create() -> None:
    class Client:
        parameters: dict[str, object] | None = None

        def put_object(self, **parameters: object) -> None:
            self.parameters = parameters

    content = b"immutable artifact"
    digest = hashlib.sha256(content).hexdigest()
    storage = object.__new__(S3PrivateStorage)
    storage.bucket = "private-documents"
    storage.sse = "AES256"
    storage.kms_key = None
    client = Client()
    storage.client = client
    storage.put(
        key="generated/ab/opaque",
        stream=io.BytesIO(content),
        size_bytes=len(content),
        sha256=digest,
        media_type="application/pdf",
    )
    assert client.parameters is not None
    assert client.parameters["IfNoneMatch"] == "*"
    assert client.parameters["ServerSideEncryption"] == "AES256"
    assert client.parameters["Metadata"] == {"claridez-sha256": digest}
    assert client.parameters["ChecksumSHA256"]


def _race_storage_writes(storage: PrivateObjectStorage, key: str) -> tuple[list[str], bytes]:
    barrier = Barrier(2)
    payloads = (b"first immutable payload", b"second immutable payload")

    def write(content: bytes) -> str:
        barrier.wait(timeout=10)
        try:
            storage.put(
                key=key,
                stream=io.BytesIO(content),
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                media_type="application/pdf",
            )
        except DocumentsError as error:
            return error.code
        return "stored"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(write, payloads))
    with storage.open(key) as stream:
        winner = stream.read()
    return outcomes, winner


def test_filesystem_create_only_is_atomic_under_concurrency(tmp_path: Path) -> None:
    outcomes, winner = _race_storage_writes(
        FilesystemPrivateStorage(tmp_path / "race-objects"), "generated/aa/race"
    )
    assert outcomes == ["object_exists", "stored"]
    assert winner in {b"first immutable payload", b"second immutable payload"}


def test_s3_create_only_is_atomic_under_concurrency() -> None:
    class AtomicClient:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}
            self.lock = Lock()

        def put_object(self, **parameters: object) -> None:
            key = str(parameters["Key"])
            content = cast(BinaryIO, parameters["Body"]).read()
            assert parameters["IfNoneMatch"] == "*"
            with self.lock:
                if key in self.objects:
                    raise ClientError(
                        {
                            "Error": {"Code": "PreconditionFailed"},
                            "ResponseMetadata": {"HTTPStatusCode": 412},
                        },
                        "PutObject",
                    )
                self.objects[key] = content

        def get_object(self, **parameters: object) -> dict[str, object]:
            return {"Body": io.BytesIO(self.objects[str(parameters["Key"])])}

    storage = object.__new__(S3PrivateStorage)
    storage.bucket = "private-documents"
    storage.sse = "AES256"
    storage.kms_key = None
    storage.client = AtomicClient()
    outcomes, winner = _race_storage_writes(storage, "generated/ab/race")
    assert outcomes == ["object_exists", "stored"]
    assert winner in {b"first immutable payload", b"second immutable payload"}


def test_render_retry_reconciles_object_written_before_database_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_document_case("render-orphan-reconciliation")
    _, template_version_id = _published_template(case)
    root_id = UUID(str(case.reservation["root_id"]))
    record = create_record(case.owner, case.organization_id, root_reservation_id=root_id)
    instrument = create_instrument(
        case.owner,
        case.organization_id,
        record_id=UUID(record["id"]),
        instrument_type="main_contract",
        title="Contrato reconciliable",
    )
    content = b"%PDF-1.7\n% orphan reconciliation\n"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        "claridez.documents.jobs.render_pdf",
        lambda _html: RenderedPDF(
            content,
            digest,
            len(content),
            "WeasyPrint",
            "69.0",
            "claridez-render-weasyprint-69.0-debian12-v1",
        ),
    )
    issued = issue_instrument(
        case.owner,
        case.organization_id,
        instrument_id=UUID(instrument["id"]),
        template_version_id=UUID(template_version_id),
        idempotency_key=uuid4(),
        correlation_id="orphan-reconciliation",
    )
    version_id = UUID(issued["id"])
    expected_key = opaque_evidence_key("generated", str(version_id))
    original_save = GeneratedArtifact.save
    failed = False

    def fail_first_artifact_save(instance: GeneratedArtifact, *args: Any, **kwargs: Any) -> None:
        nonlocal failed
        if instance._state.adding and not failed:
            failed = True
            raise RuntimeError("synthetic database failure after object write")
        original_save(instance, *args, **kwargs)

    monkeypatch.setattr(GeneratedArtifact, "save", fail_first_artifact_save)
    assert work_once(case.organization_id, worker_id="orphan-worker")
    storage = private_storage()
    assert storage.exists(expected_key)
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        assert not GeneratedArtifact.objects.filter(issued_version_id=version_id).exists()
        job = DocumentJob.objects.get(
            job_type=DocumentJob.Type.RENDER_ISSUED_VERSION, target_id=version_id
        )
        assert job.state == DocumentJob.State.RETRY_WAIT
        job.next_attempt_at = timezone.now()
        job.save(update_fields=["next_attempt_at"])

    monkeypatch.setattr(GeneratedArtifact, "save", original_save)
    assert work_once(case.organization_id, worker_id="orphan-worker")
    assert work_once(case.organization_id, worker_id="orphan-worker")
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        artifact = GeneratedArtifact.objects.get(issued_version_id=version_id)
        assert artifact.storage_key == expected_key
        assert artifact.sha256 == digest
    with storage.open(expected_key) as stream:
        assert stream.read() == content


def test_renderer_refuses_noncanonical_host() -> None:
    with pytest.raises(DocumentsError) as rejected:
        render_pdf("<p>contrato</p>")
    assert rejected.value.code == "renderer_environment_not_approved"


def test_explicit_review_detects_only_observable_contractual_changes() -> None:
    policy = ExplicitReviewPolicy()
    baseline: dict[str, Any] = {
        "organization": {
            "id": "organization-1",
            "name": "Salón Claridez",
            "currency": "USD",
            "timezone_name": "America/Guayaquil",
        },
        "counterparty": {
            "id": "person-1",
            "full_name": "María Contraparte",
            "phone": "+593999999999",
            "email": "maria@example.test",
            "revision": 1,
        },
        "quotation": {"id": "quotation-1", "total": "100.00", "lines": [{"id": "line-1"}]},
        "reservation": {
            "organization_id": "organization-1",
            "event_request_id": "request-1",
            "root_reservation_id": "reservation-root",
            "current_reservation_id": "reservation-1",
            "quotation_version_id": "quotation-1",
            "venue_id": "venue-1",
            "space_id": "space-1",
            "starts_at": "2026-10-01T15:00:00-05:00",
            "ends_at": "2026-10-01T20:00:00-05:00",
            "timezone_name": "America/Guayaquil",
            "status": "confirmed",
            "cancelled_at": None,
            "revision": 1,
            "chain_reservation_ids": ["reservation-1"],
        },
        "renderer": {"name": "WeasyPrint", "version": "69.0"},
        "artifact_sha256": "a" * 64,
    }
    unchanged = policy.assess(baseline, deepcopy(baseline))
    assert unchanged.requires_new_issue is False
    assert unchanged.status == "unchanged"

    contractual_change = deepcopy(baseline)
    contractual_change["quotation"]["total"] = "120.00"
    changed = policy.assess(baseline, contractual_change)
    assert changed.changes == ("quotation",)

    internal_metadata = deepcopy(baseline)
    internal_metadata["counterparty"]["revision"] = 2
    internal_metadata["reservation"]["revision"] = 9
    internal_metadata["sources"] = {"trace": "different"}
    assert policy.assess(baseline, internal_metadata).status == "unchanged"

    technical_render = deepcopy(baseline)
    technical_render["renderer"] = {"name": "WeasyPrint", "version": "69.0.1"}
    technical_render["artifact_sha256"] = "b" * 64
    assert policy.assess(baseline, technical_render).status == "unchanged"

    rescheduled = deepcopy(baseline)
    rescheduled["reservation"]["current_reservation_id"] = "reservation-2"
    rescheduled["reservation"]["starts_at"] = "2026-10-02T15:00:00-05:00"
    rescheduled_assessment = policy.assess(baseline, rescheduled)
    assert rescheduled_assessment.status == "review_required"
    assert rescheduled_assessment.requires_new_issue is None
    assert rescheduled_assessment.requires_new_acceptance is None
    assert rescheduled_assessment.legal_instrument_outcome is None

    cancelled = deepcopy(baseline)
    cancelled["reservation"]["status"] = "cancelled"
    cancelled["reservation"]["cancelled_at"] = "2026-09-01T12:00:00-05:00"
    cancelled_assessment = policy.assess(baseline, cancelled)
    assert cancelled_assessment.status == "review_required"
    assert cancelled_assessment.legal_instrument_outcome is None


def test_generated_pdf_is_structurally_validated_and_page_limited() -> None:
    assert validate_rendered_pdf(_pdf()) == 1
    with pytest.raises(DocumentsError) as invalid:
        validate_rendered_pdf(b"%PDF-invalid")
    assert invalid.value.code == "invalid_rendered_pdf"

    output = io.BytesIO()
    writer = PdfWriter()
    for _ in range(MAX_RENDER_PAGES + 1):
        writer.add_blank_page(width=72, height=72)
    writer.write(output)
    with pytest.raises(DocumentsError) as too_many_pages:
        validate_rendered_pdf(output.getvalue())
    assert too_many_pages.value.code == "render_page_limit_exceeded"


def test_issue_render_integrity_grant_challenge_acceptance_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_document_case("acceptance")
    _, template_version_id = _published_template(case)
    root_id = UUID(str(case.reservation["root_id"]))
    preview = preview_document(
        case.owner,
        case.organization_id,
        root_reservation_id=root_id,
        template_version_id=UUID(template_version_id),
    )
    assert preview["contractual"] is False
    assert preview["acceptance_allowed"] is False
    record = create_record(case.owner, case.organization_id, root_reservation_id=root_id)
    instrument = create_instrument(
        case.owner,
        case.organization_id,
        record_id=UUID(record["id"]),
        instrument_type="main_contract",
        title="Contrato principal",
    )
    content = b"%PDF-1.7\n% controlled synthetic artifact\n"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        "claridez.documents.jobs.render_pdf",
        lambda _html: RenderedPDF(
            content,
            digest,
            len(content),
            "WeasyPrint",
            "69.0",
            "claridez-render-weasyprint-69.0-debian12-v1",
        ),
    )
    issued = issue_instrument(
        case.owner,
        case.organization_id,
        instrument_id=UUID(instrument["id"]),
        template_version_id=UUID(template_version_id),
        idempotency_key=uuid4(),
        correlation_id="test-acceptance",
    )
    assert work_once(case.organization_id, worker_id="test-worker")
    assert work_once(case.organization_id, worker_id="test-worker")
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        artifact = GeneratedArtifact.objects.get(issued_version_id=issued["id"])
    assert artifact.sha256 == digest
    assert artifact.verified_at is not None
    grant = create_external_grant(
        case.owner,
        case.organization_id,
        issued_version_id=UUID(issued["id"]),
        purpose="accept",
        expires_at=timezone.now() + timedelta(hours=1),
        max_exchanges=1,
    )
    session = exchange_grant(grant["token"], request_id="req-1", ip_hash="ip-hash")
    challenge = create_acceptance_challenge(session.token)
    evidence = AcceptanceRequestEvidence(
        asserted_name="María Contraparte",
        ip_address="127.0.0.1",
        user_agent="pytest",
        request_id="req-accept",
        correlation_id="corr-accept",
        timezone_name="America/Guayaquil",
    )
    accepted = accept(
        session.token,
        challenge_token=challenge.token,
        manifestation_version=MANIFESTATION_VERSION,
        affirmative=True,
        evidence=evidence,
    )
    assert accepted.artifact_id == artifact.pk
    assert accepted.artifact_sha256 == artifact.sha256
    assert accepted.issued_version_id == UUID(issued["id"])
    assert accepted.challenge_id == challenge.challenge.pk
    assert accepted.manifestation_version == MANIFESTATION_VERSION
    assert accepted.manifestation_text
    assert accepted.acceptor_projection["asserted_name"] == "María Contraparte"
    assert accepted.attribution_method == "secure_link_self_assertion"
    assert accepted.authentication_result["grant_id"] == str(challenge.challenge.grant_id)
    assert accepted.accepted_at is not None
    assert accepted.request_id == "req-accept"
    assert accepted.correlation_id == "corr-accept"
    assert accepted.ip_address is None
    assert accepted.user_agent is None
    with pytest.raises(DocumentsError) as replay:
        accept(
            session.token,
            challenge_token=challenge.token,
            manifestation_version=MANIFESTATION_VERSION,
            affirmative=True,
            evidence=evidence,
        )
    assert replay.value.code == "invalid_or_consumed_challenge"
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        assert AcceptanceEvidence.objects.count() == 1
    assert (
        read_record_state(case.owner, case.organization_id, root_reservation_id=root_id)[
            "materiality"
        ]["status"]
        == "unchanged"
    )
    revoked = create_external_grant(
        case.owner,
        case.organization_id,
        issued_version_id=UUID(issued["id"]),
        purpose="read",
        expires_at=timezone.now() + timedelta(hours=1),
    )
    revoke_external_grant(case.owner, case.organization_id, grant_id=UUID(revoked["id"]))
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        assert set(ExternalAccessEvent.objects.values_list("kind", flat=True)) >= {
            "grant_created",
            "grant_exchanged",
            "challenge_created",
            "acceptance_completed",
            "grant_revoked",
        }
    with pytest.raises(DocumentsError):
        exchange_grant(revoked["token"], request_id="revoked", ip_hash="ip-hash")


def test_artifact_integrity_failure_persists_and_blocks_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from claridez.documents.services import download_artifact

    case = build_document_case("artifact-corruption")
    _, template_version_id = _published_template(case)
    root_id = UUID(str(case.reservation["root_id"]))
    record = create_record(case.owner, case.organization_id, root_reservation_id=root_id)
    instrument = create_instrument(
        case.owner,
        case.organization_id,
        record_id=UUID(record["id"]),
        instrument_type="main_contract",
        title="Contrato principal",
    )
    content = b"%PDF-1.7\n% integrity artifact\n"
    monkeypatch.setattr(
        "claridez.documents.jobs.render_pdf",
        lambda _html: RenderedPDF(
            content,
            hashlib.sha256(content).hexdigest(),
            len(content),
            "WeasyPrint",
            "69.0",
            "claridez-render-weasyprint-69.0-debian12-v1",
        ),
    )
    issued = issue_instrument(
        case.owner,
        case.organization_id,
        instrument_id=UUID(instrument["id"]),
        template_version_id=UUID(template_version_id),
        idempotency_key=uuid4(),
        correlation_id="integrity-test",
    )
    assert work_once(case.organization_id, worker_id="integrity-worker")
    assert work_once(case.organization_id, worker_id="integrity-worker")
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        artifact = GeneratedArtifact.objects.get(issued_version_id=issued["id"])
    storage = private_storage()
    assert isinstance(storage, FilesystemPrivateStorage)
    storage._path(artifact.storage_key).write_bytes(b"substituted")
    with pytest.raises(DocumentsError) as blocked:
        download_artifact(case.owner, case.organization_id, artifact_id=artifact.pk)
    assert blocked.value.code == "forbidden"
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        artifact.refresh_from_db()
        assert artifact.state == GeneratedArtifact.State.INTEGRITY_FAILED
        assert artifact.artifactintegrityevent_set.filter(result="mismatch").exists()


class _Scanner:
    def __init__(self, outcomes: list[ScanOutcome]) -> None:
        self.outcomes = outcomes

    def scan(self, _stream: BinaryIO) -> ScanOutcome:
        return self.outcomes.pop(0)


def test_external_upload_is_unavailable_until_clean_and_retries_scanner_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_document_case("upload")
    root_id = UUID(str(case.reservation["root_id"]))
    record = create_record(case.owner, case.organization_id, root_reservation_id=root_id)
    uploaded = upload_external_file(
        case.owner,
        case.organization_id,
        record_id=UUID(record["id"]),
        display_name="evidencia.pdf",
        declared_media_type="application/pdf",
        source=io.BytesIO(_pdf()),
        correlation_id="upload-test",
    )
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        row = ExternalFile.objects.get(pk=uploaded["id"])
    assert row.state == ExternalFile.State.UPLOADING
    assert work_once(case.organization_id, worker_id="upload-worker")
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        row.refresh_from_db()
    assert row.state == ExternalFile.State.PENDING_SCAN
    scanner = _Scanner(
        [
            ScanOutcome(ScanResult.TIMEOUT, "fake", detail="timeout"),
            ScanOutcome(ScanResult.CLEAN, "fake", detail="clean"),
        ]
    )
    monkeypatch.setattr("claridez.documents.jobs.malware_scanner", lambda: scanner)
    assert work_once(case.organization_id, worker_id="upload-worker")
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        row.refresh_from_db()
    assert row.state == ExternalFile.State.SCAN_ERROR
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        job = DocumentJob.objects.get(job_type=DocumentJob.Type.SCAN_EXTERNAL_FILE)
        job.next_attempt_at = timezone.now()
        job.save(update_fields=["next_attempt_at"])
    assert work_once(case.organization_id, worker_id="upload-worker")
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        row.refresh_from_db()
    assert row.state == ExternalFile.State.CLEAN
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        assert list(MalwareScanAttempt.objects.values_list("result", flat=True)) == [
            ScanResult.TIMEOUT,
            ScanResult.CLEAN,
        ]


def test_scanner_infected_and_terminal_error_never_become_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_document_case("upload-terminal")
    record = create_record(
        case.owner,
        case.organization_id,
        root_reservation_id=UUID(str(case.reservation["root_id"])),
    )
    infected = upload_external_file(
        case.owner,
        case.organization_id,
        record_id=UUID(record["id"]),
        display_name="infected.pdf",
        declared_media_type="application/pdf",
        source=io.BytesIO(_pdf()),
        correlation_id="infected-test",
    )
    assert work_once(case.organization_id, worker_id="scan-worker")
    monkeypatch.setattr(
        "claridez.documents.jobs.malware_scanner",
        lambda: _Scanner(
            [
                ScanOutcome(
                    ScanResult.INFECTED,
                    "fake",
                    malware_name="Eicar-Test-Signature",
                    detail="FOUND",
                )
            ]
        ),
    )
    assert work_once(case.organization_id, worker_id="scan-worker")
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        assert ExternalFile.objects.get(pk=infected["id"]).state == ExternalFile.State.INFECTED


def test_scanner_errors_exhaust_retries_as_dead_without_releasing_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_document_case("upload-dead")
    record = create_record(
        case.owner,
        case.organization_id,
        root_reservation_id=UUID(str(case.reservation["root_id"])),
    )
    uploaded = upload_external_file(
        case.owner,
        case.organization_id,
        record_id=UUID(record["id"]),
        display_name="scanner-error.pdf",
        declared_media_type="application/pdf",
        source=io.BytesIO(_pdf()),
        correlation_id="scanner-dead",
    )
    assert work_once(case.organization_id, worker_id="scanner-dead-worker")
    monkeypatch.setattr(
        "claridez.documents.jobs.malware_scanner",
        lambda: _Scanner(
            [ScanOutcome(ScanResult.TECHNICAL_ERROR, "fake", detail="technical_error")]
        ),
    )
    for attempt in range(3):
        assert work_once(case.organization_id, worker_id="scanner-dead-worker")
        if attempt < 2:
            with authorized_tenant_scope(
                case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
            ):
                job = DocumentJob.objects.get(job_type=DocumentJob.Type.SCAN_EXTERNAL_FILE)
                job.next_attempt_at = timezone.now()
                job.save(update_fields=["next_attempt_at"])
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        row = ExternalFile.objects.get(pk=uploaded["id"])
        job = DocumentJob.objects.get(job_type=DocumentJob.Type.SCAN_EXTERNAL_FILE)
        assert row.state == ExternalFile.State.SCAN_ERROR
        assert row.available_at is None
        assert job.state == DocumentJob.State.DEAD
        assert job.attempts == job.max_attempts == 3
        assert list(job.history.values_list("outcome", flat=True)) == ["retry", "retry", "dead"]
        assert MalwareScanAttempt.objects.filter(external_file=row).count() == 3


def test_renderer_failure_exhausts_retries_and_marks_emission_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_document_case("render-dead")
    _, template_version_id = _published_template(case)
    record = create_record(
        case.owner,
        case.organization_id,
        root_reservation_id=UUID(str(case.reservation["root_id"])),
    )
    instrument = create_instrument(
        case.owner,
        case.organization_id,
        record_id=UUID(record["id"]),
        instrument_type="main_contract",
        title="Contrato con render fallido",
    )

    def fail_render(_html: str) -> RenderedPDF:
        raise DocumentsError("render_failed", "Fallo controlado del renderer.")

    monkeypatch.setattr("claridez.documents.jobs.render_pdf", fail_render)
    issued = issue_instrument(
        case.owner,
        case.organization_id,
        instrument_id=UUID(instrument["id"]),
        template_version_id=UUID(template_version_id),
        idempotency_key=uuid4(),
        correlation_id="renderer-dead",
    )
    for attempt in range(3):
        assert work_once(case.organization_id, worker_id="renderer-dead-worker")
        if attempt < 2:
            with authorized_tenant_scope(
                case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
            ):
                job = DocumentJob.objects.get(job_type=DocumentJob.Type.RENDER_ISSUED_VERSION)
                job.next_attempt_at = timezone.now()
                job.save(update_fields=["next_attempt_at"])
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        version = IssuedInstrumentVersion.objects.get(pk=issued["id"])
        job = DocumentJob.objects.get(job_type=DocumentJob.Type.RENDER_ISSUED_VERSION)
        assert version.state == IssuedInstrumentVersion.State.RENDER_FAILED
        assert not GeneratedArtifact.objects.filter(issued_version=version).exists()
        assert job.state == DocumentJob.State.DEAD
        assert list(
            DocumentJobAttempt.objects.filter(job=job).values_list("outcome", flat=True)
        ) == ["retry", "retry", "dead"]


def test_upload_validation_rejects_mime_spoofing_and_active_pdf() -> None:
    with pytest.raises(DocumentsError) as mismatch:
        validate_upload(
            display_name="fake.pdf",
            declared_media_type="application/pdf",
            stream=io.BytesIO(b"not a pdf"),
        )
    assert mismatch.value.code == "mime_mismatch"
    with pytest.raises(DocumentsError) as unsupported:
        validate_upload(
            display_name="archive.zip",
            declared_media_type="application/zip",
            stream=io.BytesIO(b"PK\x03\x04"),
        )
    assert unsupported.value.code == "unsupported_file"


class _FakeSocket:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent = bytearray()

    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def settimeout(self, _timeout: float) -> None:
        return None

    def sendall(self, value: bytes) -> None:
        self.sent.extend(value)

    def recv(self, _size: int) -> bytes:
        value, self.response = self.response, b""
        return value


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (b"stream: OK\0", ScanResult.CLEAN),
        (b"stream: Eicar-Test-Signature FOUND\0", ScanResult.INFECTED),
        (b"stream: unsupported format ERROR\0", ScanResult.UNSUPPORTED),
        (b"", ScanResult.INCOMPLETE),
    ],
)
def test_clamd_protocol_distinguishes_outcomes(
    monkeypatch: pytest.MonkeyPatch, response: bytes, expected: ScanResult
) -> None:
    version_connection = _FakeSocket(b"ClamAV 1.4.6/28087/Sun Aug 9 2026\0")
    scan_connection = _FakeSocket(response)
    connections = iter((version_connection, scan_connection))
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: next(connections))
    outcome = ClamDScanner().scan(io.BytesIO(b"sample"))
    assert outcome.result == expected
    assert outcome.scanner_version == "1.4.6"
    assert outcome.signatures_version == "28087"
    assert version_connection.sent == b"zVERSION\0"
    assert scan_connection.sent.startswith(b"zINSTREAM\0")


def test_retention_evidence_and_holds_never_dispose_physical_bytes() -> None:
    case = build_document_case("retention")
    root_id = UUID(str(case.reservation["root_id"]))
    record = create_record(case.owner, case.organization_id, root_reservation_id=root_id)
    policy = create_retention_policy(
        case.owner,
        case.organization_id,
        key="contractual_evidence",
        version=1,
        name="Evidencia contractual",
        classification="contractual",
        rules={"basis": "política jurídica aprobada por la organización"},
    )
    activate_retention_policy(case.owner, case.organization_id, policy_id=UUID(policy["id"]))
    assignment = assign_retention_policy(
        case.owner,
        case.organization_id,
        policy_id=UUID(policy["id"]),
        target_type="contractual_record",
        target_id=UUID(record["id"]),
    )
    evaluated = evaluate_retention_eligibility(
        case.owner,
        case.organization_id,
        assignment_id=UUID(assignment["id"]),
        eligible_at=timezone.now() - timedelta(days=1),
        rationale="Evaluación autorizada sin disposición física",
    )
    assert evaluated["state"] == "eligible"
    assert evaluated["physical_disposition"] == "not_implemented"
    hold = place_legal_hold(
        case.owner,
        case.organization_id,
        assignment_id=UUID(assignment["id"]),
        reason="Litigio en revisión",
    )
    release_legal_hold(
        case.owner,
        case.organization_id,
        hold_id=UUID(hold["id"]),
        reason="Revisión concluida",
    )
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        assert list(RetentionEvent.objects.values_list("kind", flat=True)) == [
            "policy_assigned",
            "eligibility_evaluated",
            "legal_hold_placed",
            "legal_hold_released",
        ]
