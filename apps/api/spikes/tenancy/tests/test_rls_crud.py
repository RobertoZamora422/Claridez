"""Comprobar CRUD, SQL directo, default-deny y límites de autorización de RLS."""

from __future__ import annotations

import uuid

import pytest
from django.db import DatabaseError, connections, transaction

from spikes.tenancy.context import ValidatedTechnicalOrganization, tenant_scope
from spikes.tenancy.models import RlsTechnicalRecord
from spikes.tenancy.services import TenantObjectNotFound, get_private_record, tenant_queryset
from spikes.tenancy.tests.conftest import (
    RLS_RECORD_A,
    RLS_RECORD_B,
    EvidenceRecorder,
    Organizations,
)

pytestmark = pytest.mark.tenancy_spike


def test_rls_filters_reads_and_direct_sql_fail_closed(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    assert RlsTechnicalRecord.spike_unfiltered_objects.count() == 0
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT count(*) FROM claridez_spike_rls_record")
        assert cursor.fetchone()[0] == 0

    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)):
        assert tenant_queryset(RlsTechnicalRecord).count() == 1
        with pytest.raises(TenantObjectNotFound):
            get_private_record(RlsTechnicalRecord, RLS_RECORD_B)
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT count(*) FROM claridez_spike_rls_record")
            assert cursor.fetchone()[0] == 1

    evidence.record("rls_missing_context_rows", 0)
    evidence.record("rls_foreign_lookup", "indistinguishable_not_found")
    evidence.record("rls_direct_sql", "isolated")

    with (
        tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.b)),
        pytest.raises(TenantObjectNotFound),
    ):
        get_private_record(RlsTechnicalRecord, RLS_RECORD_A)
    evidence.record("rls_bidirectional_cross_lookup", "indistinguishable_not_found")


def test_rls_write_without_context_fails(evidence: EvidenceRecorder) -> None:
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connections["default"].cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO claridez_spike_rls_record "
            "(id, organization_id, external_key, payload) VALUES (%s, %s, %s, %s)",
            (uuid.uuid4(), uuid.uuid4(), "no-context", "synthetic"),
        )
    evidence.record("rls_write_without_context", "rejected")


def test_rls_using_and_with_check_cover_crud_and_bulk(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    scope = ValidatedTechnicalOrganization(synthetic_rows.a)
    with tenant_scope(scope):
        connection = connections["default"]
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO claridez_spike_rls_record "
                "(id, organization_id, external_key, payload) VALUES (%s, %s, %s, %s)",
                (uuid.uuid4(), synthetic_rows.a, "direct-a", "synthetic"),
            )
            cursor.execute(
                "UPDATE claridez_spike_rls_record SET payload = %s WHERE organization_id = %s",
                ("updated", synthetic_rows.a),
            )
            assert cursor.rowcount == 2
            cursor.execute(
                "DELETE FROM claridez_spike_rls_record WHERE organization_id = %s",
                (synthetic_rows.b,),
            )
            assert cursor.rowcount == 0

        with pytest.raises(DatabaseError), transaction.atomic():
            RlsTechnicalRecord.spike_unfiltered_objects.bulk_create(
                [
                    RlsTechnicalRecord(
                        organization_id=synthetic_rows.b,
                        external_key="cross-bulk",
                        payload="synthetic",
                    )
                ]
            )
        with pytest.raises(DatabaseError), transaction.atomic():
            RlsTechnicalRecord.spike_unfiltered_objects.filter(
                organization_id=synthetic_rows.a
            ).update(organization_id=synthetic_rows.b)
    evidence.record("rls_crud", "using_and_with_check_enforced")
    evidence.record("rls_bulk_cross_tenant", "rejected")


@pytest.mark.parametrize("raw_context", ["", "not-a-uuid"])
def test_context_reader_maps_empty_and_malformed_to_no_tenant(raw_context: str) -> None:
    with transaction.atomic(), connections["default"].cursor() as cursor:
        cursor.execute("SELECT set_config('claridez.organization_id', %s, true)", (raw_context,))
        cursor.execute("SELECT claridez_spike_current_organization_id()")
        assert cursor.fetchone()[0] is None
        cursor.execute("SELECT count(*) FROM claridez_spike_rls_record")
        assert cursor.fetchone()[0] == 0


def test_table_without_policy_is_default_deny(evidence: EvidenceRecorder) -> None:
    with transaction.atomic(), connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, true)",
            (str(uuid.uuid4()),),
        )
        cursor.execute("SELECT count(*) FROM claridez_spike_rls_default_deny")
        assert cursor.fetchone()[0] == 0
        with pytest.raises(DatabaseError), transaction.atomic():
            cursor.execute(
                "INSERT INTO claridez_spike_rls_default_deny "
                "(id, organization_id, external_key, payload) VALUES (%s, %s, %s, %s)",
                (uuid.uuid4(), uuid.uuid4(), "denied", "synthetic"),
            )
    evidence.record("rls_table_without_policy", "default_deny")


def test_fault_injection_proves_rls_is_not_authorization(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    # El constructor simula que una capa superior validó B, aunque el actor ficticio era de A.
    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.b)):
        assert RlsTechnicalRecord.spike_unfiltered_objects.count() == 1
    evidence.record("rls_foreign_valid_uuid_fault", "policy_followed_received_context")
    evidence.record("rls_membership_decision", "not_provided_by_rls")
