"""Conexiones reutilizadas, cierre, concurrencia y fault injection de sesión."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connections

from spikes.tenancy.context import ValidatedTechnicalOrganization, tenant_scope
from spikes.tenancy.models import RlsTechnicalRecord
from spikes.tenancy.tests.conftest import EvidenceRecorder, Organizations

pytestmark = pytest.mark.tenancy_spike


def _pid_and_context(alias: str) -> tuple[int, str | None]:
    with connections[alias].cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid(), current_setting('claridez.organization_id', true)")
        pid, context = cursor.fetchone()
        return int(pid), None if context is None else str(context)


def test_connection_modes_and_persistent_reuse(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    assert connections["default"].settings_dict["CONN_MAX_AGE"] == 0
    assert connections["persistent"].settings_dict["CONN_MAX_AGE"] == 60

    observed: list[dict[str, object]] = []
    for organization in (synthetic_rows.a, synthetic_rows.b):
        with tenant_scope(ValidatedTechnicalOrganization(organization), using="persistent"):
            pid, context = _pid_and_context("persistent")
            assert context == str(organization)
            assert RlsTechnicalRecord.spike_unfiltered_objects.using("persistent").count() == 1
            observed.append({"pid": pid, "phase": "scoped"})
        pid_after, context_after = _pid_and_context("persistent")
        assert context_after == ""
        observed.append({"pid": pid_after, "phase": "cleared"})
    assert len({row["pid"] for row in observed}) == 1
    assert RlsTechnicalRecord.spike_unfiltered_objects.using("persistent").count() == 0
    evidence.record("persistent_connection", observed)
    evidence.record("persistent_a_to_b", "isolated_and_cleared")
    evidence.record("persistent_a_to_none", "zero_rows")


def test_close_and_reopen_starts_without_context(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a), using="persistent"):
        first_pid, _ = _pid_and_context("persistent")
    connections["persistent"].close()
    second_pid, context = _pid_and_context("persistent")
    assert context in {None, ""}
    evidence.record(
        "connection_reopen",
        {"context": "absent", "backend_pid_changed_observation": first_pid != second_pid},
    )


def test_conn_max_age_zero_closes_at_request_boundary(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    with tenant_scope(ValidatedTechnicalOrganization(synthetic_rows.a)):
        first_pid, _ = _pid_and_context("default")
    close_old_connections()
    second_pid, context = _pid_and_context("default")
    assert context in {None, ""}
    evidence.record(
        "conn_max_age_zero",
        {"context": "absent", "backend_pid_changed_observation": first_pid != second_pid},
    )


def test_session_context_fault_injection_leaks_on_reused_connection(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    connection = connections["persistent"]
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('claridez.organization_id', %s, false)",
                (str(synthetic_rows.a),),
            )
            cursor.execute("SELECT count(*) FROM claridez_spike_rls_record")
            assert cursor.fetchone()[0] == 1
        # Simula el siguiente consumidor de la misma sesión sin establecer contexto.
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM claridez_spike_rls_record")
            leaked_rows = int(cursor.fetchone()[0])
        assert leaked_rows == 1
        evidence.record("unsafe_session_context", "contaminated_next_consumer")
        evidence.record("unsafe_session_potential_rows", leaked_rows)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET claridez.organization_id")
        connection.close()


def test_two_threads_keep_independent_connections(
    synthetic_rows: Organizations, evidence: EvidenceRecorder
) -> None:
    barrier = Barrier(2)

    def inspect(organization_id):  # type: ignore[no-untyped-def]
        alias = "persistent"
        try:
            with tenant_scope(ValidatedTechnicalOrganization(organization_id), using=alias):
                barrier.wait(timeout=5)
                pid, context = _pid_and_context(alias)
                rows = RlsTechnicalRecord.spike_unfiltered_objects.using(alias).count()
                return pid, context, rows
        finally:
            connections[alias].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(inspect, (synthetic_rows.a, synthetic_rows.b)))
    assert all(
        context == str(organization) and rows == 1
        for (_, context, rows), organization in zip(
            results, (synthetic_rows.a, synthetic_rows.b), strict=True
        )
    )
    assert results[0][0] != results[1][0]
    evidence.record("concurrent_threads", "independent_connections_and_contexts")
    evidence.record("concurrent_backend_pid_count", len({result[0] for result in results}))
