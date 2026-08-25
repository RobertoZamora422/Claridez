"""Cutover, RLS y privilegios PostgreSQL reales de Operations P13."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from claridez.operations.advanced_models import OperationalPlanSnapshot
from claridez.operations.models import EventPreparation, PreparationItem
from claridez.operations.services import create_item, read_event
from claridez.organizations.capabilities import Capability
from claridez.organizations.services import create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.settings.environment import load_bootstrap_settings
from tests.test_operations import _confirmed, _user

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

P13_APPEND_ONLY_TABLES = (
    "operations_templatereadinessdefinition",
    "operations_templatephasedefinition",
    "operations_templateroledefinition",
    "operations_templateresourceneed",
    "operations_operationalplansnapshot",
    "operations_operationalverificationevent",
    "operations_operationalphasefact",
    "operations_operationalresponsibility",
    "operations_operationalincidentevent",
    "operations_operationalchangedecision",
    "operations_readinessdeviation",
    "operations_operationalresourcewindow",
    "operations_operationalevidence",
    "operations_posteventclose",
    "operations_posteventclosecorrection",
    "operations_operationcommand",
)
P13_PROJECTION_TABLES = (
    "operations_operationaltemplate",
    "operations_operationaltemplateversion",
    "operations_operationalverification",
    "operations_operationalincident",
    "operations_operationalchangeproposal",
)
P13_PRIVATE_TABLES = (*P13_APPEND_ONLY_TABLES, *P13_PROJECTION_TABLES)


def _restore_head() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


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


def test_p12_final_to_p13_classifies_existing_items_without_inventing_history() -> None:
    owner = _user("p13-cutover@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="P13 cutover")
    reservation = _confirmed(owner, creation.organization.pk)
    reservation_id = UUID(str(reservation["id"]))
    detail = read_event(owner, creation.organization.pk, reservation_id=reservation_id)
    manual, created = create_item(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        client_request_id=uuid4(),
        values={
            "title": "Ítem manual previo a P13",
            "section": "definitions",
            "is_required": False,
        },
    )
    assert created is True
    manual_id = UUID(str(manual["item"]["id"]))
    assert detail["preparation"]["items"]
    try:
        MigrationExecutor(connection).migrate(
            [
                (
                    "operations",
                    "0004_remove_eventpreparation_operations_preparation_status_valid_and_more",
                ),
                ("resources", "0002_temporal_asset_availability_hardening"),
            ]
        )
        tables = set(connection.introspection.table_names())
        assert "operations_operationalplansnapshot" not in tables
        assert "operations_operationalresourcewindow" not in tables
        assert "operations_operationalphasefact" not in tables

        _restore_head()
        with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
            preparation = EventPreparation.objects.get(pk=reservation_id)
            baseline = tuple(
                PreparationItem.objects.filter(preparation=preparation, baseline_key__isnull=False)
            )
            migrated_manual = PreparationItem.objects.get(pk=manual_id)
            assert len(baseline) == 7
            assert {row.source_kind for row in baseline} == {
                PreparationItem.SourceKind.BASELINE_5_2
            }
            assert migrated_manual.source_kind == PreparationItem.SourceKind.MANUAL
            assert not OperationalPlanSnapshot.objects.filter(preparation=preparation).exists()
        with connection.cursor() as cursor:
            for table in (
                "operations_operationalplansnapshot",
                "operations_operationalresourcewindow",
                "operations_operationalphasefact",
                "operations_operationalincident",
                "operations_posteventclose",
            ):
                cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
                assert cursor.fetchone()[0] == 0
    finally:
        _restore_head()


def test_p13_force_rls_and_claridez_app_minimum_privileges_are_effective() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(%s) ORDER BY relname",
            [list(P13_PRIVATE_TABLES)],
        )
        assert cursor.fetchall() == sorted((table, True, True) for table in P13_PRIVATE_TABLES)
        for table in P13_APPEND_ONLY_TABLES:
            cursor.execute(
                "SELECT has_table_privilege('claridez_app', %s, 'SELECT'), "
                "has_table_privilege('claridez_app', %s, 'INSERT'), "
                "has_table_privilege('claridez_app', %s, 'UPDATE'), "
                "has_table_privilege('claridez_app', %s, 'DELETE'), "
                "has_table_privilege('claridez_app', %s, 'TRUNCATE')",
                [table] * 5,
            )
            assert cursor.fetchone() == (True, True, False, False, False)
        for table in P13_PROJECTION_TABLES:
            cursor.execute(
                "SELECT has_table_privilege('claridez_app', %s, 'SELECT'), "
                "has_table_privilege('claridez_app', %s, 'INSERT'), "
                "has_table_privilege('claridez_app', %s, 'UPDATE'), "
                "has_table_privilege('claridez_app', %s, 'DELETE'), "
                "has_table_privilege('claridez_app', %s, 'TRUNCATE')",
                [table] * 5,
            )
            assert cursor.fetchone() == (True, True, True, False, False)
        for table in (
            "resources_resourcerequirement",
            "resources_resourceassignment",
            "resources_resourcecapacityallocation",
        ):
            cursor.execute(
                "SELECT has_table_privilege('claridez_app', %s, 'DELETE'), "
                "has_table_privilege('claridez_app', %s, 'TRUNCATE')",
                [table, table],
            )
            assert cursor.fetchone() == (False, False)

    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                "UPDATE operations_operationalphasefact SET observed_at = observed_at WHERE false"
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("DELETE FROM operations_operationaltemplate WHERE false")
