from __future__ import annotations

import ast
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from django.test import Client
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator

from claridez.finance.errors import FinanceError
from claridez.finance.models import (
    ExpenseOccurrence,
    FinanceCommand,
    OperatingBudgetRevision,
    OperatingCashMovement,
    PeriodCloseSnapshot,
)
from claridez.finance.services import (
    close_period,
    correct_cash_movement,
    correct_direct_cost,
    create_category,
    create_period,
    create_recurring_rule,
    finance_overview,
    materialize_recurring_expense,
    publish_budget,
    publish_direct_cost_plan,
    record_actual_direct_cost,
    record_cash_movement,
    record_expense,
    record_recognition_adjustment,
)
from claridez.operations.services import (
    assign_preparation,
    complete_event,
    mark_ready,
    read_event,
    start_event,
    update_item,
)
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import create_space, create_venue, list_venues
from claridez.organizations.models import Membership
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.scheduling.services import reschedule_reservation
from tests.test_receivables import _confirmed


def test_finance_cross_module_consumers_use_only_public_ports_and_no_catalog() -> None:
    package = Path(__file__).resolve().parents[1] / "src" / "claridez" / "finance"
    violations: list[str] = []
    for module in package.rglob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported: str | None = None
            if isinstance(node, ast.ImportFrom):
                imported = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "claridez.catalog" or (
                        alias.name.startswith("claridez.") and not alias.name.endswith(".public")
                    ):
                        violations.append(f"{module.name}: {alias.name}")
            if imported is None:
                continue
            if imported == "claridez.catalog" or (
                imported.startswith(
                    (
                        "claridez.commercial",
                        "claridez.operations",
                        "claridez.organizations",
                        "claridez.receivables",
                        "claridez.scheduling",
                    )
                )
                and not imported.endswith(".public")
                and imported
                not in {
                    "claridez.organizations.capabilities",
                    "claridez.organizations.exceptions",
                    "claridez.organizations.tenant_scope",
                }
            ):
                violations.append(f"{module.name}: {imported}")

    assert violations == []
    assert "SourcePeriodRegistration" not in (package / "models.py").read_text(encoding="utf-8")


def _month_bounds(value: date) -> tuple[date, date]:
    start = value.replace(day=1)
    end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
    return start, end


def _make_period(owner: Any, organization_id: UUID, value: date, label: str = "Periodo") -> Any:
    starts_on, ends_on = _month_bounds(value)
    return create_period(
        owner,
        organization_id,
        starts_on=starts_on,
        ends_on=ends_on,
        label=label,
        idempotency_key=uuid4(),
    )


def _venue_for_space(owner: Any, organization_id: UUID, space_id: UUID | str) -> UUID:
    for venue in list_venues(owner, organization_id):
        for space in venue["spaces"]:
            if str(space["id"]) == str(space_id):
                return UUID(str(venue["id"]))
    raise AssertionError("space has no venue")


def _prepare_and_start(
    owner: Any, organization_id: UUID, reservation_id: UUID | str
) -> dict[str, Any]:
    target = UUID(str(reservation_id))
    detail = read_event(owner, organization_id, reservation_id=target)
    responsible_id = Membership.objects.get(
        organization_id=organization_id, user=owner, status=Membership.Status.ACTIVE
    ).pk
    assigned = assign_preparation(
        owner,
        organization_id,
        reservation_id=target,
        revision=detail["preparation"]["revision"],
        responsible_membership_id=responsible_id,
    )
    revision = assigned["preparation"]["revision"]
    for item in assigned["preparation"]["items"]:
        changed = update_item(
            owner,
            organization_id,
            reservation_id=target,
            item_id=item["id"],
            revision=item["revision"],
            values={"status": "completed"},
        )
        revision = changed["preparation_revision"]
    ready = mark_ready(owner, organization_id, reservation_id=target, revision=revision)
    return start_event(
        owner,
        organization_id,
        reservation_id=target,
        revision=ready["preparation"]["revision"],
    )


def _complete(owner: Any, organization_id: UUID, reservation_id: UUID | str) -> dict[str, Any]:
    started = _prepare_and_start(owner, organization_id, reservation_id)
    return complete_event(
        owner,
        organization_id,
        reservation_id=UUID(str(reservation_id)),
        revision=started["preparation"]["revision"],
    )


def _overview(owner: Any, organization_id: UUID, **filters: Any) -> dict[str, Any]:
    return cast(dict[str, Any], finance_overview(owner, organization_id, **filters))


@pytest.mark.django_db(transaction=True)
def test_payment_is_cash_but_not_revenue_until_execution_completed() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-recognition")
    organization_id = creation.organization.pk
    period = _make_period(owner, organization_id, timezone.localdate(), "Mes operativo")

    before = _overview(owner, organization_id, period_id=period.pk)
    assert before["presented"]["p10_cash"] == Decimal("300.00")
    assert before["presented"]["recognized_revenue"] == Decimal("0.00")

    _complete(owner, organization_id, confirmed["id"])
    after = _overview(owner, organization_id, period_id=period.pk)
    assert after["presented"]["p10_cash"] == Decimal("300.00")
    assert after["presented"]["recognized_revenue"] == Decimal("1617.20")
    assert UUID(str(after["events"][0]["root_reservation_id"])) == UUID(str(reservation["root_id"]))


@pytest.mark.django_db(transaction=True)
def test_latest_plan_at_start_is_immutable_baseline_and_idempotent() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-baseline")
    organization_id = creation.organization.pk
    _make_period(owner, organization_id, timezone.localdate())
    venue_id = _venue_for_space(owner, organization_id, confirmed["space_id"])
    category = create_category(
        owner,
        organization_id,
        kind="direct_cost",
        name="Catering",
        idempotency_key=uuid4(),
    )
    first = publish_direct_cost_plan(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=venue_id,
        currency_value="USD",
        reason="Estimación inicial",
        lines=[{"category_id": category.pk, "description": "Menú", "amount": "100.00"}],
        idempotency_key=uuid4(),
    )
    key = uuid4()
    baseline = publish_direct_cost_plan(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=venue_id,
        currency_value="USD",
        reason="Estimación final",
        lines=[{"category_id": category.pk, "description": "Menú", "amount": "120.00"}],
        idempotency_key=key,
    )
    replay = publish_direct_cost_plan(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=venue_id,
        currency_value="USD",
        reason="Estimación final",
        lines=[{"category_id": category.pk, "description": "Menú", "amount": "120.00"}],
        idempotency_key=key,
    )
    assert replay.pk == baseline.pk and baseline.revision == first.revision + 1

    _prepare_and_start(owner, organization_id, confirmed["id"])
    with pytest.raises(FinanceError, match="baseline") as rejected:
        publish_direct_cost_plan(
            owner,
            organization_id,
            root_reservation_id=reservation["root_id"],
            venue_id=venue_id,
            currency_value="USD",
            reason="Cambio tardío",
            lines=[{"category_id": category.pk, "description": "Menú", "amount": "140.00"}],
            idempotency_key=uuid4(),
        )
    assert rejected.value.code == "cost_baseline_already_frozen"
    overview = _overview(owner, organization_id, root_reservation_id=reservation["root_id"])
    assert overview["events"][0]["baseline_plan_revision_id"] == baseline.pk
    assert overview["events"][0]["baseline_planned_cost"] == Decimal("120.00")
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ):
        assert FinanceCommand.objects.filter(command_type="publish_direct_cost_plan").count() == 2


@pytest.mark.django_db(transaction=True)
def test_reprogramming_between_venues_does_not_move_historical_cost_or_expense() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-venue-history")
    organization_id = creation.organization.pk
    _make_period(owner, organization_id, timezone.localdate())
    original_venue = _venue_for_space(owner, organization_id, confirmed["space_id"])
    destination_venue = create_venue(owner, organization_id, name="Sede destino")
    destination_space = create_space(
        owner,
        organization_id,
        venue_id=destination_venue["id"],
        name="Salón destino",
    )
    direct = create_category(
        owner, organization_id, kind="direct_cost", name="Montaje", idempotency_key=uuid4()
    )
    variable = create_category(
        owner,
        organization_id,
        kind="variable_expense",
        name="Transporte",
        idempotency_key=uuid4(),
    )
    cost = record_actual_direct_cost(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=original_venue,
        category_id=direct.pk,
        amount_value="100.00",
        currency_value="USD",
        economic_date=timezone.localdate(),
        description="Montaje original",
        evidence_reference="COST-1",
        idempotency_key=uuid4(),
    )
    expense = record_expense(
        owner,
        organization_id,
        category_id=variable.pk,
        expense_type="variable",
        amount_value="40.00",
        currency_value="USD",
        economic_date=timezone.localdate(),
        description="Transporte original",
        evidence_reference="EXP-1",
        allocations=[
            {
                "scope": "event",
                "root_reservation_id": reservation["root_id"],
                "venue_id": original_venue,
                "amount": "40.00",
            }
        ],
        idempotency_key=uuid4(),
    )
    successor = reschedule_reservation(
        owner,
        organization_id,
        reservation_id=confirmed["id"],
        revision=confirmed["revision"],
        idempotency_key=uuid4(),
        space_id=UUID(str(destination_space["id"])),
        starts_at_local=datetime(2026, 10, 20, 18, 0),
        ends_at_local=datetime(2026, 10, 20, 23, 0),
        timezone_name="America/Guayaquil",
        reason="Cambio de sede",
        commercial_terms_unchanged=True,
    )["reservation"]
    _complete(owner, organization_id, successor["id"])

    original = _overview(owner, organization_id, venue_id=original_venue)
    destination = _overview(owner, organization_id, venue_id=UUID(str(destination_venue["id"])))
    assert original["presented"]["direct_cost"] == Decimal("100.00")
    assert original["presented"]["variable_expense"] == Decimal("40.00")
    assert original["presented"]["recognized_revenue"] == Decimal("0.00")
    assert destination["presented"]["recognized_revenue"] == Decimal("1617.20")
    assert destination["presented"]["direct_cost"] == Decimal("0.00")
    assert cost.venue_id == original_venue
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ):
        assert expense.allocations.get().venue_id == original_venue


@pytest.mark.django_db(transaction=True)
def test_late_fact_is_prior_period_adjustment_and_closed_snapshot_is_unchanged() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-late-fact")
    organization_id = creation.organization.pk
    january = _make_period(owner, organization_id, date(2026, 1, 15), "Enero 2026")
    february = _make_period(owner, organization_id, date(2026, 2, 15), "Febrero 2026")
    closed = close_period(owner, organization_id, period_id=january.pk, idempotency_key=uuid4())
    original_hash = closed.snapshot_sha256
    venue_id = _venue_for_space(owner, organization_id, confirmed["space_id"])
    category = create_category(
        owner,
        organization_id,
        kind="direct_cost",
        name="Hecho tardío",
        idempotency_key=uuid4(),
    )
    cost = record_actual_direct_cost(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=venue_id,
        category_id=category.pk,
        amount_value="10.005",
        currency_value="USD",
        economic_date=date(2026, 1, 20),
        description="Factura tardía",
        evidence_reference="LATE-1",
        idempotency_key=uuid4(),
    )
    assert cost.amount == Decimal("10.01")
    assert cost.registration_period_id == february.pk
    january_result = _overview(owner, organization_id, period_id=january.pk)
    february_result = _overview(owner, organization_id, period_id=february.pk)
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ):
        persisted = PeriodCloseSnapshot.objects.get(pk=closed.pk)
        assert persisted.snapshot_sha256 == original_hash
    assert january_result["presented"]["direct_cost"] == "0.00"
    assert february_result["ordinary"]["direct_cost"] == Decimal("0.00")
    assert february_result["prior_period_adjustments"]["direct_cost"] == Decimal("10.01")


@pytest.mark.django_db(transaction=True)
def test_expense_recurrence_budget_cash_and_restricted_recognition() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-components")
    organization_id = creation.organization.pk
    period = _make_period(owner, organization_id, timezone.localdate())
    venue_id = _venue_for_space(owner, organization_id, confirmed["space_id"])
    direct = create_category(
        owner, organization_id, kind="direct_cost", name="Personal", idempotency_key=uuid4()
    )
    recurring = create_category(
        owner,
        organization_id,
        kind="recurring_expense",
        name="Renta",
        idempotency_key=uuid4(),
    )
    cost = record_actual_direct_cost(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=venue_id,
        category_id=direct.pk,
        amount_value="80.00",
        currency_value="USD",
        economic_date=timezone.localdate(),
        description="Personal",
        evidence_reference="COST-CASH",
        idempotency_key=uuid4(),
    )
    cash = record_cash_movement(
        owner,
        organization_id,
        direction="outflow",
        source_kind="direct_cost",
        source_id=cost.pk,
        original_outflow_id=None,
        amount_value="50.00",
        economic_date=timezone.localdate(),
        reason="Pago de costo",
        evidence_reference="CASH-1",
        idempotency_key=uuid4(),
    )
    rule = create_recurring_rule(
        owner,
        organization_id,
        category_id=recurring.pk,
        name="Renta mensual",
        amount_value="30.00",
        currency_value="USD",
        day_of_month=timezone.localdate().day,
        valid_from=period.starts_on,
        valid_until=None,
        default_venue_id=venue_id,
        idempotency_key=uuid4(),
    )
    occurrence = materialize_recurring_expense(
        owner,
        organization_id,
        rule_id=rule.pk,
        economic_date=timezone.localdate(),
        evidence_reference="RENT-1",
        idempotency_key=uuid4(),
    )
    budget = publish_budget(
        owner,
        organization_id,
        period_id=period.pk,
        venue_id=venue_id,
        currency_value="USD",
        reason="Presupuesto mensual",
        lines=[{"category_id": recurring.pk, "amount": "35.00"}],
        idempotency_key=uuid4(),
    )
    assert cash.direction == OperatingCashMovement.Direction.OUTFLOW
    assert occurrence.provenance == ExpenseOccurrence.Provenance.RECURRING
    assert budget.revision == 1
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ):
        assert OperatingBudgetRevision.objects.count() == 1
    with pytest.raises(FinanceError) as uncompleted:
        record_recognition_adjustment(
            owner,
            organization_id,
            root_reservation_id=reservation["root_id"],
            direction="decrease",
            amount_value="1.00",
            currency_value="USD",
            economic_date=timezone.localdate(),
            reason_code="measurement_correction",
            reason="Medición",
            evidence_reference="REC-1",
            idempotency_key=uuid4(),
        )
    assert uncompleted.value.code == "execution_not_completed"
    _complete(owner, organization_id, confirmed["id"])
    with pytest.raises(FinanceError) as forbidden:
        record_recognition_adjustment(
            owner,
            organization_id,
            root_reservation_id=reservation["root_id"],
            direction="decrease",
            amount_value="1.00",
            currency_value="USD",
            economic_date=timezone.localdate(),
            reason_code="measurement_correction",
            reason="Pérdida de anticipo por cancelación",
            evidence_reference="REC-2",
            idempotency_key=uuid4(),
        )
    assert forbidden.value.code == "cancellation_consequence_not_authorized"
    overview = _overview(owner, organization_id, period_id=period.pk)
    assert overview["presented"]["recognized_revenue"] == Decimal("1617.20")
    assert overview["presented"]["direct_cost"] == Decimal("80.00")
    assert overview["presented"]["recurring_expense"] == Decimal("30.00")
    assert overview["presented"]["p11_cash"] == Decimal("-50.00")
    assert overview["presented"]["net_cash_flow"] == Decimal("250.00")


@pytest.mark.django_db(transaction=True)
def test_cash_limits_survive_source_and_outflow_corrections() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-cash-corrections")
    organization_id = creation.organization.pk
    _make_period(owner, organization_id, timezone.localdate())
    category = create_category(
        owner,
        organization_id,
        kind="direct_cost",
        name="Costo con caja",
        idempotency_key=uuid4(),
    )
    cost = record_actual_direct_cost(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=_venue_for_space(owner, organization_id, confirmed["space_id"]),
        category_id=category.pk,
        amount_value="100.00",
        currency_value="USD",
        economic_date=timezone.localdate(),
        description="Costo",
        evidence_reference="CASH-GUARD-COST",
        idempotency_key=uuid4(),
    )
    outflow = record_cash_movement(
        owner,
        organization_id,
        direction="outflow",
        source_kind="direct_cost",
        source_id=cost.pk,
        original_outflow_id=None,
        amount_value="80.00",
        economic_date=timezone.localdate(),
        reason="Salida",
        evidence_reference="CASH-GUARD-OUT",
        idempotency_key=uuid4(),
    )
    record_cash_movement(
        owner,
        organization_id,
        direction="recovery",
        source_kind="direct_cost",
        source_id=cost.pk,
        original_outflow_id=outflow.pk,
        amount_value="30.00",
        economic_date=timezone.localdate(),
        reason="Recuperación",
        evidence_reference="CASH-GUARD-REC",
        idempotency_key=uuid4(),
    )
    with pytest.raises(FinanceError) as source_error:
        correct_direct_cost(
            owner,
            organization_id,
            direct_cost_id=cost.pk,
            direction="decrease",
            amount_value="60.00",
            economic_date=timezone.localdate(),
            reason="Corrección incompatible",
            evidence_reference="CASH-GUARD-CORR",
            idempotency_key=uuid4(),
        )
    assert source_error.value.code == "cash_exceeds_source"
    with pytest.raises(FinanceError) as recovery_error:
        correct_cash_movement(
            owner,
            organization_id,
            cash_movement_id=outflow.pk,
            direction="decrease",
            amount_value="60.00",
            economic_date=timezone.localdate(),
            reason="Corrección incompatible",
            idempotency_key=uuid4(),
        )
    assert recovery_error.value.code == "recovery_exceeds_outflow"


@pytest.mark.django_db
def test_finance_http_openapi_and_csv_are_exposed_without_generic_mutation() -> None:
    owner, creation, *_ = _confirmed("finance-http")
    organization_id = creation.organization.pk
    _make_period(owner, organization_id, timezone.localdate())
    client = Client()
    csrf = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
    logged_in = client.post(
        "/api/v1/auth/login/",
        data={"email": owner.email, "password": "correct-horse-battery-staple-receivables-42"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert logged_in.status_code == 200
    overview = client.get(f"/api/v1/organizations/{organization_id}/finance/overview/")
    assert overview.status_code == 200
    assert overview.json()["presented"]["recognized_revenue"] == "0.00"
    export = client.get(f"/api/v1/organizations/{organization_id}/finance/export/")
    assert export.status_code == 200
    assert export["Content-Type"].startswith("text/csv")

    schema = cast(Any, SchemaGenerator)().get_schema(request=None, public=True)
    assert schema is not None
    paths = schema["paths"]
    prefix = "/api/v1/organizations/{organization_id}/finance/"
    assert prefix + "overview/" in paths
    assert prefix + "direct-cost-plans/" in paths
    assert prefix + "recognition-adjustments/" in paths
    assert all(
        "delete" not in operations and "patch" not in operations
        for path, operations in paths.items()
        if path.startswith(prefix)
    )
