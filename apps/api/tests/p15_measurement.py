"""Presupuestos de aceptación e instrumentación local; nunca contienen cifras simuladas.

El profiling EXPLAIN es una pasada separada: no contamina las muestras de latencia.
No persiste SQL, parámetros, identificadores de personas ni cuerpos de peticiones.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any

from django.db import connection


@dataclass(frozen=True, slots=True)
class Budget:
    sql: int
    payload_bytes: int
    p95_ms: int = 500


# Incluyen transacción, sesión, actor/membership, contexto RLS y lectura del resultado.
BUDGETS = {
    "catalog": Budget(24, 128 * 1024),
    "dashboard": Budget(110, 512 * 1024),
    "reports": Budget(24, 512 * 1024),
    "revisions": Budget(24, 512 * 1024),
    "executions": Budget(24, 512 * 1024),
    "exports": Budget(24, 512 * 1024),
    "execution_create": Budget(130, 520 * 1024),
    "execution_detail": Budget(50, 520 * 1024),
    "report_create": Budget(36, 64 * 1024),
    "report_revise": Budget(40, 64 * 1024),
    "report_archive": Budget(32, 64 * 1024),
    "export_create": Budget(36, 8 * 1024),
    "export_status": Budget(24, 8 * 1024),
    "export_download": Budget(36, 20 * 1024 * 1024),
}
CONCURRENT_CLIENTS = 8
CONCURRENT_EXPORTS = 2
SAMPLES_PER_CLIENT = 25
WARMUPS_PER_CLIENT = 3
MAX_EXPORT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class Sample:
    elapsed_ms: float
    sql_count: int
    payload_bytes: int


def summarize(samples: tuple[Sample, ...]) -> dict[str, float | int]:
    if not samples or any(
        not math.isfinite(row.elapsed_ms)
        or row.elapsed_ms < 0
        or row.sql_count < 0
        or row.payload_bytes < 0
        for row in samples
    ):
        raise ValueError("invalid_performance_samples")
    ordered = sorted(row.elapsed_ms for row in samples)
    return {
        "samples": len(samples),
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "max_ms": ordered[-1],
        "qmax": max(row.sql_count for row in samples),
        "payload_max_bytes": max(row.payload_bytes for row in samples),
    }


def assert_budget(name: str, samples: tuple[Sample, ...]) -> dict[str, object]:
    observed = summarize(samples)
    budget = BUDGETS[name]
    assert observed["qmax"] <= budget.sql, (name, "qmax", observed, budget)
    assert observed["payload_max_bytes"] <= budget.payload_bytes, (
        name,
        "payload",
        observed,
        budget,
    )
    assert observed["p95_ms"] < budget.p95_ms, (name, "p95", observed, budget)
    return {"route": name, "observed": observed, "budget": asdict(budget)}


class SQLProbe:
    def __init__(self, *, explain: bool = False) -> None:
        self.count = 0
        self.explain = explain
        self.explanations: list[dict[str, object]] = []
        self._seen: set[str] = set()
        self._inside_explain = False

    def __call__(
        self,
        execute: Callable[..., Any],
        sql: str,
        params: Any,
        many: bool,
        context: dict[str, Any],
    ) -> Any:
        if self._inside_explain:
            return execute(sql, params, many, context)
        self.count += 1
        result = execute(sql, params, many, context)
        owner_match = re.search(
            r'\bFROM\s+"(commercial|crm|scheduling|operations|people|receivables|finance|resources|analytics)_',
            sql,
            re.IGNORECASE,
        )
        if self.explain and not many and sql.lstrip().upper().startswith("SELECT ") and owner_match:
            digest = hashlib.sha256(sql.encode()).hexdigest()
            if digest not in self._seen:
                self._seen.add(digest)
                self._inside_explain = True
                try:
                    # Mismo scope/GUC/rol y parámetros, todavía dentro del tenant real.
                    with connection.cursor() as cursor:
                        cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
                        raw = cursor.fetchone()[0][0]
                    # Filter/Output/Index Cond pueden contener literales identificables.
                    self.explanations.append(
                        {
                            "owner": owner_match[1].lower(),
                            "sql_sha256": digest,
                            "planning_ms": raw["Planning Time"],
                            "execution_ms": raw["Execution Time"],
                            "plan": _safe_plan(raw["Plan"]),
                        }
                    )
                finally:
                    self._inside_explain = False
        return result


def _safe_plan(node: dict[str, Any]) -> dict[str, object]:
    keys = (
        "Node Type",
        "Relation Name",
        "Index Name",
        "Plan Rows",
        "Actual Rows",
        "Actual Loops",
        "Actual Total Time",
        "Shared Hit Blocks",
        "Shared Read Blocks",
        "Temp Read Blocks",
        "Temp Written Blocks",
    )
    result: dict[str, object] = {key: node[key] for key in keys if key in node}
    result["Plans"] = [_safe_plan(child) for child in node.get("Plans", [])]
    return result


def measure(operation: Callable[[], bytes]) -> Sample:
    probe = SQLProbe()
    with connection.execute_wrapper(probe):
        start = perf_counter()
        payload = operation()
        elapsed_ms = (perf_counter() - start) * 1000
    return Sample(elapsed_ms, probe.count, len(payload))
