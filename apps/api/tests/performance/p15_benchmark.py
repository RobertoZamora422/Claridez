"""Arnés explícito de carga P15, separado de las pruebas funcionales ordinarias.

Ejecutar por npm run test:p15:performance. No es evidencia hasta que termine sin fallos.
No es LCP ni latencia de red: mide la ruta HTTP Django completa con PostgreSQL/claridez_app.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from django.apps import apps
from django.db import close_old_connections, connection
from django.test import Client, override_settings
from django.utils import timezone

from claridez.analytics import jobs, services
from claridez.analytics.presets import PRESETS
from claridez.analytics.query import selection_payload
from claridez.analytics.storage import LocalAnalyticsStorage
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.models import Membership
from claridez.organizations.tenant_scope import authorized_tenant_scope
from tests.p15_dataset import REPRESENTATIVE, Dataset, build_dataset
from tests.p15_measurement import (
    CONCURRENT_CLIENTS,
    CONCURRENT_EXPORTS,
    MAX_EXPORT_SECONDS,
    SAMPLES_PER_CLIENT,
    WARMUPS_PER_CLIENT,
    Sample,
    SQLProbe,
    assert_budget,
    measure,
    summarize,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

# Solo inspección de test: los módulos productivos Analytics no consultan modelos de otra fuente.
VOLUMES = {
    "people": "people.Person",
    "requests": "commercial.EventRequest",
    "interactions": "crm.Interaction",
    "tasks": "crm.FollowUpTask",
    "issued_quotes": "commercial.QuotationVersion",
    "confirmed_roots": "receivables.ReceivableObligation",
    "preparations": "operations.EventPreparation",
    "payments": "receivables.ReceivedPayment",
    "applications": "receivables.PaymentApplication",
    "obligations": "receivables.ReceivableObligation",
    "finance_periods": "finance.OperationalPeriod",
    "cost_plans": "finance.DirectCostPlanRevision",
    "direct_costs": "finance.ActualDirectCost",
    "variable_expenses": "finance.ExpenseOccurrence",
    "cash_outflows": "finance.OperatingCashMovement",
    "resources": "resources.Resource",
    "receipts": "resources.SupplyReceiptLine",
    "stock_movements": "resources.StockMovement",
    "requirements": "resources.ResourceRequirement",
    "assignments": "resources.ResourceAssignment",
}


def _record_volumes(dataset: Dataset) -> dict[str, int]:
    with authorized_tenant_scope(
        dataset.actor, dataset.organization_id, Capability.ANALYTICS_READ_DASHBOARD
    ):
        observed = {
            name: apps.get_model(label)
            .objects.filter(organization_id=dataset.organization_id)
            .count()
            for name, label in VOLUMES.items()
        }
        observed["accepted_quotes"] = (
            apps.get_model("commercial.QuotationVersion")
            .objects.filter(
                organization_id=dataset.organization_id,
                accepted_at__isnull=False,
            )
            .count()
        )
        observed["execution_completed"] = (
            apps.get_model("operations.EventPreparation")
            .objects.filter(
                organization_id=dataset.organization_id,
                status="completed",
            )
            .count()
        )
    for name, value in observed.items():
        assert value == REPRESENTATIVE.expected[name], (name, value, REPRESENTATIVE.expected[name])
    return observed


def _client(actor: User) -> tuple[Client, str]:
    client = Client(enforce_csrf_checks=True)
    client.force_login(actor)
    csrf = str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])
    return client, csrf


def _dashboard(client: Client, dataset: Dataset, csrf: str, role: str) -> bytes:
    selected = dataset.selections()
    if role != "all_53":
        selected = tuple(row for row in selected if row.metric_id in PRESETS[role])
    result = client.post(
        f"/api/v1/organizations/{dataset.organization_id}/analytics/dashboards/query/",
        data=json.dumps(
            {
                "timezone": "America/Guayaquil",
                "metrics": [selection_payload(row) for row in selected],
            }
        ),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert result.status_code == 200, (result.status_code, result.content)
    return result.content


def _actor(dataset: Dataset, role: str) -> User:
    if role in {"owner", "all_53"}:
        return dataset.actor
    if role == "commercial":
        return dataset.commercial_actor
    actor = User.objects.create_user(
        email=f"p15-{dataset.organization_id}-{role}@example.test",
        password=None,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    Membership.objects.create(
        user=actor,
        organization_id=dataset.organization_id,
        role=role,
        status=Membership.Status.ACTIVE,
    )
    return actor


def test_representative_http_fan_in_qmax_payload_p95_and_explain(
    record_property: Callable[[str, object], None],
    tmp_path: Path,
) -> None:
    datasets = (
        build_dataset("p15-load-a", REPRESENTATIVE),
        build_dataset("p15-load-b", REPRESENTATIVE),
    )
    record_property("dataset_profile", REPRESENTATIVE.name)
    record_property(
        "source_volumes_per_tenant",
        json.dumps([_record_volumes(row) for row in datasets], sort_keys=True),
    )
    # EXPLAIN se conserva incluso si falla después el presupuesto de latencia.
    dataset = datasets[0]
    client, csrf = _client(dataset.actor)
    probe = SQLProbe(explain=True)
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE claridez_app")
    try:
        with connection.execute_wrapper(probe):
            _dashboard(client, dataset, csrf, "all_53")
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
    assert probe.explanations
    record_property("explain_analyze_buffers", json.dumps(probe.explanations, sort_keys=True))
    # Cada perfil se mide por separado para que uno lento no quede oculto en el promedio.
    for role in ("owner", "administrator", "commercial", "operations", "finance", "all_53"):
        actors = tuple(_actor(row, role) for row in datasets)
        barrier = Barrier(CONCURRENT_CLIENTS)

        def worker(
            index: int,
            actors: tuple[User, ...] = actors,
            role: str = role,
            barrier: Barrier = barrier,
        ) -> tuple[Sample, ...]:
            close_old_connections()
            dataset, actor = datasets[index % 2], actors[index % 2]
            try:
                client, csrf = _client(actor)
                with connection.cursor() as cursor:
                    cursor.execute("SET ROLE claridez_app")
                for _ in range(WARMUPS_PER_CLIENT):
                    _dashboard(client, dataset, csrf, role)
                barrier.wait(timeout=60)
                return tuple(
                    measure(lambda: _dashboard(client, dataset, csrf, role))
                    for _ in range(SAMPLES_PER_CLIENT)
                )
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("RESET ROLE")
                close_old_connections()

        with ThreadPoolExecutor(max_workers=CONCURRENT_CLIENTS) as pool:
            samples = tuple(
                sample for group in pool.map(worker, range(CONCURRENT_CLIENTS)) for sample in group
            )
        # Guardar la observación incluso si a continuación falla el presupuesto.
        record_property(f"dashboard_{role}", json.dumps(summarize(samples), sort_keys=True))
        assert_budget("dashboard", samples)
    _exports(datasets, tmp_path, record_property)


def _exports(
    datasets: tuple[Dataset, ...],
    root: Path,
    record_property: Callable[[str, object], None],
) -> None:
    executions = tuple(
        services.run_report(
            row.actor,
            row.organization_id,
            idempotency_key=uuid4(),
            timezone_name="America/Guayaquil",
            selections=row.selections(),
        )
        for row in datasets
    )
    with override_settings(ANALYTICS_STORAGE_ROOT=root):
        for format_name in ("csv", "xlsx"):
            queued = tuple(
                services.create_export(
                    row.actor,
                    row.organization_id,
                    UUID(str(execution["id"])),
                    format=format_name,
                    idempotency_key=uuid4(),
                )
                for row, execution in zip(datasets, executions, strict=True)
            )
            barrier = Barrier(CONCURRENT_EXPORTS)

            def generate(row: Dataset, barrier: Barrier = barrier) -> float:
                close_old_connections()
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SET ROLE claridez_app")
                    barrier.wait(timeout=60)
                    start = perf_counter()
                    assert jobs.work_once(row.organization_id, storage=LocalAnalyticsStorage(root))
                    return perf_counter() - start
                finally:
                    with connection.cursor() as cursor:
                        cursor.execute("RESET ROLE")
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=CONCURRENT_EXPORTS) as pool:
                durations = tuple(pool.map(generate, datasets))
            record_property(f"export_{format_name}_seconds", json.dumps(durations))
            assert all(value < MAX_EXPORT_SECONDS for value in durations)
            for row, job in zip(datasets, queued, strict=True):
                content, actual_format, digest = services.download_export(
                    row.actor,
                    row.organization_id,
                    UUID(str(job["id"])),
                )
                assert actual_format == format_name
                assert hashlib.sha256(content).hexdigest() == digest
                assert len(content) <= 20 * 1024 * 1024


def test_representative_history_pages_are_bounded_and_do_not_scale_with_row_count(
    record_property: Callable[[str, object], None],
) -> None:
    dataset = build_dataset("p15-history-load", REPRESENTATIVE)
    selection = dataset.selections()[:1]
    report_id: UUID | None = None
    for index in range(75):
        report = services.create_report(
            dataset.actor,
            dataset.organization_id,
            title=f"Reporte sintético {index}",
            visibility="private",
            timezone_name="America/Guayaquil",
            selections=selection,
        )
        report_id = UUID(str(report["id"]))
        execution = services.run_report(
            dataset.actor,
            dataset.organization_id,
            idempotency_key=uuid4(),
            timezone_name="America/Guayaquil",
            selections=selection,
        )
        services.create_export(
            dataset.actor,
            dataset.organization_id,
            UUID(str(execution["id"])),
            format="csv",
            idempotency_key=uuid4(),
        )
    assert report_id is not None
    for revision in range(1, 75):
        services.revise_report(
            dataset.actor,
            dataset.organization_id,
            report_id,
            expected_revision=revision,
            title=f"Revisión sintética {revision + 1}",
            visibility="private",
            timezone_name="America/Guayaquil",
            selections=selection,
        )
    client, _ = _client(dataset.actor)
    routes = {
        "catalog": "catalog",
        "reports": "reports",
        "revisions": f"reports/{report_id}/revisions",
        "executions": "executions",
        "exports": "exports",
    }
    for name, path in routes.items():

        def read(path: str = path) -> bytes:
            response = client.get(
                f"/api/v1/organizations/{dataset.organization_id}/analytics/{path}/"
            )
            assert response.status_code == 200, response.content
            return response.content

        with connection.cursor() as cursor:
            cursor.execute("SET ROLE claridez_app")
        try:
            samples = tuple(measure(read) for _ in range(50))
        finally:
            with connection.cursor() as cursor:
                cursor.execute("RESET ROLE")
        record_property(f"{name}_observed", json.dumps(summarize(samples), sort_keys=True))
        record_property(name, json.dumps(assert_budget(name, samples), sort_keys=True))
