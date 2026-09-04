"""Reconciliación P15 con comandos de dominio reales; no mocks de fórmulas ni timestamps."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest
from django.db import connection

from claridez.analytics.query import execute_query
from claridez.organizations.analytics_contracts import Coverage, MetricValueStatus
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope
from tests.p15_dataset import SMOKE, build_dataset
from tests.p15_measurement import SQLProbe

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def test_known_source_facts_reconcile_composition_finance_cartera_agenda_and_resources() -> None:
    dataset = build_dataset("p15-reconciliation")
    # Otro tenant tiene hechos de las mismas familias: no debe alterar ninguno de los resultados.
    build_dataset("p15-reconciliation-other")
    probe = SQLProbe()
    with (
        authorized_tenant_scope(
            dataset.actor, dataset.organization_id, Capability.ANALYTICS_READ_DASHBOARD
        ) as auth,
        connection.execute_wrapper(probe),
    ):
        output = execute_query(
            auth,
            dataset.selections(),
            timezone_name="America/Guayaquil",
            capability=Capability.ANALYTICS_READ_DASHBOARD,
        )
    assert len(output.metrics) == 53
    actual = {row.metric_id: row.result for row in output.metrics}
    expected = {
        "request_created_count": "16",
        "quote_issued_count": "4",
        "quote_accepted_count": "4",
        "accepted_quote_amount": "6468.80",
        "confirmed_sale_count": "2",
        "confirmed_sale_amount": "3234.40",
        "request_to_confirmed_sale_conversion_rate": "12.50",
        "distinct_canonical_request_person_count": "2",
        "open_request_without_next_action_count": "8",
        "confirmed_reservation_count": "2",
        "confirmed_event_minutes": "600",
        "confirmed_occupied_minutes": "600",
        "preparation_open_count": "1",
        "execution_completed_count": "1",
        "obligation_original_amount": "3234.40",
        "payment_received_amount": "600.00",
        "application_net_amount": "600.00",
        "payment_unapplied_amount": "0.00",
        "open_balance_amount": "2634.40",
        "recognized_revenue_amount": "1617.20",
        "baseline_direct_cost_amount": "100.00",
        "actual_direct_cost_amount": "240.00",
        "variable_expense_amount": "40.00",
        "cash_inflow_amount": "600.00",
        "cash_outflow_amount": "160.00",
        "net_cash_flow_amount": "440.00",
        "gross_margin_amount": "1377.20",
        "contribution_margin_amount": "1337.20",
        "operating_result_amount": "1337.20",
    }
    expected["profitability_rate"] = str(
        (Decimal("1337.20") / Decimal("1617.20") * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    )
    for name, value in expected.items():
        result = actual[name]
        assert result.coverage is Coverage.COMPLETE, (name, result.coverage_reason)
        currencies = {
            dict(point.dimensions)["currency"]
            for point in result.points
            if "currency" in dict(point.dimensions)
        }
        assert currencies <= {"USD"}, name  # Nunca se suman divisas distintas para reconciliar.
        assert result.points and all(
            point.status is MetricValueStatus.VALUE for point in result.points
        ), name
        assert sum((Decimal(str(point.value)) for point in result.points), Decimal(0)) == Decimal(
            value
        ), name
    response = actual["first_outbound_response_elapsed_seconds"]
    assert response.coverage is Coverage.COMPLETE
    assert response.points[0].sample_size == SMOKE.requests
    assert response.points[0].value is not None and response.points[0].value >= 0
    for name, amount in (
        ("stock_on_hand_quantity", "10000"),
        ("event_required_quantity", "2"),
        ("event_allocated_quantity", "2"),
        ("event_shortage_quantity", "0"),
    ):
        result = actual[name]
        assert result.coverage is Coverage.COMPLETE, (name, result.coverage_reason)
        assert len(result.points) == 2
        # Cantidad se comprueba por recurso/unidad; nunca se suman unidades incompatibles.
        for point in result.points:
            assert set(dict(point.dimensions)) == {"resource_id", "unit_id"}
            assert point.value == Decimal(amount), name
    assert probe.count <= 96, (
        probe.count
    )  # Solo fan-in: autorización se mide además en el benchmark HTTP.
