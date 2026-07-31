"""Medición local secundaria, pequeña y reproducible, con planes resumidos."""

from __future__ import annotations

import os
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = API_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "spikes.tenancy.settings")

import django  # noqa: E402

django.setup()

from django.db import connections  # noqa: E402

from spikes.tenancy.context import ValidatedTechnicalOrganization, tenant_scope  # noqa: E402

BENCHMARK_ORGANIZATION_A = uuid.UUID("33333333-3333-4333-8333-333333333333")
BENCHMARK_ORGANIZATION_B = uuid.UUID("44444444-4444-4444-8444-444444444444")
ROWS_PER_ORGANIZATION = 1_000
WARMUP_ITERATIONS = 20
MEASURED_ITERATIONS = 100


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[round(0.95 * (len(ordered) - 1))]


def _prepare_synthetic_data() -> None:
    rows: list[tuple[uuid.UUID, uuid.UUID, str, str]] = []
    for organization, prefix in (
        (BENCHMARK_ORGANIZATION_A, "a"),
        (BENCHMARK_ORGANIZATION_B, "b"),
    ):
        rows.extend(
            (uuid.uuid4(), organization, f"bench-{prefix}-{index:04d}", "synthetic")
            for index in range(ROWS_PER_ORGANIZATION)
        )
    migrator = connections["migrator"]
    with migrator.cursor() as cursor:
        cursor.execute(
            "TRUNCATE claridez_spike_app_child, claridez_spike_rls_child, "
            "claridez_spike_app_record, claridez_spike_rls_record, "
            "claridez_spike_rls_default_deny, claridez_spike_organization CASCADE"
        )
        cursor.execute(
            "INSERT INTO claridez_spike_organization (id, label) VALUES (%s, %s), (%s, %s)",
            (
                BENCHMARK_ORGANIZATION_A,
                "benchmark-a",
                BENCHMARK_ORGANIZATION_B,
                "benchmark-b",
            ),
        )
        for table_name in ("claridez_spike_app_record", "claridez_spike_rls_record"):
            cursor.executemany(
                f"INSERT INTO {table_name} (id, organization_id, external_key, payload) "
                "VALUES (%s, %s, %s, %s)",
                rows,
            )
        cursor.execute("ANALYZE claridez_spike_app_record")
        cursor.execute("ANALYZE claridez_spike_rls_record")


def _summarize_plan(raw_plan: list[dict[str, Any]]) -> dict[str, Any]:
    statement = raw_plan[0]
    plan = statement["Plan"]

    def nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
        current = {
            "node_type": node.get("Node Type"),
            "index_name": node.get("Index Name"),
            "actual_rows": node.get("Actual Rows"),
        }
        descendants = [current]
        for child in node.get("Plans", []):
            descendants.extend(nodes(child))
        return descendants

    return {
        "nodes": nodes(plan),
        "shared_hit_blocks": plan.get("Shared Hit Blocks"),
        "shared_read_blocks": plan.get("Shared Read Blocks"),
        "planning_time_ms": statement.get("Planning Time"),
        "execution_time_ms": statement.get("Execution Time"),
    }


def _measure(table_name: str) -> dict[str, Any]:
    query = f"SELECT payload FROM {table_name} WHERE organization_id = %s AND external_key = %s"
    parameters = (BENCHMARK_ORGANIZATION_A, "bench-a-0500")
    timings: list[float] = []
    with (
        tenant_scope(ValidatedTechnicalOrganization(BENCHMARK_ORGANIZATION_A)),
        connections["default"].cursor() as cursor,
    ):
        for _ in range(WARMUP_ITERATIONS):
            cursor.execute(query, parameters)
            cursor.fetchone()
        for _ in range(MEASURED_ITERATIONS):
            started = time.perf_counter_ns()
            cursor.execute(query, parameters)
            cursor.fetchone()
            timings.append((time.perf_counter_ns() - started) / 1_000_000)
        cursor.execute(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}",
            parameters,
        )
        raw_plan = cursor.fetchone()[0]
    return {
        "median_ms": round(statistics.median(timings), 4),
        "p95_ms": round(_percentile_95(timings), 4),
        "iterations": MEASURED_ITERATIONS,
        "warmup_iterations": WARMUP_ITERATIONS,
        "plan": _summarize_plan(raw_plan),
    }


def run_benchmark() -> dict[str, Any]:
    """Medir la misma búsqueda e índices con y sin RLS."""
    _prepare_synthetic_data()
    try:
        application_only = _measure("claridez_spike_app_record")
        application_plus_rls = _measure("claridez_spike_rls_record")
        return {
            "scope": "local_observation_not_production_prediction",
            "rows_per_organization": ROWS_PER_ORGANIZATION,
            "same_schema_indexes_and_query": True,
            "application_only": application_only,
            "application_plus_rls": application_plus_rls,
        }
    finally:
        connections.close_all()


if __name__ == "__main__":
    import json

    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))
