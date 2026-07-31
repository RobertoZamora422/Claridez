"""Propiedad, privilegios, FORCE RLS y procesos técnicos sin tenant."""

from __future__ import annotations

import pytest
from django.db import DatabaseError, connections, transaction

from spikes.tenancy.context import ValidatedTechnicalOrganization, tenant_scope
from spikes.tenancy.database import CLARIDEZ_ROLES, collect_catalog_evidence
from spikes.tenancy.models import ApplicationTechnicalRecord, RlsTechnicalRecord
from spikes.tenancy.tests.conftest import EvidenceRecorder, Organizations

pytestmark = pytest.mark.tenancy_spike


def test_catalogs_confirm_ownership_and_role_flags(evidence: EvidenceRecorder) -> None:
    catalog = collect_catalog_evidence()
    owners = catalog["owners"]
    assert owners
    assert all(row["owner"] == "claridez_migrator" for row in owners)
    roles = {row["rolname"]: row for row in catalog["roles"]}
    assert set(roles) == set(CLARIDEZ_ROLES)
    assert all(not row["rolsuper"] for row in roles.values())
    assert all(not row["rolcreaterole"] for row in roles.values())
    assert all(not row["rolbypassrls"] for row in roles.values())
    assert roles["claridez_app"]["rolcreatedb"] is False
    assert roles["claridez_migrator"]["rolcreatedb"] is False
    assert roles["claridez_test_runner"]["rolcreatedb"] is True
    evidence.record("table_owners", "claridez_migrator")
    evidence.record("claridez_roles_bypassrls", False)


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE claridez_spike_rls_record DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE claridez_spike_rls_record ADD COLUMN forbidden text",
        "DROP POLICY spike_rls_record_tenant_policy ON claridez_spike_rls_record",
    ],
)
def test_application_role_cannot_change_tables_policies_or_grants(statement: str) -> None:
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connections["default"].cursor() as cursor,
    ):
        cursor.execute(statement)


def test_application_role_cannot_grant_privileges(evidence: EvidenceRecorder) -> None:
    with connections["default"].cursor() as cursor:
        cursor.execute("GRANT SELECT ON claridez_spike_rls_record TO PUBLIC")
        cursor.execute(
            "SELECT has_table_privilege('public', 'claridez_spike_rls_record', 'SELECT')"
        )
        assert cursor.fetchone()[0] is False
    evidence.record("application_grant", "no_privilege_granted")


def test_enable_and_force_rls_change_owner_behavior(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    migrator = connections["migrator"]
    with migrator.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM claridez_spike_rls_record")
        owner_without_force = int(cursor.fetchone()[0])
        cursor.execute("ALTER TABLE claridez_spike_rls_record FORCE ROW LEVEL SECURITY")
        cursor.execute("SELECT count(*) FROM claridez_spike_rls_record")
        owner_with_force_no_context = int(cursor.fetchone()[0])
    assert owner_without_force == 2
    assert owner_with_force_no_context == 0
    with (
        tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a), using="migrator"),
        migrator.cursor() as cursor,
    ):
        cursor.execute("SELECT count(*) FROM claridez_spike_rls_record")
        assert cursor.fetchone()[0] == 1
    with migrator.cursor() as cursor:
        cursor.execute("ALTER TABLE claridez_spike_rls_record NO FORCE ROW LEVEL SECURITY")
    evidence.record("rls_owner_enable_only_rows", owner_without_force)
    evidence.record("rls_owner_force_without_context_rows", owner_with_force_no_context)
    evidence.record("rls_force_with_context_rows", 1)


def test_data_migration_behavior_with_and_without_context(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    migrator = connections["migrator"]
    with migrator.cursor() as cursor:
        cursor.execute("ALTER TABLE claridez_spike_rls_record NO FORCE ROW LEVEL SECURITY")
        cursor.execute("UPDATE claridez_spike_rls_record SET payload = 'owner-bypass'")
        without_force_rows = cursor.rowcount
        cursor.execute("ALTER TABLE claridez_spike_rls_record FORCE ROW LEVEL SECURITY")
        cursor.execute("UPDATE claridez_spike_rls_record SET payload = 'missing-context'")
        forced_without_context_rows = cursor.rowcount
    with (
        tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a), using="migrator"),
        migrator.cursor() as cursor,
    ):
        cursor.execute("UPDATE claridez_spike_rls_record SET payload = 'scoped-migration'")
        forced_with_context_rows = cursor.rowcount
    with migrator.cursor() as cursor:
        cursor.execute("ALTER TABLE claridez_spike_rls_record NO FORCE ROW LEVEL SECURITY")
    assert without_force_rows == 2
    assert forced_without_context_rows == 0
    assert forced_with_context_rows == 1
    evidence.record("data_migration_enable_without_context_rows", without_force_rows)
    evidence.record("data_migration_force_without_context_rows", forced_without_context_rows)
    evidence.record("data_migration_force_with_context_rows", forced_with_context_rows)


def test_migrator_can_run_ddl_but_application_cannot(evidence: EvidenceRecorder) -> None:
    with connections["migrator"].cursor() as cursor:
        cursor.execute("CREATE TABLE claridez_spike_transient_ddl (id integer)")
        cursor.execute("DROP TABLE claridez_spike_transient_ddl")
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connections["default"].cursor() as cursor,
    ):
        cursor.execute("CREATE TABLE claridez_spike_forbidden_ddl (id integer)")
    evidence.record("migrator_ddl", "allowed")
    evidence.record("application_ddl", "rejected")


def test_non_owner_test_runner_obeys_rls(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    assert RlsTechnicalRecord.spike_unfiltered_objects.using("test_runner").count() == 0
    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.b), using="test_runner"):
        assert RlsTechnicalRecord.spike_unfiltered_objects.using("test_runner").count() == 1
    evidence.record("test_runner_rls", "non_owner_policy_applied")


def test_process_without_tenant_is_safe_only_when_rls_exists(evidence: EvidenceRecorder) -> None:
    app_only_rows = ApplicationTechnicalRecord.spike_unfiltered_objects.count()
    rls_rows = RlsTechnicalRecord.spike_unfiltered_objects.count()
    assert app_only_rows == 2
    assert rls_rows == 0
    evidence.record("technical_process_without_tenant_app_only_rows", app_only_rows)
    evidence.record("technical_process_without_tenant_rls_rows", rls_rows)
