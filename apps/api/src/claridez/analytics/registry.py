"""Catálogo normativo, code-defined e inmutable de métricas P15 v1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Final

from claridez.organizations.analytics_contracts import TemporalMode


@dataclass(frozen=True, slots=True)
class SourceMetricReference:
    source_metric_id: str
    source_metric_version: int = 1


@dataclass(frozen=True, slots=True)
class MetricContract:
    metric_id: str
    metric_version: int
    owner: str
    category: str
    label: str
    sources: tuple[SourceMetricReference, ...]
    formula: str
    grain: str
    dimensions: tuple[str, ...]
    required_dimensions: tuple[str, ...]
    temporal_mode: TemporalMode
    unit: str
    scale: int
    required_capabilities: tuple[str, ...]
    coverage_rule: str

    @property
    def versioned_id(self) -> str:
        return f"{self.metric_id}@{self.metric_version}"


def _source(value: str) -> SourceMetricReference:
    return SourceMetricReference(value, 1)


def _metric(
    metric_id: str,
    owner: str,
    label: str,
    source_ids: tuple[str, ...],
    formula: str,
    grain: str,
    dimensions: tuple[str, ...],
    mode: TemporalMode,
    unit: str,
    capabilities: tuple[str, ...],
    coverage: str,
    *,
    required_dimensions: tuple[str, ...] = (),
    category: str = "source_owned",
) -> MetricContract:
    return MetricContract(
        metric_id=metric_id,
        metric_version=1,
        owner=owner,
        category=category,
        label=label,
        sources=tuple(_source(value) for value in source_ids),
        formula=formula,
        grain=grain,
        dimensions=dimensions,
        required_dimensions=required_dimensions,
        temporal_mode=mode,
        unit=unit,
        scale={
            "money": 2,
            "percentage_points": 2,
            "seconds": 3,
            "minutes": 3,
            "quantity": 6,
            "count": 0,
        }[unit],
        required_capabilities=capabilities,
        coverage_rule=coverage,
    )


_C: Final = (
    _metric(
        "request_created_count",
        "commercial",
        "Solicitudes creadas",
        ("commercial.request_created_count",),
        "count distinct por EventRequestHistory created; excluye cutover_state",
        "event_request",
        ("time_bucket", "origin", "responsible_membership_id"),
        TemporalMode.FACT,
        "count",
        ("sales:read",),
        "created autoritativo para todo el alcance",
    ),
    _metric(
        "quote_issued_count",
        "commercial",
        "Cotizaciones emitidas",
        ("commercial.quote_issued_count",),
        "count de QuotationVersion con issued_at autoritativo",
        "quotation_version",
        ("time_bucket", "currency", "event_type_id", "venue_id", "space_id"),
        TemporalMode.FACT,
        "count",
        ("sales:read",),
        "issued_at fiable",
    ),
    _metric(
        "quote_accepted_count",
        "commercial",
        "Cotizaciones aceptadas",
        ("commercial.quote_accepted_count",),
        "count distinct de versiones por primera aceptación autoritativa",
        "quotation_version",
        ("time_bucket", "currency", "event_type_id", "venue_id", "space_id", "acceptance_channel"),
        TemporalMode.FACT,
        "count",
        ("sales:read",),
        "accepted_at fiable",
    ),
    _metric(
        "closed_lost_request_count",
        "commercial",
        "Solicitudes perdidas",
        ("commercial.closed_lost_request_count",),
        "count distinct por transición status_changed a closed_lost",
        "event_request",
        ("time_bucket", "origin", "responsible_membership_id"),
        TemporalMode.FACT,
        "count",
        ("sales:read",),
        "transición y tiempo autoritativos",
    ),
    _metric(
        "closed_lost_latest_issued_quote_amount",
        "commercial",
        "Valor perdido de última cotización",
        ("commercial.closed_lost_latest_issued_quote_amount",),
        "suma última versión emitida no posterior al cierre perdido",
        "event_request",
        ("time_bucket", "currency", "origin", "event_type_id", "venue_id", "space_id"),
        TemporalMode.FACT,
        "money",
        ("sales:read",),
        "versión vigente al cierre demostrable",
        required_dimensions=("currency",),
    ),
    _metric(
        "accepted_quote_amount",
        "commercial",
        "Valor de cotizaciones aceptadas",
        ("commercial.accepted_quote_amount",),
        "suma total de cada versión aceptada",
        "quotation_version",
        ("time_bucket", "currency", "event_type_id", "venue_id", "space_id", "acceptance_channel"),
        TemporalMode.FACT,
        "money",
        ("sales:read",),
        "accepted_at fiable",
        required_dimensions=("currency",),
    ),
    _metric(
        "open_issued_quote_amount",
        "commercial",
        "Pipeline emitido abierto",
        ("commercial.open_issued_quote_amount",),
        "suma última emitida por solicitud quoted y vigente as-of",
        "event_request",
        ("currency", "origin", "event_type_id", "venue_id", "space_id"),
        TemporalMode.STATE,
        "money",
        ("sales:read",),
        "historia de estado y retiro suficiente",
        required_dimensions=("currency",),
    ),
    _metric(
        "first_outbound_response_elapsed_seconds",
        "crm",
        "Tiempo a primera respuesta",
        ("crm.first_outbound_response_elapsed_seconds", "commercial.request_created_cohort"),
        "media de primera interacción outbound efectiva menos creación de solicitud",
        "event_request",
        ("time_bucket", "origin", "channel"),
        TemporalMode.COHORT,
        "seconds",
        ("interaction:read_analytics", "sales:read"),
        "historia completa de creación e interacciones",
    ),
    _metric(
        "open_request_without_next_action_count",
        "crm",
        "Solicitudes abiertas sin próxima acción",
        ("crm.open_request_without_next_action_count", "commercial.request_state_as_of"),
        "solicitudes new/quoted/accepted as-of sin tarea efectiva open",
        "event_request",
        ("origin", "responsible_membership_id"),
        TemporalMode.STATE,
        "count",
        ("task:read_analytics", "sales:read"),
        "historia de tarea y solicitud reconstruible",
    ),
    _metric(
        "confirmed_sale_count",
        "finance",
        "Ventas confirmadas",
        ("finance.confirmed_sale_count",),
        "raíces distintas con venta por primera confirmación",
        "root_reservation",
        ("time_bucket", "currency", "venue_id"),
        TemporalMode.FACT,
        "count",
        ("finance:read",),
        "procedencia Finance/Receivables y snapshot económico",
    ),
    _metric(
        "confirmed_sale_amount",
        "finance",
        "Valor de venta confirmada",
        ("finance.confirmed_sale_amount",),
        "total de cotización aceptada que originó obligación en primera confirmación",
        "root_reservation",
        ("time_bucket", "currency", "venue_id"),
        TemporalMode.FACT,
        "money",
        ("finance:read",),
        "misma cobertura que confirmed_sale_count",
        required_dimensions=("currency",),
    ),
    _metric(
        "request_to_confirmed_sale_conversion_rate",
        "analytics",
        "Conversión solicitud a venta confirmada",
        ("commercial.request_created_cohort", "finance.confirmed_sale_cohort"),
        "solicitudes de cohorte con primera venta visible / solicitudes elegibles * 100",
        "event_request",
        ("time_bucket", "origin"),
        TemporalMode.COHORT,
        "percentage_points",
        ("sales:read", "finance:read"),
        "peor cobertura de ambas fuentes y cohortes reconciliables",
        category="analytics_owned",
    ),
    _metric(
        "distinct_canonical_request_person_count",
        "analytics",
        "Personas canónicas distintas",
        ("commercial.request_person_cohort", "people.canonical_cluster_as_of"),
        "clusters People distintos as-of con solicitud en la cohorte",
        "canonical_cluster",
        ("time_bucket", "origin"),
        TemporalMode.COHORT,
        "count",
        ("sales:read", "person:resolve_analytics"),
        "peor cobertura y merge histórico suficiente",
        category="analytics_owned",
    ),
)

_S_O: Final = (
    _metric(
        "confirmed_event_minutes",
        "scheduling",
        "Minutos de evento confirmados",
        ("scheduling.confirmed_event_minutes",),
        "intersección del periodo con event_interval de reserva efectiva por raíz",
        "root_reservation",
        ("time_bucket", "venue_id", "space_id"),
        TemporalMode.STATE_IN_PERIOD,
        "minutes",
        ("schedule:read_analytics",),
        "cadena, ScheduleEvent e intervalo completos",
    ),
    _metric(
        "confirmed_occupied_minutes",
        "scheduling",
        "Minutos ocupados confirmados",
        ("scheduling.confirmed_occupied_minutes",),
        "intersección con occupied_interval histórico, incluidos setup, teardown y buffers",
        "root_reservation",
        ("time_bucket", "venue_id", "space_id"),
        TemporalMode.STATE_IN_PERIOD,
        "minutes",
        ("schedule:read_analytics",),
        "snapshot histórico de ocupación completo",
    ),
    _metric(
        "confirmed_reservation_count",
        "scheduling",
        "Reservas confirmadas",
        ("scheduling.confirmed_reservation_count",),
        "raíces con reserva efectiva confirmed as-of e intersección de event_interval",
        "root_reservation",
        ("time_bucket", "venue_id", "space_id"),
        TemporalMode.STATE_IN_PERIOD,
        "count",
        ("schedule:read_analytics",),
        "cadena y estado históricos completos",
    ),
    _metric(
        "blocked_minutes",
        "scheduling",
        "Minutos bloqueados",
        ("scheduling.blocked_minutes",),
        "intersección con allocations de bloqueo efectivas as-of",
        "schedule_block_space",
        ("time_bucket", "venue_id", "space_id"),
        TemporalMode.STATE_IN_PERIOD,
        "minutes",
        ("schedule:read_analytics",),
        "creación y liberación demostrables",
        required_dimensions=("space_id",),
    ),
    _metric(
        "reservation_cancelled_count",
        "scheduling",
        "Cancelaciones de reserva",
        ("scheduling.reservation_cancelled_count",),
        "count de ScheduleEvent autoritativos de cancelación",
        "schedule_event",
        ("time_bucket", "venue_id", "space_id"),
        TemporalMode.FACT,
        "count",
        ("schedule:read_analytics",),
        "evento y snapshot previo completos",
    ),
    _metric(
        "reservation_rescheduled_count",
        "scheduling",
        "Reprogramaciones",
        ("scheduling.reservation_rescheduled_count",),
        "count de ScheduleEvent autoritativos de reprogramación",
        "schedule_event",
        ("time_bucket", "from_venue_id", "from_space_id", "to_venue_id", "to_space_id"),
        TemporalMode.FACT,
        "count",
        ("schedule:read_analytics",),
        "snapshots y cadena coherentes",
    ),
    _metric(
        "preparation_open_count",
        "operations",
        "Preparaciones abiertas",
        ("operations.preparation_open_count",),
        "preparaciones cuyo estado as-of es preparing, ready o in_progress",
        "event_preparation",
        ("status", "responsible_membership_id"),
        TemporalMode.STATE,
        "count",
        ("operation:read",),
        "transiciones históricas suficientes",
    ),
    _metric(
        "pending_required_verification_count",
        "operations",
        "Verificaciones requeridas pendientes",
        ("operations.pending_required_verification_count",),
        "verificaciones requeridas efectivas pending as-of",
        "operational_verification",
        ("phase", "role_key"),
        TemporalMode.STATE,
        "count",
        ("operation:read",),
        "historia de estado y correcciones suficiente",
    ),
    _metric(
        "execution_completed_count",
        "operations",
        "Ejecuciones completadas",
        ("operations.execution_completed_count",),
        "preparaciones distintas por transición execution_completed",
        "event_preparation",
        ("time_bucket",),
        TemporalMode.FACT,
        "count",
        ("operation:read",),
        "transición autoritativa, no cutover",
    ),
    _metric(
        "phase_duration_seconds",
        "operations",
        "Duración observada de fase",
        ("operations.phase_duration_seconds",),
        "media de completed.observed_at - started.observed_at no negativa",
        "preparation_phase",
        ("time_bucket", "phase"),
        TemporalMode.FACT,
        "seconds",
        ("operation:read",),
        "pares completos; incompletos vuelven partial",
        required_dimensions=("phase",),
    ),
    _metric(
        "incident_opened_count",
        "operations",
        "Incidencias abiertas",
        ("operations.incident_opened_count",),
        "incidentes distintos por evento raíz opened efectivo",
        "operational_incident",
        ("time_bucket", "incident_type", "severity"),
        TemporalMode.FACT,
        "count",
        ("operation_incident:read",),
        "evento de apertura fiable",
    ),
    _metric(
        "post_event_close_elapsed_seconds",
        "operations",
        "Tiempo hasta cierre postevento",
        ("operations.post_event_close_elapsed_seconds",),
        "media de cierre postevento menos execution_completed",
        "event_preparation",
        ("time_bucket",),
        TemporalMode.FACT,
        "seconds",
        ("operation:read",),
        "transición y cierre autoritativos",
    ),
)

_R: Final = (
    _metric(
        "obligation_original_amount",
        "receivables",
        "Obligación original",
        ("receivables.obligation_original_amount",),
        "suma original_total por primera confirmación",
        "receivable_obligation",
        ("time_bucket", "currency"),
        TemporalMode.FACT,
        "money",
        ("receivables:read",),
        "obligación y snapshot económico fiables",
        required_dimensions=("currency",),
    ),
    _metric(
        "payment_received_amount",
        "receivables",
        "Pagos recibidos",
        ("receivables.payment_received_amount",),
        "suma bruta de pagos externos declarados",
        "received_payment",
        ("time_bucket", "currency", "method", "provenance"),
        TemporalMode.FACT,
        "money",
        ("receivables:read",),
        "pago y moneda autoritativos",
        required_dimensions=("currency",),
    ),
    _metric(
        "payment_unapplied_amount",
        "receivables",
        "Pago sin aplicar",
        ("receivables.payment_unapplied_amount",),
        "no aplicado de pagos de cohorte según ledger P10 as-of",
        "received_payment",
        ("time_bucket", "currency", "method", "provenance"),
        TemporalMode.COHORT,
        "money",
        ("receivables:read",),
        "cadena completa de movimientos",
        required_dimensions=("currency",),
    ),
    _metric(
        "application_net_amount",
        "receivables",
        "Aplicación neta",
        ("receivables.application_net_amount",),
        "efectos netos de aplicaciones, reversos y refunds",
        "financial_effect",
        ("time_bucket", "currency", "effect_kind"),
        TemporalMode.FACT,
        "money",
        ("receivables:read",),
        "cadena y asignaciones completas",
        required_dimensions=("currency",),
    ),
    _metric(
        "adjustment_net_amount",
        "receivables",
        "Ajuste neto",
        ("receivables.adjustment_net_amount",),
        "signo normativo de ajustes y reversos",
        "adjustment_effect",
        ("time_bucket", "currency", "direction"),
        TemporalMode.FACT,
        "money",
        ("receivables:read",),
        "objetivo y reverso coherentes",
        required_dimensions=("currency",),
    ),
    _metric(
        "movement_reversal_amount_by_target",
        "receivables",
        "Reversos por objetivo",
        ("receivables.movement_reversal_amount_by_target",),
        "suma bruta positiva de reversos por target_kind",
        "movement_reversal",
        ("time_bucket", "currency", "target_kind"),
        TemporalMode.FACT,
        "money",
        ("receivables:read",),
        "target y moneda reconciliables",
        required_dimensions=("currency", "target_kind"),
    ),
    _metric(
        "refund_recorded_amount",
        "receivables",
        "Devoluciones registradas",
        ("receivables.refund_recorded_amount",),
        "suma bruta de devoluciones registradas",
        "refund_record",
        ("time_bucket", "currency"),
        TemporalMode.FACT,
        "money",
        ("receivables:read",),
        "refund y asignaciones coherentes",
        required_dimensions=("currency",),
    ),
    _metric(
        "open_balance_amount",
        "receivables",
        "Saldo abierto",
        ("receivables.open_balance_amount",),
        "saldo exacto ADR 0019 por obligación as-of",
        "receivable_obligation",
        ("currency",),
        TemporalMode.STATE,
        "money",
        ("receivables:read",),
        "ledger completo y moneda única",
        required_dimensions=("currency",),
    ),
    _metric(
        "aging_open_balance_amount",
        "receivables",
        "Antigüedad de saldo",
        ("receivables.aging_open_balance_amount",),
        "saldo abierto distribuido por calendario aplicable y bucket",
        "obligation_due",
        ("currency", "aging_bucket"),
        TemporalMode.STATE,
        "money",
        ("receivables:read",),
        "calendario y movimientos reconstruibles",
        required_dimensions=("currency", "aging_bucket"),
    ),
    _metric(
        "expected_collection_amount",
        "receivables",
        "Cobro calendarizado esperado",
        ("receivables.expected_collection_amount",),
        "residual abierto de vencimientos due_on en periodo",
        "collection_due",
        ("time_bucket", "currency"),
        TemporalMode.STATE_IN_PERIOD,
        "money",
        ("receivables:read",),
        "calendario as-of reconstruible",
        required_dimensions=("currency",),
    ),
)


def _finance(
    metric_id: str,
    label: str,
    formula: str,
    dims: tuple[str, ...],
    unit: str = "money",
    *,
    mode: TemporalMode = TemporalMode.FINANCIAL_PERIOD,
    required: tuple[str, ...] = ("currency",),
) -> MetricContract:
    return _metric(
        metric_id,
        "finance",
        label,
        (f"finance.{metric_id}",),
        formula,
        {
            "recognized_revenue_amount": "operational_period_root",
            "baseline_direct_cost_amount": "root_plan_line",
            "actual_direct_cost_amount": "actual_direct_cost_or_correction",
            "variable_expense_amount": "variable_expense_allocation_or_correction",
            "recurring_expense_amount": "recurring_expense_allocation_or_correction",
            "cash_inflow_amount": "cash_contribution_or_movement_or_correction",
            "cash_outflow_amount": "cash_contribution_or_movement_or_correction",
        }.get(metric_id, "operational_period_scope"),
        ("currency", *dims),
        mode,
        unit,
        ("finance:read",),
        "baseline inmutable; antes de existir not_applicable; revisiones visibles al cutoff"
        if metric_id == "baseline_direct_cost_amount"
        else "snapshot cerrado manda; abierto es provisional; registros visibles al cutoff",
        required_dimensions=required,
    )


_F: Final = (
    _finance(
        "recognized_revenue_amount",
        "Ingreso reconocido",
        "ADR 0020 §§4,9,11",
        ("venue_id", "root_reservation_id"),
    ),
    _finance(
        "baseline_direct_cost_amount",
        "Baseline de costo directo",
        "suma baseline inmutable ADR 0020 §5",
        ("root_reservation_id", "category_id"),
        mode=TemporalMode.STATE,
        required=("currency", "root_reservation_id"),
    ),
    _finance(
        "actual_direct_cost_amount",
        "Costo directo real",
        "costo real neto de correcciones",
        ("venue_id", "root_reservation_id", "category_id"),
    ),
    _finance(
        "variable_expense_amount",
        "Gasto variable",
        "porciones variables materializadas netas",
        ("venue_id", "root_reservation_id", "category_id"),
    ),
    _finance(
        "recurring_expense_amount",
        "Gasto recurrente",
        "porciones recurrentes materializadas netas",
        ("venue_id", "category_id"),
    ),
    _finance(
        "cash_inflow_amount",
        "Entrada de caja",
        "contribuciones P10 y movimientos P11 de entrada",
        ("venue_id", "root_reservation_id", "source_kind"),
    ),
    _finance(
        "cash_outflow_amount",
        "Salida de caja",
        "contribuciones P10 y movimientos P11 de salida",
        ("venue_id", "root_reservation_id", "source_kind"),
    ),
    _finance(
        "net_cash_flow_amount",
        "Flujo neto",
        "contribuciones de caja P10 más movimientos P11",
        ("venue_id", "root_reservation_id"),
    ),
    _finance(
        "gross_margin_amount",
        "Margen bruto",
        "ingreso reconocido menos costos directos reales",
        ("venue_id", "root_reservation_id"),
    ),
    _finance(
        "contribution_margin_amount",
        "Margen de contribución",
        "margen bruto menos gastos variables",
        ("venue_id", "root_reservation_id"),
    ),
    _finance(
        "operating_result_amount",
        "Resultado operativo",
        "margen de contribución menos gastos recurrentes",
        ("venue_id", "root_reservation_id"),
    ),
    _finance(
        "profitability_rate",
        "Rentabilidad operativa del periodo",
        "resultado operativo / ingreso reconocido * 100",
        ("venue_id", "root_reservation_id"),
        "percentage_points",
    ),
)


def _resource(
    metric_id: str, label: str, formula: str, dims: tuple[str, ...], mode: TemporalMode
) -> MetricContract:
    return _metric(
        metric_id,
        "resources",
        label,
        (f"resources.{metric_id}",),
        formula,
        {
            "stock_on_hand_quantity": "resource_location",
            "stock_movement_quantity": "stock_movement",
            "event_required_quantity": "resource_requirement",
            "event_allocated_quantity": "resource_assignment",
            "event_shortage_quantity": "resource_requirement",
            "resource_unavailability_quantity": "resource_unavailability",
        }[metric_id],
        ("resource_id", "unit_id", *dims),
        mode,
        "quantity",
        ("resource:read",),
        "ledger y eventos Resources históricos completos",
        required_dimensions=("resource_id", "unit_id", "direction")
        if metric_id == "stock_movement_quantity"
        else ("resource_id", "unit_id"),
    )


_RES: Final = (
    _resource(
        "stock_on_hand_quantity",
        "Existencia disponible",
        "suma efectos StockMovement hasta el corte",
        ("location_id",),
        TemporalMode.STATE,
    ),
    _resource(
        "stock_movement_quantity",
        "Movimientos de existencia",
        "suma positiva por dirección sin netear",
        ("time_bucket", "location_id", "kind", "direction"),
        TemporalMode.FACT,
    ),
    _resource(
        "event_required_quantity",
        "Cantidad requerida por eventos",
        "requisitos efectivos no cancelados que intersectan periodo",
        ("root_reservation_id", "temporal_source"),
        TemporalMode.STATE_IN_PERIOD,
    ),
    _resource(
        "event_allocated_quantity",
        "Cantidad asignada a eventos",
        "asignaciones efectivas bloqueantes que intersectan periodo",
        ("root_reservation_id", "source_location_id", "assignment_status"),
        TemporalMode.STATE_IN_PERIOD,
    ),
    _resource(
        "event_shortage_quantity",
        "Faltante por eventos",
        "max(required - asignado efectivo, 0) por requisito",
        ("root_reservation_id", "temporal_source"),
        TemporalMode.STATE_IN_PERIOD,
    ),
    _resource(
        "resource_unavailability_quantity",
        "Cantidad indisponible",
        "indisponibilidades efectivas que contienen as_of_at",
        ("location_id",),
        TemporalMode.STATE,
    ),
)


METRICS: Final = _C + _S_O + _R + _F + _RES
if len(METRICS) != 53:
    raise RuntimeError("El catálogo P15 v1 debe contener exactamente 53 contratos.")
if len({item.versioned_id for item in METRICS}) != len(METRICS):
    raise RuntimeError("El catálogo P15 contiene identificadores duplicados.")

METRIC_REGISTRY: Final = MappingProxyType({item.versioned_id: item for item in METRICS})
CATALOG_VERSION: Final = "p15-v1"


def _canonical_catalog() -> bytes:
    payload = []
    for contract in METRICS:
        value = asdict(contract)
        value["temporal_mode"] = contract.temporal_mode.value
        payload.append(value)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


CATALOG_HASH: Final = hashlib.sha256(_canonical_catalog()).hexdigest()


def contract(metric_id: str, metric_version: int = 1) -> MetricContract:
    try:
        return METRIC_REGISTRY[f"{metric_id}@{metric_version}"]
    except KeyError as error:
        raise KeyError("métrica o versión no publicadas") from error


def public_catalog() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "metric_id": item.metric_id,
            "metric_version": item.metric_version,
            "label": item.label,
            "owner": item.owner,
            "category": item.category,
            "source_metrics": [
                {
                    "source_metric_id": source.source_metric_id,
                    "source_metric_version": source.source_metric_version,
                }
                for source in item.sources
            ],
            "formula": item.formula,
            "grain": item.grain,
            "dimensions": list(item.dimensions),
            "required_dimensions": list(item.required_dimensions),
            "temporal_mode": item.temporal_mode.value,
            "unit": item.unit,
            "scale": item.scale,
            "required_capabilities": list(item.required_capabilities),
            "coverage_rule": item.coverage_rule,
        }
        for item in METRICS
    )
