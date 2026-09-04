"""Reconstrucción congelada y datasets minimizados: no calcula fórmulas de negocio."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from typing import cast

from claridez.organizations.analytics_contracts import TemporalMode
from claridez.organizations.capabilities import Capability
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.tenant_scope import TenantAuthorization
from claridez.scheduling.public import analytics_scope_fingerprint

from .models import ReportExecution
from .query import _execute_frozen, authorize_selections, output_payload
from .registry import CATALOG_HASH, contract
from .renderers import Cell, Column, ExportDataset
from .services import payload_hash, stored_selections
from .storage import StorageIntegrityError


def _can_requery(row: dict[str, object]) -> bool:
    # recorded_at/created_at no son commit timestamps. Un commit tardío puede hacer visible
    # después un hecho ya registrado al cutoff. Sin una frontera durable de visibilidad, el
    # mínimo snapshot seguro son los puntos de ESTA ejecución (no IDs de todo el ledger).
    # Excepción: un periodo Finance ya cerrado y observado tiene un snapshot único inmutable.
    definition = contract(str(row["metric_id"]), cast(int, row["metric_version"]))
    return (
        definition.owner == "finance"
        and definition.temporal_mode is TemporalMode.FINANCIAL_PERIOD
        and row["provisional"] is False
        and row["coverage"] == "complete"
    )


def renderer_version() -> str:
    """Identidad del renderer efectivo: un despliegue diferente no regenera una key anterior."""
    source = b"\0".join(
        Path(__file__).with_name(name).read_bytes()
        for name in ("exporting.py", "renderers.py", "render_process.py")
    )
    return hashlib.sha256(
        b"analytics-renderer@1:" + source + version("weasyprint").encode()
    ).hexdigest()


def freeze_payload(output: dict[str, object]) -> dict[str, object]:
    """Descarta valores que el ledger fuente puede reproducir honestamente al cutoff."""
    frozen = deepcopy(output)
    for row in cast(list[dict[str, object]], frozen["metrics"]):
        row_hash = payload_hash(row)
        if _can_requery(row):
            row.pop("points")
            row["materialization"] = "source_requery"
        else:
            row["materialization"] = "execution_snapshot"
        row["metric_result_sha256"] = row_hash
    return frozen


def revalidate_execution_scope(auth: TenantAuthorization, execution: ReportExecution) -> None:
    stored_metrics = cast(list[dict[str, object]], execution.result_snapshot["metrics"])
    if any(
        contract(str(row["metric_id"]), cast(int, row["metric_version"])).owner == "scheduling"
        for row in stored_metrics
    ):
        current_scope = analytics_scope_fingerprint(auth)
        if current_scope is not None:
            for row in stored_metrics:
                if (
                    contract(str(row["metric_id"]), cast(int, row["metric_version"])).owner
                    != "scheduling"
                ):
                    continue
                original_scope = cast(dict[str, object], row["provenance"]).get(
                    "authorization_scope_sha256"
                )
                if original_scope != current_scope:
                    raise AuthorizationDenied(
                        "El ámbito de agenda cambió; se requiere una nueva ejecución."
                    )


def reconstruct_execution(
    auth: TenantAuthorization, execution: ReportExecution, capability: Capability
) -> dict[str, object]:
    selections = stored_selections(execution.selection)
    authorize_selections(auth, selections, capability)
    revalidate_execution_scope(auth, execution)
    if execution.catalog_sha256 != CATALOG_HASH:
        raise StorageIntegrityError("execution_catalog_version_unavailable")
    stored = deepcopy(cast(dict[str, object], execution.result_snapshot))
    stored_metrics = cast(list[dict[str, object]], stored["metrics"])
    ids = {
        str(row["metric_id"])
        for row in stored_metrics
        if row["materialization"] == "source_requery"
    }
    requests = tuple(row for row in selections if row.metric_id in ids)
    materialized: dict[str, dict[str, object]] = {}
    if requests:
        output = _execute_frozen(
            auth,
            requests,
            timezone_name=execution.timezone_name,
            knowledge_cutoff_at=execution.knowledge_cutoff_at,
            executed_at=execution.executed_at,
            capability=capability,
        )
        materialized = {
            str(row["metric_id"]): row
            for row in cast(list[dict[str, object]], output_payload(output)["metrics"])
        }
    results = []
    for row in stored_metrics:
        expected = str(row.pop("metric_result_sha256"))
        strategy = row.pop("materialization")
        if strategy == "source_requery":
            row = materialized[str(row["metric_id"])]
        elif strategy != "execution_snapshot":
            raise StorageIntegrityError("unknown_execution_materialization")
        if payload_hash(row) != expected:
            raise StorageIntegrityError("source_requery_result_mismatch")
        results.append(row)
    stored["metrics"] = results
    if payload_hash(stored) != execution.result_sha256:
        raise StorageIntegrityError("execution_result_integrity_failure")
    return stored


def _export_points(metric: dict[str, object]) -> list[dict[str, object]]:
    points = cast(list[dict[str, object]], metric["points"])
    # Una métrica sin grupos sigue teniendo metadata exportable. No inventa un cero.
    return points or [
        {
            "dimensions": {},
            "value": None,
            "status": "not_calculable",
            "sample_size": None,
            "eligible_count": None,
        }
    ]


def _selection_filters(payload: dict[str, object]) -> dict[str, dict[str, str]]:
    # Una partición fijada por filtro sigue siendo parte del dato exportado, aunque
    # no sea una dimensión de agrupación. Nunca perder USD/unidad/recurso al serializar.
    return {
        str(row["metric_id"]): {
            key: value
            for key, value in cast(dict[str, str], row["filters"]).items()
            if key != "time_bucket"
        }
        for row in cast(list[dict[str, object]], payload["selection"])
    }


def export_dataset(execution_id: str, payload: dict[str, object]) -> ExportDataset:
    metrics = cast(list[dict[str, object]], payload["metrics"])
    filters = _selection_filters(payload)
    dimension_names = sorted(
        {
            name
            for row in metrics
            for point in cast(list[dict[str, object]], row["points"])
            for name in cast(dict[str, str], point["dimensions"])
        }
        | {name for row in filters.values() for name in row}
    )
    columns = (
        Column("metric_id", "Métrica", "text"),
        Column("metric_version", "Versión", "integer"),
        *(Column(name, name, "text") for name in dimension_names),
        Column("value", "Valor", "decimal"),
        Column("unit", "Unidad", "text"),
        Column("status", "Estado", "text"),
        Column("coverage", "Cobertura", "text"),
        Column("provisional", "Provisional", "boolean"),
        Column("coverage_reason", "Motivo de cobertura", "text"),
        Column("sample_size", "Muestra", "integer"),
        Column("eligible_count", "Elegibles", "integer"),
    )
    rows: list[tuple[Cell, ...]] = []
    for metric in metrics:
        for point in _export_points(metric):
            dims = {
                **filters.get(str(metric["metric_id"]), {}),
                **cast(dict[str, str], point["dimensions"]),
            }
            rows.append(
                (
                    str(metric["metric_id"]),
                    cast(int, metric["metric_version"]),
                    *(dims.get(name) for name in dimension_names),
                    Decimal(str(point["value"])) if point["value"] is not None else None,
                    str(metric["unit"]),
                    str(point["status"]),
                    str(metric["coverage"]),
                    cast(bool, metric["provisional"]),
                    cast(str | None, metric["coverage_reason"]),
                    cast(int | None, point["sample_size"]),
                    cast(int | None, point["eligible_count"]),
                )
            )
    result = ExportDataset(
        columns,
        tuple(rows),
        execution_id,
        str(payload["catalog_hash"]),
        str(payload["timezone"]),
        str(payload["knowledge_cutoff_at"]),
    )
    result.validate()
    return result


def presentation_dataset(execution_id: str, payload: dict[str, object]) -> ExportDataset:
    """PDF de presentación compacto; cada punto conserva unidad, dimensiones y cobertura."""
    columns = (
        Column("metric", "Métrica", "text"),
        Column("dimensions", "Dimensiones", "text"),
        Column("value", "Valor", "decimal"),
        Column("unit", "Unidad", "text"),
        Column("status", "Estado", "text"),
        Column("coverage", "Cobertura", "text"),
        Column("provisional", "Provisional", "boolean"),
        Column("reason", "Detalle", "text"),
    )
    rows: list[tuple[Cell, ...]] = []
    filters = _selection_filters(payload)
    for metric in cast(list[dict[str, object]], payload["metrics"]):
        definition = contract(str(metric["metric_id"]), cast(int, metric["metric_version"]))
        for point in _export_points(metric):
            dims = {
                **filters.get(str(metric["metric_id"]), {}),
                **cast(dict[str, str], point["dimensions"]),
            }
            rows.append(
                (
                    definition.label,
                    "; ".join(f"{key}: {value}" for key, value in sorted(dims.items())),
                    Decimal(str(point["value"])) if point["value"] is not None else None,
                    str(metric["unit"]),
                    str(point["status"]),
                    str(metric["coverage"]),
                    cast(bool, metric["provisional"]),
                    cast(str | None, metric["coverage_reason"]),
                )
            )
    result = ExportDataset(
        columns,
        tuple(rows),
        execution_id,
        str(payload["catalog_hash"]),
        str(payload["timezone"]),
        str(payload["knowledge_cutoff_at"]),
    )
    result.validate()
    return result
