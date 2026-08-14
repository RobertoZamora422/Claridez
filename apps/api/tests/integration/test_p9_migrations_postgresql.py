from __future__ import annotations

from uuid import UUID

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from claridez.documents.models import (
    AcceptanceEvidence,
    ContractualInstrument,
    ContractualRecord,
    ExternalFile,
    GeneratedArtifact,
)
from claridez.documents.services import read_record_state
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope
from tests.document_fixtures import build_document_case

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _restore_head() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_p9_from_p8_final_preserves_reservations_without_inventing_documents() -> None:
    case = build_document_case("p9-migration")
    reservation_id = UUID(str(case.reservation["id"]))
    root_id = UUID(str(case.reservation["root_id"]))
    try:
        MigrationExecutor(connection).migrate([("documents", None)])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('claridez.organization_id', %s, false)",
                (str(case.organization_id),),
            )
            cursor.execute(
                "SELECT count(*) FROM commercial_reservation WHERE id = %s", (reservation_id,)
            )
            row = cursor.fetchone()
            assert row is not None and row[0] == 1
            cursor.execute("SELECT to_regclass('public.documents_contractualrecord')")
            table = cursor.fetchone()
            assert table is not None and table[0] is None

        _restore_head()
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.documents_contractualrecord')")
            table = cursor.fetchone()
            assert table is not None and table[0] == "documents_contractualrecord"
        with authorized_tenant_scope(
            case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
        ):
            assert ContractualRecord.objects.count() == 0
            assert ContractualInstrument.objects.count() == 0
            assert GeneratedArtifact.objects.count() == 0
            assert AcceptanceEvidence.objects.count() == 0
            assert ExternalFile.objects.count() == 0
        status = read_record_state(case.owner, case.organization_id, root_reservation_id=root_id)
        assert status["status"] == "no_contract_issued"
        assert status["label"] == "sin contrato emitido"
    finally:
        _restore_head()


def test_p9_document_migrations_are_immediately_reapplicable() -> None:
    try:
        MigrationExecutor(connection).migrate([("documents", None)])
        _restore_head()
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM django_migrations WHERE app = 'documents'")
            count = cursor.fetchone()
        assert count is not None and count[0] == 8
    finally:
        _restore_head()
