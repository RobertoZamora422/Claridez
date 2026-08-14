from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone

from claridez.documents.acceptance import (
    MANIFESTATION_VERSION,
    AcceptanceRequestEvidence,
    accept,
)
from claridez.documents.errors import DocumentsError
from claridez.documents.external_access import create_acceptance_challenge, exchange_grant
from claridez.documents.jobs import claim_job, enqueue_job, work_once
from claridez.documents.models import (
    AcceptanceEvidence,
    ArtifactIntegrityEvent,
    ContractualRecord,
    DocumentJob,
    DocumentJobAttempt,
    DocumentTemplateVersion,
    GeneratedArtifact,
    IssuedInstrumentVersion,
)
from claridez.documents.rendering import RenderedPDF
from claridez.documents.services import (
    create_external_grant,
    create_instrument,
    create_record,
    create_template,
    issue_instrument,
    publish_template_version,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.settings.environment import load_bootstrap_settings
from tests.document_fixtures import DocumentCase, build_document_case

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

P9_PRIVATE_TABLES = (
    "documents_documenttemplate",
    "documents_documenttemplateversion",
    "documents_templateevent",
    "documents_contractualrecord",
    "documents_contractualinstrument",
    "documents_issuedinstrumentversion",
    "documents_generatedartifact",
    "documents_artifactintegrityevent",
    "documents_externalfile",
    "documents_externalfileevent",
    "documents_malwarescanattempt",
    "documents_externalaccessgrant",
    "documents_externaldocumentsession",
    "documents_acceptancechallenge",
    "documents_acceptanceevidence",
    "documents_externalaccessevent",
    "documents_retentionpolicy",
    "documents_retentionassignment",
    "documents_legalhold",
    "documents_retentionevent",
    "documents_documentjob",
    "documents_documentjobattempt",
)
P9_APPEND_ONLY_TABLES = (
    "documents_templateevent",
    "documents_artifactintegrityevent",
    "documents_externalfileevent",
    "documents_malwarescanattempt",
    "documents_acceptanceevidence",
    "documents_externalaccessevent",
    "documents_retentionevent",
    "documents_documentjobattempt",
)
BODY = "<h1>{{ organization.name }}</h1><p>{{ counterparty.full_name }}</p>"
SCHEMA = {
    "version": "claridez-vars-v1",
    "variables": [
        {"name": "organization.name", "required": True},
        {"name": "counterparty.full_name", "required": True},
    ],
}


def _record(case: DocumentCase) -> dict[str, object]:
    return create_record(
        case.owner,
        case.organization_id,
        root_reservation_id=UUID(str(case.reservation["root_id"])),
    )


def _artifact(case: DocumentCase, monkeypatch: pytest.MonkeyPatch) -> GeneratedArtifact:
    template = create_template(
        case.owner,
        case.organization_id,
        name=f"Contrato {uuid4()}",
        title="Contrato",
        body_html=BODY,
        variable_schema=SCHEMA,
    )
    template_version_id = UUID(template["versions"][0]["id"])
    publish_template_version(case.owner, case.organization_id, version_id=template_version_id)
    record = _record(case)
    instrument = create_instrument(
        case.owner,
        case.organization_id,
        record_id=UUID(str(record["id"])),
        instrument_type="main_contract",
        title="Contrato",
    )
    content = b"%PDF-1.7\n% integration artifact\n"
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
    issue_instrument(
        case.owner,
        case.organization_id,
        instrument_id=UUID(instrument["id"]),
        template_version_id=template_version_id,
        idempotency_key=uuid4(),
        correlation_id="integration-artifact",
    )
    assert work_once(case.organization_id, worker_id="integration-worker")
    assert work_once(case.organization_id, worker_id="integration-worker")
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        return GeneratedArtifact.objects.get(is_emitted_original=True)


def _app_connection() -> psycopg.Connection[tuple[object, ...]]:
    settings = load_bootstrap_settings()
    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.test_db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        autocommit=True,
    )


def test_p9_force_rls_app_role_privileges_and_direct_sql_tenant_isolation() -> None:
    first = build_document_case("p9-rls-a")
    second = build_document_case("p9-rls-b")
    first_record = _record(first)
    second_record = _record(second)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(%s) ORDER BY relname",
            [list(P9_PRIVATE_TABLES)],
        )
        metadata = cursor.fetchall()
        cursor.execute(
            "SELECT has_table_privilege('claridez_app', "
            "'documents_contractualrecord', 'SELECT,INSERT'), "
            "has_table_privilege('claridez_app', 'documents_contractualrecord', 'DELETE'), "
            "has_table_privilege('claridez_app', 'documents_acceptanceevidence', 'UPDATE'), "
            "has_table_privilege('claridez_app', 'documents_acceptanceevidence', 'DELETE')"
        )
        privileges = cursor.fetchone()
        cursor.execute(
            "SELECT c.relname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relname = ANY(%s) "
            "AND t.tgname = c.relname || '_no_delete' ORDER BY c.relname",
            [list(P9_PRIVATE_TABLES)],
        )
        no_delete_tables = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            "SELECT c.relname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND c.relname = ANY(%s) "
            "AND t.tgname = c.relname || '_append_only' ORDER BY c.relname",
            [list(P9_APPEND_ONLY_TABLES)],
        )
        append_only_tables = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            "SELECT table_name, has_table_privilege('claridez_app', "
            "'public.' || table_name, 'DELETE') FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY(%s) ORDER BY table_name",
            [list(P9_PRIVATE_TABLES)],
        )
        delete_privileges = cursor.fetchall()
    assert metadata == sorted((table, True, True) for table in P9_PRIVATE_TABLES)
    assert privileges == (True, False, False, False)
    assert no_delete_tables == sorted(P9_PRIVATE_TABLES)
    assert append_only_tables == sorted(P9_APPEND_ONLY_TABLES)
    assert delete_privileges == sorted((table, False) for table in P9_PRIVATE_TABLES)

    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM documents_contractualrecord")
        first_count = cursor.fetchone()
        assert first_count is not None and first_count[0] == 0
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            (str(first.organization_id),),
        )
        cursor.execute(
            "SELECT id FROM documents_contractualrecord WHERE id IN (%s, %s) ORDER BY id",
            (first_record["id"], second_record["id"]),
        )
        assert [str(row[0]) for row in cursor.fetchall()] == [str(first_record["id"])]
        cursor.execute(
            "UPDATE documents_contractualrecord SET root_reservation_id = root_reservation_id "
            "WHERE id = %s",
            (second_record["id"],),
        )
        assert cursor.rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                "DELETE FROM documents_contractualrecord WHERE id = %s", (first_record["id"],)
            )


def test_concurrent_record_creation_returns_one_record() -> None:
    case = build_document_case("p9-record-race")
    root_id = UUID(str(case.reservation["root_id"]))
    barrier = Barrier(2)

    def create() -> str:
        close_old_connections()
        try:
            owner = User.objects.get(pk=case.owner.pk)
            barrier.wait(timeout=10)
            return str(
                create_record(owner, case.organization_id, root_reservation_id=root_id)["id"]
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=20)
            for future in (executor.submit(create), executor.submit(create))
        ]
    assert len(set(results)) == 1
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        assert ContractualRecord.objects.filter(root_reservation_id=root_id).count() == 1


def test_skip_locked_job_claims_are_distinct_and_recover_expired_leases() -> None:
    case = build_document_case("p9-jobs")
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        for index in range(2):
            enqueue_job(
                organization_id=case.organization_id,
                job_type=DocumentJob.Type.VERIFY_ARTIFACT,
                target_id=uuid4(),
                idempotency_key=f"claim-{index}-{uuid4()}",
                correlation_id="claim-test",
            )
    barrier = Barrier(2)

    def claim(worker: str) -> str:
        close_old_connections()
        try:
            owner = User.objects.get(pk=case.owner.pk)
            with authorized_tenant_scope(
                owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
            ):
                barrier.wait(timeout=10)
                job = claim_job(case.organization_id, worker_id=worker)
                assert job is not None
                return str(job.pk)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        identifiers = [
            future.result(timeout=20)
            for future in (executor.submit(claim, "worker-a"), executor.submit(claim, "worker-b"))
        ]
    assert len(set(identifiers)) == 2
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        expired = DocumentJob.objects.get(pk=identifiers[0])
        expired.lease_expires_at = timezone.now() - timedelta(seconds=1)
        expired.save(update_fields=["lease_expires_at"])
        recovered = claim_job(case.organization_id, worker_id="recovery-worker")
        assert recovered is not None
        assert recovered.pk == expired.pk
        assert recovered.attempts == 2


def test_acceptance_challenge_is_single_use_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_document_case("p9-accept-race")
    artifact = _artifact(case, monkeypatch)
    grant = create_external_grant(
        case.owner,
        case.organization_id,
        issued_version_id=artifact.issued_version_id,
        purpose="accept",
        expires_at=timezone.now() + timedelta(hours=1),
        max_exchanges=1,
    )
    session = exchange_grant(grant["token"], request_id="race", ip_hash="ip")
    challenge = create_acceptance_challenge(session.token)
    evidence = AcceptanceRequestEvidence(
        asserted_name="Contraparte concurrente",
        ip_address="127.0.0.1",
        user_agent="pytest",
        request_id="accept-race",
        correlation_id="accept-race",
        timezone_name="America/Guayaquil",
    )
    barrier = Barrier(2)

    def submit() -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                accept(
                    session.token,
                    challenge_token=challenge.token,
                    manifestation_version=MANIFESTATION_VERSION,
                    affirmative=True,
                    evidence=evidence,
                )
            except DocumentsError as error:
                return error.code
            return "accepted"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(
            future.result(timeout=20)
            for future in (executor.submit(submit), executor.submit(submit))
        )
    assert results == ["accepted", "invalid_or_consumed_challenge"]
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        assert AcceptanceEvidence.objects.filter(artifact=artifact).count() == 1


def test_database_guards_stop_orm_bulk_delete_and_app_sql_evidence_bypasses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_document_case("p9-guards")
    template = create_template(
        case.owner,
        case.organization_id,
        name="Plantilla guardada",
        title="Título inmutable",
        body_html=BODY,
        variable_schema=SCHEMA,
    )
    version_id = UUID(template["versions"][0]["id"])
    publish_template_version(case.owner, case.organization_id, version_id=version_id)
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.DOCUMENT_TEMPLATE_MANAGE
    ):
        version = DocumentTemplateVersion.objects.get(pk=version_id)
        version.title = "Mutado por save"
        with pytest.raises(IntegrityError), transaction.atomic():
            version.save(update_fields=["title"])
        version.refresh_from_db()
        with pytest.raises(IntegrityError), transaction.atomic():
            DocumentTemplateVersion.objects.filter(pk=version_id).update(title="Mutado")
        version.body_html = "<p>Mutado por bulk</p>"
        with pytest.raises(IntegrityError), transaction.atomic():
            DocumentTemplateVersion.objects.bulk_update([version], ["body_html"])
        with (
            pytest.raises(IntegrityError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE documents_documenttemplateversion SET body_html = '<p>mutado</p>' "
                "WHERE id = %s",
                (version_id,),
            )
    artifact = _artifact(case, monkeypatch)
    grant = create_external_grant(
        case.owner,
        case.organization_id,
        issued_version_id=artifact.issued_version_id,
        purpose="accept",
        expires_at=timezone.now() + timedelta(hours=1),
    )
    session = exchange_grant(grant["token"], request_id="guard-accept", ip_hash="guard-ip")
    challenge = create_acceptance_challenge(session.token)
    acceptance = accept(
        session.token,
        challenge_token=challenge.token,
        manifestation_version=MANIFESTATION_VERSION,
        affirmative=True,
        evidence=AcceptanceRequestEvidence(
            asserted_name="Contraparte inmutable",
            ip_address=None,
            user_agent=None,
            request_id="guard-accept",
            correlation_id="guard-accept",
            timezone_name="America/Guayaquil",
        ),
    )
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        issued = IssuedInstrumentVersion.objects.get(pk=artifact.issued_version_id)
        issued.snapshot_sha256 = "0" * 64
        with pytest.raises(IntegrityError), transaction.atomic():
            issued.save(update_fields=["snapshot_sha256"])
        issued.refresh_from_db()
        with pytest.raises(IntegrityError), transaction.atomic():
            IssuedInstrumentVersion.objects.filter(pk=issued.pk).update(snapshot_sha256="1" * 64)
        issued.snapshot_sha256 = "2" * 64
        with pytest.raises(IntegrityError), transaction.atomic():
            IssuedInstrumentVersion.objects.bulk_update([issued], ["snapshot_sha256"])

        artifact.sha256 = "3" * 64
        with pytest.raises(IntegrityError), transaction.atomic():
            artifact.save(update_fields=["sha256"])
        artifact.refresh_from_db()
        with pytest.raises(IntegrityError), transaction.atomic():
            GeneratedArtifact.objects.filter(pk=artifact.pk).update(sha256="3" * 64)
        artifact.sha256 = "3" * 64
        with pytest.raises(IntegrityError), transaction.atomic():
            GeneratedArtifact.objects.bulk_update([artifact], ["sha256"])

        with pytest.raises(IntegrityError), transaction.atomic():
            ContractualRecord.objects.filter(pk=issued.instrument.record_id).update(
                root_reservation_id=uuid4()
            )

        acceptance.manifestation_text = "Mutación prohibida"
        with pytest.raises(IntegrityError), transaction.atomic():
            acceptance.save(update_fields=["manifestation_text"])
        acceptance.refresh_from_db()
        with pytest.raises(IntegrityError), transaction.atomic():
            AcceptanceEvidence.objects.filter(pk=acceptance.pk).update(
                manifestation_text="Mutación bulk prohibida"
            )
        acceptance.manifestation_text = "Mutación bulk_update prohibida"
        with pytest.raises(IntegrityError), transaction.atomic():
            AcceptanceEvidence.objects.bulk_update([acceptance], ["manifestation_text"])
        with pytest.raises(IntegrityError), transaction.atomic():
            acceptance.delete()
        with pytest.raises(IntegrityError), transaction.atomic():
            AcceptanceEvidence.objects.filter(pk=acceptance.pk).delete()

        attempt = DocumentJobAttempt.objects.first()
        integrity_event = ArtifactIntegrityEvent.objects.first()
        assert attempt is not None and integrity_event is not None
        with pytest.raises(IntegrityError), transaction.atomic():
            DocumentJobAttempt.objects.filter(pk=attempt.pk).update(outcome="mutated")
        with pytest.raises(IntegrityError), transaction.atomic():
            ArtifactIntegrityEvent.objects.filter(pk=integrity_event.pk).update(result="missing")
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM documents_issuedinstrumentversion WHERE id = %s", (issued.pk,)
            )

    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            (str(case.organization_id),),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "UPDATE documents_issuedinstrumentversion SET snapshot_sha256 = %s WHERE id = %s",
                ("4" * 64, artifact.issued_version_id),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "UPDATE documents_generatedartifact SET sha256 = %s WHERE id = %s",
                ("5" * 64, artifact.pk),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                "UPDATE documents_acceptanceevidence SET manifestation_text = %s WHERE id = %s",
                ("Mutación", acceptance.pk),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                "DELETE FROM documents_acceptanceevidence WHERE id = %s", (acceptance.pk,)
            )
