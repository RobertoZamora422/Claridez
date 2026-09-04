"""P15 sobre PostgreSQL real: no mocks de RLS, ledgers, claims ni publicación."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from threading import Barrier
from time import sleep
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from django.utils import timezone

from claridez.analytics import jobs, services
from claridez.analytics.errors import AnalyticsError
from claridez.analytics.models import (
    ExportArtifact,
    ExportAttempt,
    ExportJob,
    ReportExecution,
    ReportRevision,
)
from claridez.analytics.query import MetricSelection, execute_query
from claridez.analytics.registry import METRICS
from claridez.analytics.renderers import render_csv
from claridez.analytics.storage import LocalAnalyticsStorage, object_key
from claridez.finance.services import create_period
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied
from claridez.organizations.models import Membership
from claridez.organizations.tenant_scope import authorized_tenant_scope, infrastructure_tenant_scope
from tests.integration.test_p14_postgresql import _app_connection
from tests.test_p8_scheduling import _owner

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
SECURITY = import_module("claridez.analytics.migrations.0002_tenant_integrity")
TABLES = cast(tuple[str, ...], SECURITY.TABLES)
APPEND_ONLY = cast(tuple[str, ...], SECURITY.APPEND_ONLY)


def _selection() -> tuple[MetricSelection, ...]:
    return (
        MetricSelection(
            "request_created_count",
            period_start=timezone.now() - timedelta(days=30),
            period_end=timezone.now() - timedelta(days=1),
        ),
    )


def _execute(actor: User, oid: UUID) -> dict[str, object]:
    return services.run_report(
        actor,
        oid,
        idempotency_key=uuid4(),
        timezone_name="America/Guayaquil",
        selections=_selection(),
    )


def _enqueue(actor: User, oid: UUID) -> UUID:
    execution = _execute(actor, oid)
    job = services.create_export(
        actor, oid, UUID(str(execution["id"])), format="csv", idempotency_key=uuid4()
    )
    return UUID(str(job["id"]))


def test_all_private_tables_rls_privileges_and_no_bypassrls() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(%s)",
            [list(TABLES)],
        )
        assert sorted(cursor.fetchall()) == sorted((table, True, True) for table in TABLES)
        for table in TABLES:
            cursor.execute(
                "SELECT has_table_privilege('claridez_app', %s, 'SELECT'), "
                "has_table_privilege('claridez_app', %s, 'INSERT'), "
                "has_table_privilege('claridez_app', %s, 'UPDATE'), "
                "has_table_privilege('claridez_app', %s, 'DELETE'), "
                "has_table_privilege('claridez_app', %s, 'TRUNCATE')",
                [table] * 5,
            )
            assert cursor.fetchone() == (True, True, table not in APPEND_ONLY, False, False)
        cursor.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'claridez_app'")
        assert cursor.fetchone() == (False,)


def test_known_uuid_negative_sql_and_orm_as_runtime_role_in_two_tenants() -> None:
    first, a = _owner("p15-rls-a")
    second, b = _owner("p15-rls-b")
    record = _execute(first, a)
    record_id = UUID(str(record["id"]))
    with _app_connection() as app, app.cursor() as cursor:
        cursor.execute("SELECT id FROM analytics_reportexecution WHERE id = %s", [record_id])
        assert cursor.fetchall() == []
        cursor.execute("SELECT set_config('claridez.organization_id', %s, false)", [str(b)])
        cursor.execute("SELECT id FROM analytics_reportexecution WHERE id = %s", [record_id])
        assert cursor.fetchall() == []
        cursor.execute("SELECT set_config('claridez.organization_id', %s, false)", [str(a)])
        cursor.execute("SELECT id FROM analytics_reportexecution WHERE id = %s", [record_id])
        assert cursor.fetchall() == [(record_id,)]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("DELETE FROM analytics_reportexecution WHERE id = %s", [record_id])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                "UPDATE analytics_reportexecution SET timezone_name = 'UTC' WHERE id = %s",
                [record_id],
            )
    with (
        authorized_tenant_scope(second, b, Capability.ANALYTICS_EXECUTE_REPORT),
        connection.cursor() as cursor,
    ):
        cursor.execute("SET LOCAL ROLE claridez_app")
        assert not ReportExecution.objects.filter(pk=record_id).exists()
    with pytest.raises(TenantAccessDenied):
        services.execution_detail(second, a, record_id)
    with pytest.raises(AnalyticsError):
        services.execution_detail(second, b, record_id)


def test_report_revisions_append_only_and_interactive_query_is_not_execution() -> None:
    owner, oid = _owner("p15-revisions")
    selection = _selection()
    services.dashboard_query(owner, oid, timezone_name="UTC", selections=selection)
    report = services.create_report(
        owner, oid, title="Métrica", visibility="private", timezone_name="UTC", selections=selection
    )
    revised = services.revise_report(
        owner,
        oid,
        UUID(str(report["id"])),
        expected_revision=1,
        title="Métrica revisada",
        visibility="organization",
        timezone_name="UTC",
        selections=selection,
    )
    assert revised["revision"] == 2
    with authorized_tenant_scope(owner, oid, Capability.ANALYTICS_EXECUTE_REPORT):
        assert ReportExecution.objects.count() == 0
        assert list(ReportRevision.objects.order_by("number").values_list("title", flat=True)) == [
            "Métrica",
            "Métrica revisada",
        ]
        with pytest.raises(IntegrityError), transaction.atomic():
            ReportRevision.objects.filter(pk=UUID(str(report["revision_id"]))).update(
                title="Sobrescrito"
            )
    with pytest.raises(AnalyticsError):
        services.revise_report(
            owner,
            oid,
            UUID(str(report["id"])),
            expected_revision=1,
            title="Vieja",
            visibility="private",
            timezone_name="UTC",
            selections=selection,
        )


def test_shared_visibility_does_not_grant_source_permissions() -> None:
    owner, oid = _owner("p15-shared")
    commercial = User.objects.create_user(
        email="p15-member@example.test",
        password="synthetic-p15-password",
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    Membership.objects.create(
        organization_id=oid,
        user=commercial,
        role=Membership.Role.COMMERCIAL,
        status=Membership.Status.ACTIVE,
    )
    now = timezone.now()
    selection = (
        MetricSelection(
            "confirmed_sale_amount",
            dimensions=("currency",),
            period_start=now - timedelta(days=2),
            period_end=now - timedelta(days=1),
        ),
    )
    report = services.create_report(
        owner,
        oid,
        title="Finance",
        visibility="organization",
        timezone_name="UTC",
        selections=selection,
    )
    assert services.list_reports(commercial, oid) == ()
    with pytest.raises(AuthorizationDenied):
        services.run_report(
            commercial,
            oid,
            idempotency_key=uuid4(),
            report_revision_id=UUID(str(report["revision_id"])),
        )
    with pytest.raises(AuthorizationDenied):
        services.create_report(
            commercial,
            oid,
            title="Compartido",
            visibility="organization",
            timezone_name="UTC",
            selections=_selection(),
        )


def test_all_53_ports_materialize_in_one_real_tenant_without_orm_results() -> None:
    owner, oid = _owner("p15-catalog-real")
    period = create_period(
        owner,
        oid,
        starts_on=date(2020, 1, 1),
        ends_on=date(2020, 2, 1),
        label="Periodo sintético",
        idempotency_key=uuid4(),
    )
    now = timezone.now()
    requests = tuple(
        MetricSelection(
            row.metric_id,
            dimensions=row.required_dimensions,
            period_start=now - timedelta(days=3)
            if row.temporal_mode.value in {"F", "SI", "C"}
            else None,
            period_end=now - timedelta(days=1)
            if row.temporal_mode.value in {"F", "SI", "C"}
            else None,
            as_of_at=None if row.temporal_mode.value == "F" else now,
            operational_period_id=period.pk if row.temporal_mode.value == "FP" else None,
        )
        for row in METRICS
    )
    with authorized_tenant_scope(owner, oid, Capability.ANALYTICS_READ_DASHBOARD) as auth:
        output = execute_query(
            auth,
            requests,
            timezone_name="America/Guayaquil",
            capability=Capability.ANALYTICS_READ_DASHBOARD,
        )
    assert len(output.metrics) == 53
    for row in output.metrics:
        assert isinstance(row.result.points, tuple)
        assert row.result.source_metric_version == 1


def test_execution_idempotency_and_private_export_equal_frozen_result(tmp_path: Path) -> None:
    owner, oid = _owner("p15-export-exact")
    key, selection = uuid4(), _selection()
    first = services.run_report(
        owner, oid, idempotency_key=key, timezone_name="UTC", selections=selection
    )
    replay = services.run_report(
        owner, oid, idempotency_key=key, timezone_name="UTC", selections=selection
    )
    assert first == replay
    job = services.create_export(
        owner, oid, UUID(str(first["id"])), format="csv", idempotency_key=uuid4()
    )
    with override_settings(ANALYTICS_STORAGE_ROOT=tmp_path):
        assert jobs.work_once(oid)
        content, format_name, digest = services.download_export(owner, oid, UUID(str(job["id"])))
    assert format_name == "csv" and len(digest) == 64
    assert b"request_created_count" in content
    with authorized_tenant_scope(owner, oid, Capability.ANALYTICS_CREATE_EXPORT):
        assert list(
            ExportAttempt.objects.order_by("created_at").values_list("event", flat=True)
        ) == ["claimed", "completed"]
        assert ExportArtifact.objects.count() == 1
        assert ReportExecution.objects.count() == 1
    User.objects.filter(pk=owner.pk).update(status=User.Status.SUSPENDED, is_active=False)
    with override_settings(ANALYTICS_STORAGE_ROOT=tmp_path), pytest.raises(TenantAccessDenied):
        services.download_export(owner, oid, UUID(str(job["id"])))


def test_history_keyset_pages_and_foreign_cursor_are_tenant_aware() -> None:
    owner, oid = _owner("p15-page-a")
    other, foreign_oid = _owner("p15-page-b")
    for title in ("Primero", "Segundo", "Tercero"):
        services.create_report(
            owner,
            oid,
            title=title,
            visibility="private",
            timezone_name="UTC",
            selections=_selection(),
        )
    first = services.history_page(owner, oid, "reports", limit=2)
    second = services.history_page(owner, oid, "reports", limit=2, cursor=str(first["next_cursor"]))
    initial_rows = cast(list[dict[str, object]], first["results"])
    remaining_rows = cast(list[dict[str, object]], second["results"])
    assert len(initial_rows) == 2 and len(remaining_rows) == 1
    assert {row["id"] for row in initial_rows}.isdisjoint(row["id"] for row in remaining_rows)
    assert second["next_cursor"] is None
    with pytest.raises(ValueError, match="invalid_history_cursor"):
        services.history_page(other, foreign_oid, "reports", cursor=str(first["next_cursor"]))


def test_concurrent_claim_only_once_and_only_requested_organization() -> None:
    owner, oid = _owner("p15-claim-a")
    other, second = _owner("p15-claim-b")
    target, foreign = _enqueue(owner, oid), _enqueue(other, second)
    barrier = Barrier(2)

    def claim() -> jobs.JobClaim | None:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            with infrastructure_tenant_scope(oid, purpose="analytics_worker"):
                return jobs.claim_next(oid)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: claim(), range(2)))
    assert [row.job_id for row in claimed if row] == [target]
    with authorized_tenant_scope(other, second, Capability.ANALYTICS_CREATE_EXPORT):
        assert ExportJob.objects.get(pk=foreign).state == "queued"


def test_expired_lease_stale_worker_cannot_publish(
    tmp_path: Path,
) -> None:
    owner, oid = _owner("p15-reclaim")
    _enqueue(owner, oid)
    with infrastructure_tenant_scope(oid, purpose="analytics_worker"):
        claim = jobs.claim_next(oid)
    assert claim is not None
    # Reloj de aplicación simula el paso del lease; no reescribe un ledger histórico.
    from unittest.mock import patch

    with patch(
        "claridez.analytics.jobs.timezone.now",
        return_value=claim.lease_expires_at + timedelta(seconds=1),
    ):
        jobs.process_claim(claim, storage=LocalAnalyticsStorage(tmp_path))
    assert not any(tmp_path.rglob("*.csv"))
    with authorized_tenant_scope(owner, oid, Capability.ANALYTICS_CREATE_EXPORT):
        assert ExportArtifact.objects.count() == 0


def test_revoked_membership_before_generation_fails_without_bytes(tmp_path: Path) -> None:
    owner, oid = _owner("p15-revoked")
    job_id = _enqueue(owner, oid)
    with infrastructure_tenant_scope(oid, purpose="analytics_worker"):
        claim = jobs.claim_next(oid)
    assert claim is not None
    # Desactivación global de usuario preserva la membresía y su metadata histórica.
    User.objects.filter(pk=owner.pk).update(status=User.Status.SUSPENDED, is_active=False)
    jobs.process_claim(claim, storage=LocalAnalyticsStorage(tmp_path))
    with infrastructure_tenant_scope(oid, purpose="analytics_worker"):
        assert ExportJob.objects.get(pk=job_id).state == "terminal"
        assert ExportArtifact.objects.count() == 0
    assert not any(tmp_path.rglob("*.csv"))


def test_crash_after_write_once_publication_reclaims_and_reuses_identical_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, oid = _owner("p15-publication-crash")
    job_id = _enqueue(owner, oid)
    storage = LocalAnalyticsStorage(tmp_path)
    # La prueba aísla el crash en publicación; los bytes vienen del renderer real.
    monkeypatch.setattr(
        jobs, "render_bounded", lambda dataset, *_args, **_kwargs: render_csv(dataset)
    )
    finalize = jobs._finalize

    def crash(*_args: object) -> bool:
        raise RuntimeError("simulated_process_crash_after_publication")

    with override_settings(ANALYTICS_EXPORT_LEASE_SECONDS=3):
        with infrastructure_tenant_scope(oid, purpose="analytics_worker"):
            first = jobs.claim_next(oid)
        assert first is not None
        monkeypatch.setattr(jobs, "_finalize", crash)
        with pytest.raises(RuntimeError, match="simulated_process_crash"):
            jobs.process_claim(first, storage=storage)
        path = tmp_path / object_key(oid, first.artifact_identity, "csv")
        original_bytes = path.read_bytes()
        with infrastructure_tenant_scope(oid, purpose="analytics_worker"):
            assert ExportArtifact.objects.count() == 0
            assert ExportJob.objects.get(pk=job_id).state == "running"
        sleep(max(0, (first.lease_expires_at - timezone.now()).total_seconds()) + 0.1)
        monkeypatch.setattr(jobs, "_finalize", finalize)
        with infrastructure_tenant_scope(oid, purpose="analytics_worker"):
            second = jobs.claim_next(oid)
        assert second is not None and second.lease_token != first.lease_token
        assert second.attempt_number == 2
        jobs.process_claim(second, storage=storage)
    assert path.read_bytes() == original_bytes
    with authorized_tenant_scope(owner, oid, Capability.ANALYTICS_CREATE_EXPORT):
        assert ExportJob.objects.get(pk=job_id).state == "completed"
        assert ExportArtifact.objects.count() == 1
        assert sorted(ExportAttempt.objects.values_list("event", flat=True)) == [
            "claimed",
            "claimed",
            "completed",
            "reclaimed",
        ]


def test_rival_bytes_at_the_logical_key_fail_terminally_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, oid = _owner("p15-rival-hash")
    job_id = _enqueue(owner, oid)
    storage = LocalAnalyticsStorage(tmp_path)
    monkeypatch.setattr(
        jobs, "render_bounded", lambda dataset, *_args, **_kwargs: render_csv(dataset)
    )
    with infrastructure_tenant_scope(oid, purpose="analytics_worker"):
        claim = jobs.claim_next(oid)
    assert claim is not None
    rival = storage.publish(oid, claim.artifact_identity, "csv", b"rival immutable bytes")
    jobs.process_claim(claim, storage=storage)
    assert storage.read(oid, claim.artifact_identity, rival) == b"rival immutable bytes"
    with authorized_tenant_scope(owner, oid, Capability.ANALYTICS_CREATE_EXPORT):
        job = ExportJob.objects.get(pk=job_id)
        assert job.state == "terminal"
        assert job.last_error_code == "artifact_integrity_failure"
        assert ExportArtifact.objects.count() == 0


def test_migration_from_p14_is_additive_and_does_not_fabricate_history() -> None:
    def restore() -> None:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    try:
        executor = MigrationExecutor(connection)
        targets = [
            node
            for node in executor.loader.graph.leaf_nodes()
            if node[0] not in {"analytics", "commercial", "operations", "resources", "scheduling"}
        ]
        targets += [
            ("analytics", None),
            ("commercial", "0008_delete_reservation"),
            ("scheduling", "0009_allow_terminal_operational_successors"),
            ("operations", "0018_incident_follow_up_integrity"),
            ("resources", "0006_preserve_custody_interval_guard"),
        ]
        executor.migrate(targets)
        assert not any(
            table.startswith("analytics_") for table in connection.introspection.table_names()
        )
        restore()
        with connection.cursor() as cursor:
            for table in TABLES:
                cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
                assert cursor.fetchone() == (0,)
    finally:
        restore()
