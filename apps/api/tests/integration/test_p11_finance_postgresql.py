from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from claridez.finance.errors import FinanceError
from claridez.finance.models import (
    ActualDirectCost,
    FinanceCategory,
    FinanceCommand,
    OperationalPeriod,
)
from claridez.finance.services import (
    create_category,
    create_period,
    record_actual_direct_cost,
    record_cash_movement,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.settings.environment import load_bootstrap_settings
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


def test_p10_final_to_p11_and_back_to_head_is_reapplicable() -> None:
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
            ]
    finally:
        restore()
