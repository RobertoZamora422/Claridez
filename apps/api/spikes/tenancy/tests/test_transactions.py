"""Semántica de SET LOCAL, scopes anidados, commit, rollback y savepoints."""

from __future__ import annotations

import pytest
from django.db import connections, transaction

from spikes.tenancy.context import (
    TenantScopeError,
    ValidatedTechnicalOrganization,
    current_organization_id,
    tenant_scope,
)
from spikes.tenancy.models import RlsTechnicalRecord
from spikes.tenancy.tests.conftest import EvidenceRecorder, Organizations

pytestmark = pytest.mark.tenancy_spike


def _database_context(using: str = "default") -> str:
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT current_setting('claridez.organization_id', true)")
        return str(cursor.fetchone()[0])


def test_set_local_outside_explicit_transaction_has_no_lifetime(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    connection = connections["default"]
    assert connection.get_autocommit()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, true)",
            (str(synthetic_rows.a),),
        )
    assert _database_context() == ""
    evidence.record("set_local_in_autocommit", "cleared_after_statement")


@pytest.mark.parametrize("using", ["default", "persistent"])
def test_scope_commit_and_rollback_clear_context(
    using: str, synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    scope = ValidatedTechnicalOrganization(synthetic_rows.a)
    with tenant_scope(scope, using=using):
        assert current_organization_id() == synthetic_rows.a
        assert _database_context(using) == str(synthetic_rows.a)
    assert current_organization_id() is None
    assert _database_context(using) == ""

    with pytest.raises(RuntimeError), tenant_scope(scope, using=using):
        assert RlsTechnicalRecord.spike_unfiltered_objects.using(using).count() == 1
        raise RuntimeError("synthetic rollback")
    assert current_organization_id() is None
    assert _database_context(using) == ""
    evidence.record(f"transaction_commit_cleanup_{using}", "cleared")
    evidence.record(f"transaction_rollback_cleanup_{using}", "cleared")
    evidence.record(f"transaction_exception_cleanup_{using}", "cleared")


def test_nested_scope_reuses_same_tenant_and_rejects_change_before_sql(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    executed: list[str] = []

    def capture(execute, sql, params, many, context):  # type: ignore[no-untyped-def]
        executed.append(str(sql))
        return execute(sql, params, many, context)

    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)):
        with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)):
            assert current_organization_id() == synthetic_rows.a
        with (
            connections["default"].execute_wrapper(capture),
            pytest.raises(TenantScopeError),
            tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.b)),
        ):
            pass
        assert executed == []
    evidence.record("nested_same_tenant", "context_reused")
    evidence.record("nested_different_tenant", "rejected_before_sql")


def test_savepoint_rollback_restores_previous_set_local_value(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    connection = connections["default"]
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('claridez.organization_id', %s, true)",
                (str(synthetic_rows.a),),
            )
        savepoint = transaction.savepoint()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('claridez.organization_id', %s, true)",
                (str(synthetic_rows.b),),
            )
        assert _database_context() == str(synthetic_rows.b)
        transaction.savepoint_rollback(savepoint)
        assert _database_context() == str(synthetic_rows.a)
    assert _database_context() == ""
    evidence.record("savepoint_rollback", "restored_outer_value")


def test_inner_atomic_rollback_does_not_break_outer_scope(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)):
        with pytest.raises(RuntimeError), transaction.atomic():
            assert _database_context() == str(synthetic_rows.a)
            raise RuntimeError("synthetic inner rollback")
        assert _database_context() == str(synthetic_rows.a)
        assert RlsTechnicalRecord.spike_unfiltered_objects.count() == 1
    evidence.record("nested_savepoint_exception", "outer_scope_preserved")
