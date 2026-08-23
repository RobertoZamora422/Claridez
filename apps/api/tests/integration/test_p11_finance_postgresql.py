from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from queue import Queue
from threading import Barrier, Event
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from claridez.finance.errors import FinanceError
from claridez.finance.models import (
    ActualDirectCost,
    DirectCostPlanRevision,
    FinanceCategory,
    FinanceCommand,
    OperationalPeriod,
)
from claridez.finance.services import (
    close_period,
    create_category,
    create_period,
    finance_overview,
    publish_direct_cost_plan,
    record_actual_direct_cost,
    record_cash_movement,
    record_expense,
)
from claridez.identity.models import User
from claridez.operations.services import (
    assign_preparation,
    mark_ready,
    read_event,
    start_event,
    update_item,
)
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.models import Membership
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.receivables.services import record_payment_authorized, record_refund_authorized
from claridez.settings.environment import load_bootstrap_settings
from tests.test_finance import _prepare_and_start
from tests.test_receivables import _confirmed, _owner

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

PRIVATE_TABLES = (
    "finance_financecategory",
    "finance_operationalperiod",
    "finance_periodclosesnapshot",
    "finance_directcostplanrevision",
    "finance_directcostplanline",
    "finance_operationalcostevidence",
    "finance_evidencedecision",
    "finance_actualdirectcost",
    "finance_directcostcorrection",
    "finance_recurringexpenserule",
    "finance_expenseoccurrence",
    "finance_expenseallocation",
    "finance_expenseoccurrencecorrection",
    "finance_operatingbudgetrevision",
    "finance_operatingbudgetline",
    "finance_operatingcashmovement",
    "finance_cashmovementcorrection",
    "finance_recognitionadjustment",
    "finance_recognitionadjustmentcorrection",
    "finance_financecommand",
)


def _app_connection() -> psycopg.Connection[tuple[object, ...]]:
    settings = load_bootstrap_settings()
    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.test_db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        autocommit=True,
    )


def _period(owner: User, organization_id: UUID) -> OperationalPeriod:
    today = timezone.localdate()
    starts_on = today.replace(day=1)
    ends_on = (
        date(starts_on.year + 1, 1, 1)
        if starts_on.month == 12
        else date(starts_on.year, starts_on.month + 1, 1)
    )
    return create_period(
        owner,
        organization_id,
        starts_on=starts_on,
        ends_on=ends_on,
        label="Periodo PostgreSQL",
        idempotency_key=uuid4(),
    )


def _venue(owner: User, organization_id: UUID, space_id: UUID | str) -> UUID:
    return next(
        UUID(str(venue["id"]))
        for venue in list_venues(owner, organization_id)
        for space in venue["spaces"]
        if str(space["id"]) == str(space_id)
    )


def _ready(owner: User, organization_id: UUID, reservation_id: UUID | str) -> dict[str, Any]:
    target = UUID(str(reservation_id))
    detail = read_event(owner, organization_id, reservation_id=target)
    membership_id = Membership.objects.get(
        organization_id=organization_id, user=owner, status=Membership.Status.ACTIVE
    ).pk
    assigned = assign_preparation(
        owner,
        organization_id,
        reservation_id=target,
        revision=detail["preparation"]["revision"],
        responsible_membership_id=membership_id,
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
    return mark_ready(owner, organization_id, reservation_id=target, revision=revision)


def test_finance_force_rls_two_tenants_and_app_privileges() -> None:
    first_owner, first = _owner("finance-rls-a")
    second_owner, second = _owner("finance-rls-b")
    first_category = create_category(
        first_owner,
        first.organization.pk,
        kind="direct_cost",
        name="Aislada A",
        idempotency_key=uuid4(),
    )
    create_category(
        second_owner,
        second.organization.pk,
        kind="direct_cost",
        name="Aislada B",
        idempotency_key=uuid4(),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(%s) ORDER BY relname",
            [list(PRIVATE_TABLES)],
        )
        assert cursor.fetchall() == sorted((table, True, True) for table in PRIVATE_TABLES)
        cursor.execute(
            "SELECT has_table_privilege('claridez_app', 'finance_financecategory', 'SELECT'), "
            "has_table_privilege('claridez_app', 'finance_financecategory', 'INSERT'), "
            "has_table_privilege('claridez_app', 'finance_financecategory', 'UPDATE'), "
            "has_table_privilege('claridez_app', 'finance_financecategory', 'DELETE'), "
            "has_table_privilege('claridez_app', 'finance_financecategory', 'TRUNCATE')"
        )
        assert cursor.fetchone() == (True, True, False, False, False)

    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            (str(first.organization.pk),),
        )
        cursor.execute("SELECT organization_id, name FROM finance_financecategory")
        assert cursor.fetchall() == [(first.organization.pk, "Aislada A")]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                "UPDATE finance_financecategory SET name = 'Bypass' WHERE id = %s",
                (first_category.pk,),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                "DELETE FROM finance_financecategory WHERE id = %s", (first_category.pk,)
            )


def test_finance_orm_bulk_and_direct_sql_guard_append_only_history() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-guard-paths")
    organization_id = creation.organization.pk
    _period(owner, organization_id)
    category = create_category(
        owner,
        organization_id,
        kind="direct_cost",
        name="Protegida",
        idempotency_key=uuid4(),
    )
    cost = record_actual_direct_cost(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=_venue(owner, organization_id, confirmed["space_id"]),
        category_id=category.pk,
        amount_value="100.00",
        currency_value="USD",
        economic_date=timezone.localdate(),
        description="Costo protegido",
        evidence_reference="GUARD-1",
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ):
        category.name = "Bulk bypass"
        with pytest.raises(DatabaseError), transaction.atomic():
            FinanceCategory.objects.bulk_update([category], ["name"])
        with pytest.raises(DatabaseError), transaction.atomic():
            ActualDirectCost.objects.filter(pk=cost.pk).update(amount="1.00")
        with pytest.raises(DatabaseError), transaction.atomic():
            ActualDirectCost.objects.filter(pk=cost.pk).delete()

    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            (str(organization_id),),
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("TRUNCATE finance_actualdirectcost")


def test_finance_direct_sql_cannot_break_cash_source_invariant() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-cash-sql-guard")
    organization_id = creation.organization.pk
    period = _period(owner, organization_id)
    category = create_category(
        owner,
        organization_id,
        kind="direct_cost",
        name="Origen protegido",
        idempotency_key=uuid4(),
    )
    cost = record_actual_direct_cost(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=_venue(owner, organization_id, confirmed["space_id"]),
        category_id=category.pk,
        amount_value="100.00",
        currency_value="USD",
        economic_date=timezone.localdate(),
        description="Costo protegido",
        evidence_reference="SQL-CASH-SOURCE",
        idempotency_key=uuid4(),
    )
    record_cash_movement(
        owner,
        organization_id,
        direction="outflow",
        source_kind="direct_cost",
        source_id=cost.pk,
        original_outflow_id=None,
        amount_value="80.00",
        expense_attributions=[],
        economic_date=timezone.localdate(),
        reason="Salida protegida",
        evidence_reference="SQL-CASH-OUT",
        idempotency_key=uuid4(),
    )
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ) as authorization:
        membership_id = authorization.membership_id
    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            (str(organization_id),),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO finance_directcostcorrection "
                "(id, organization_id, direct_cost_id, direction, amount, currency, "
                "economic_date, registration_period_id, reason, evidence_reference, "
                "recorded_by_membership_id, recorded_at, created_at) "
                "VALUES (%s, %s, %s, 'decrease', 30.00, 'USD', %s, %s, %s, %s, %s, %s, %s)",
                (
                    uuid4(),
                    organization_id,
                    cost.pk,
                    timezone.localdate(),
                    period.pk,
                    "Intento SQL",
                    "SQL-CASH-CORRECTION",
                    membership_id,
                    timezone.now(),
                    timezone.now(),
                ),
            )


def test_baseline_rejects_retrodated_sql_and_bulk_after_execution_started() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-baseline-sql")
    organization_id = creation.organization.pk
    _period(owner, organization_id)
    venue_id = _venue(owner, organization_id, confirmed["space_id"])
    category = create_category(
        owner,
        organization_id,
        kind="direct_cost",
        name="Baseline SQL",
        idempotency_key=uuid4(),
    )
    baseline = publish_direct_cost_plan(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=venue_id,
        currency_value="USD",
        reason="Ganadora antes del inicio",
        lines=[{"category_id": category.pk, "description": "Base", "amount": "90.00"}],
        idempotency_key=uuid4(),
    )
    _prepare_and_start(owner, organization_id, confirmed["id"])
    retrodated = timezone.now() - timedelta(days=30)
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ) as authorization:
        membership_id = authorization.membership_id
        bypass = DirectCostPlanRevision(
            organization_id=organization_id,
            root_reservation_id=reservation["root_id"],
            venue_id=venue_id,
            revision=2,
            currency="USD",
            reason="Bulk retrodatado",
            published_by_membership_id=membership_id,
            published_at=retrodated,
        )
        with pytest.raises(DatabaseError), transaction.atomic():
            DirectCostPlanRevision.objects.bulk_create([bypass])

    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            (str(organization_id),),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO finance_directcostplanrevision "
                "(id, organization_id, root_reservation_id, venue_id, revision, currency, "
                "reason, published_by_membership_id, published_at, created_at) "
                "VALUES (%s, %s, %s, %s, 2, 'USD', %s, %s, %s, %s)",
                (
                    uuid4(),
                    organization_id,
                    reservation["root_id"],
                    venue_id,
                    "SQL retrodatado",
                    membership_id,
                    retrodated,
                    timezone.now(),
                ),
            )
    result = finance_overview(owner, organization_id, root_reservation_id=reservation["root_id"])
    events = cast(list[dict[str, object]], result["events"])
    assert events[0]["baseline_plan_revision_id"] == baseline.pk


def test_plan_publication_and_execution_start_are_serialized_on_preparation() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-baseline-race")
    organization_id = creation.organization.pk
    _period(owner, organization_id)
    venue_id = _venue(owner, organization_id, confirmed["space_id"])
    category = create_category(
        owner,
        organization_id,
        kind="direct_cost",
        name="Baseline carrera",
        idempotency_key=uuid4(),
    )
    initial = publish_direct_cost_plan(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=venue_id,
        currency_value="USD",
        reason="Inicial",
        lines=[{"category_id": category.pk, "description": "Base", "amount": "80.00"}],
        idempotency_key=uuid4(),
    )
    ready = _ready(owner, organization_id, confirmed["id"])
    revision = ready["preparation"]["revision"]
    barrier = Barrier(2)

    def begin_execution() -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            barrier.wait(timeout=20)
            start_event(
                actor,
                organization_id,
                reservation_id=confirmed["id"],
                revision=revision,
            )
            return "started"
        finally:
            close_old_connections()

    def publish() -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            barrier.wait(timeout=20)
            try:
                row = publish_direct_cost_plan(
                    actor,
                    organization_id,
                    root_reservation_id=reservation["root_id"],
                    venue_id=venue_id,
                    currency_value="USD",
                    reason="Candidata concurrente",
                    lines=[{"category_id": category.pk, "description": "Base", "amount": "95.00"}],
                    idempotency_key=uuid4(),
                )
                return str(row.pk)
            except FinanceError as error:
                return error.code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        start_future = pool.submit(begin_execution)
        publish_future = pool.submit(publish)
        assert start_future.result(timeout=40) == "started"
        publication = publish_future.result(timeout=40)

    result = finance_overview(owner, organization_id, root_reservation_id=reservation["root_id"])
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ):
        plans = DirectCostPlanRevision.objects.filter(
            organization_id=organization_id,
            root_reservation_id=reservation["root_id"],
        ).order_by("revision")
        assert plans.count() in {1, 2}
        winner = plans.last()
    assert winner is not None
    events = cast(list[dict[str, object]], result["events"])
    assert events[0]["baseline_plan_revision_id"] == winner.pk
    if publication == "cost_baseline_already_frozen":
        assert winner.pk == initial.pk
    else:
        assert publication == str(winner.pk)


@pytest.mark.parametrize(
    ("pending_kind", "expected_cash"),
    [("payment", Decimal("25.00")), ("refund", Decimal("-20.00"))],
)
def test_period_close_classifies_only_exact_committed_p10_sources(
    pending_kind: str, expected_cash: Decimal
) -> None:
    owner, creation, person, _, reservation, _ = _confirmed(f"finance-close-{pending_kind}")
    organization_id = creation.organization.pk
    january = create_period(
        owner,
        organization_id,
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 2, 1),
        label="Enero concurrente",
        idempotency_key=uuid4(),
    )
    february = create_period(
        owner,
        organization_id,
        starts_on=date(2026, 2, 1),
        ends_on=date(2026, 3, 1),
        label="Febrero correctivo",
        idempotency_key=uuid4(),
    )
    ready = Event()
    release = Event()
    source_ids: Queue[UUID] = Queue()
    refundable_payment_id: UUID | None = None

    if pending_kind == "refund":

        def create_refundable_payment() -> UUID:
            close_old_connections()
            try:
                actor = User.objects.get(pk=owner.pk)
                with authorized_tenant_scope(
                    actor, organization_id, Capability.RECEIVABLES_RECORD_PAYMENT
                ) as authorization:
                    row = record_payment_authorized(
                        authorization,
                        counterparty_person_id=UUID(str(person["id"])),
                        root_reservation_id=UUID(str(reservation["root_id"])),
                        amount_value="100.00",
                        currency_value="USD",
                        reported_at=timezone.now(),
                        method="cash",
                        reference="PAGO-DEVOLVIBLE",
                        observation="Preparación de carrera de devolución",
                        provenance="manual",
                        evidence_level="internal_report",
                        idempotency_key=uuid4(),
                    )
                    return row.pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as setup_pool:
            refundable_payment_id = setup_pool.submit(create_refundable_payment).result(timeout=40)

    def pending_p10_commit() -> UUID:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            capability = (
                Capability.RECEIVABLES_RECORD_PAYMENT
                if pending_kind == "payment"
                else Capability.RECEIVABLES_RECORD_REFUND
            )
            with authorized_tenant_scope(actor, organization_id, capability) as authorization:
                if pending_kind == "payment":
                    payment_source = record_payment_authorized(
                        authorization,
                        counterparty_person_id=UUID(str(person["id"])),
                        root_reservation_id=UUID(str(reservation["root_id"])),
                        amount_value="25.00",
                        currency_value="USD",
                        reported_at=datetime(
                            2026, 1, 10, 12, 0, tzinfo=ZoneInfo("America/Guayaquil")
                        ),
                        method="cash",
                        reference="P10-PENDIENTE",
                        observation="Commit posterior al cierre",
                        provenance="manual",
                        evidence_level="internal_report",
                        idempotency_key=uuid4(),
                    )
                    source_id = payment_source.pk
                else:
                    assert refundable_payment_id is not None
                    refund_source = record_refund_authorized(
                        authorization,
                        payment_id=refundable_payment_id,
                        amount_value="20.00",
                        currency_value="USD",
                        refunded_at=datetime(
                            2026, 1, 12, 12, 0, tzinfo=ZoneInfo("America/Guayaquil")
                        ),
                        method="cash",
                        reference="DEV-PENDIENTE",
                        reason="Commit posterior al cierre",
                        idempotency_key=uuid4(),
                    )
                    source_id = refund_source.pk
                source_ids.put(source_id)
                ready.set()
                assert release.wait(timeout=40)
                return source_id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(pending_p10_commit)
        assert ready.wait(timeout=20)
        source_id = source_ids.get(timeout=5)
        try:
            closed = close_period(
                owner, organization_id, period_id=january.pk, idempotency_key=uuid4()
            )
        finally:
            release.set()
        assert pending.result(timeout=40) == source_id

    closed_references = cast(list[dict[str, object]], closed.snapshot["p10_source_references"])
    assert all(str(reference["source_id"]) != str(source_id) for reference in closed_references)
    february_result = finance_overview(owner, organization_id, period_id=february.pk)
    prior = cast(dict[str, object], february_result["prior_period_adjustments"])
    assert prior["p10_cash"] == expected_cash
    later_references = cast(list[dict[str, object]], february_result["p10_source_references"])
    assert any(str(reference["source_id"]) == str(source_id) for reference in later_references)


def test_expense_cash_allocation_limit_is_serialized_and_sql_validated() -> None:
    owner, creation, _, _, _, confirmed = _confirmed("finance-expense-cash-race")
    organization_id = creation.organization.pk
    period = _period(owner, organization_id)
    venue_id = _venue(owner, organization_id, confirmed["space_id"])
    category = create_category(
        owner,
        organization_id,
        kind="variable_expense",
        name="Gasto con caja atribuida",
        idempotency_key=uuid4(),
    )
    expense = record_expense(
        owner,
        organization_id,
        category_id=category.pk,
        expense_type="variable",
        amount_value="200.00",
        currency_value="USD",
        economic_date=timezone.localdate(),
        description="Dos ámbitos",
        evidence_reference="EXP-CASH-RACE",
        allocations=[
            {
                "scope": "business",
                "root_reservation_id": None,
                "venue_id": None,
                "amount": "100.00",
            },
            {
                "scope": "venue",
                "root_reservation_id": None,
                "venue_id": venue_id,
                "amount": "100.00",
            },
        ],
        idempotency_key=uuid4(),
    )
    barrier = Barrier(2)

    def business_outflow() -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            barrier.wait(timeout=20)
            try:
                row = record_cash_movement(
                    actor,
                    organization_id,
                    direction="outflow",
                    source_kind="expense",
                    source_id=expense.pk,
                    original_outflow_id=None,
                    amount_value="60.00",
                    expense_attributions=[
                        {
                            "scope": "business",
                            "root_reservation_id": None,
                            "venue_id": None,
                            "amount": "60.00",
                        }
                    ],
                    economic_date=timezone.localdate(),
                    reason="Carrera por ámbito",
                    evidence_reference=str(uuid4()),
                    idempotency_key=uuid4(),
                )
                return str(row.pk)
            except FinanceError as error:
                return error.code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=40)
            for future in (pool.submit(business_outflow), pool.submit(business_outflow))
        ]
    assert results.count("cash_exceeds_allocation") == 1

    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ) as authorization:
        membership_id = authorization.membership_id
    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            (str(organization_id),),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO finance_operatingcashmovement "
                "(id, organization_id, direction, source_kind, source_id, original_outflow_id, "
                "amount, expense_attributions, currency, economic_date, registration_period_id, "
                "reason, evidence_reference, recorded_by_membership_id, recorded_at, created_at) "
                "VALUES (%s, %s, 'outflow', 'expense', %s, NULL, 10.00, %s::jsonb, 'USD', "
                "%s, %s, %s, %s, %s, %s, %s)",
                (
                    uuid4(),
                    organization_id,
                    expense.pk,
                    '[{"scope":"venue","root_reservation_id":null,'
                    f'"venue_id":"{venue_id}","amount":"5.00"}}]',
                    timezone.localdate(),
                    period.pk,
                    "SQL sin suma exacta",
                    "EXP-CASH-SQL",
                    membership_id,
                    timezone.now(),
                    timezone.now(),
                ),
            )


def test_finance_idempotency_and_cash_limit_are_serialized() -> None:
    owner, creation, _, _, reservation, confirmed = _confirmed("finance-concurrency")
    organization_id = creation.organization.pk
    _period(owner, organization_id)
    category = create_category(
        owner,
        organization_id,
        kind="direct_cost",
        name="Concurrente",
        idempotency_key=uuid4(),
    )
    cost = record_actual_direct_cost(
        owner,
        organization_id,
        root_reservation_id=reservation["root_id"],
        venue_id=_venue(owner, organization_id, confirmed["space_id"]),
        category_id=category.pk,
        amount_value="100.00",
        currency_value="USD",
        economic_date=timezone.localdate(),
        description="Costo concurrente",
        evidence_reference="RACE-COST",
        idempotency_key=uuid4(),
    )
    barrier = Barrier(2)

    def outflow() -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            barrier.wait(timeout=20)
            try:
                row = record_cash_movement(
                    actor,
                    organization_id,
                    direction="outflow",
                    source_kind="direct_cost",
                    source_id=cost.pk,
                    original_outflow_id=None,
                    amount_value="80.00",
                    expense_attributions=[],
                    economic_date=timezone.localdate(),
                    reason="Carrera",
                    evidence_reference=str(uuid4()),
                    idempotency_key=uuid4(),
                )
                return str(row.pk)
            except FinanceError as error:
                return error.code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(outflow), pool.submit(outflow))
        results = [future.result(timeout=40) for future in futures]
    assert results.count("cash_exceeds_source") == 1

    same_key = uuid4()
    replay_barrier = Barrier(2)

    def same_category() -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            replay_barrier.wait(timeout=20)
            row = create_category(
                actor,
                organization_id,
                kind="variable_expense",
                name="Retry único",
                idempotency_key=same_key,
            )
            return str(row.pk)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = [
            future.result(timeout=40)
            for future in (pool.submit(same_category), pool.submit(same_category))
        ]
    assert len(set(ids)) == 1
    with authorized_tenant_scope(owner, organization_id, Capability.FINANCE_READ):
        assert (
            FinanceCommand.objects.filter(
                command_type="create_category", idempotency_key=same_key
            ).count()
            == 1
        )


def test_p10_final_to_current_finance_head_and_back_is_reapplicable() -> None:
    def restore() -> None:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    try:
        MigrationExecutor(connection).migrate([("finance", None)])
        assert "finance_financecategory" not in connection.introspection.table_names()
        restore()
        assert set(PRIVATE_TABLES).issubset(connection.introspection.table_names())
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT app, name FROM django_migrations WHERE app = 'finance' ORDER BY name"
            )
            assert cursor.fetchall() == [
                ("finance", "0001_initial"),
                ("finance", "0002_integrity_rls_and_guardians"),
                ("finance", "0003_deferred_guard_hardening"),
                ("finance", "0004_cash_invariant_hardening"),
                ("finance", "0005_baseline_and_expense_cash_attribution"),
                ("finance", "0006_resources_receipt_provenance"),
            ]
    finally:
        restore()
