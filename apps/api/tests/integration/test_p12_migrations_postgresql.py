"""Instalación limpia y actualización reversible P11 -> P12."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _restore_head() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_p11_final_to_p12_is_empty_ordered_and_reapplicable() -> None:
    try:
        MigrationExecutor(connection).migrate(
            [
                ("finance", "0005_baseline_and_expense_cash_attribution"),
                ("resources", None),
            ]
        )
        assert not any(
            name.startswith("resources_") for name in connection.introspection.table_names()
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT app, name FROM django_migrations "
                "WHERE app IN ('resources', 'finance') ORDER BY app, name"
            )
            rows = cursor.fetchall()
            assert ("resources", "0001_initial") not in rows
            assert ("resources", "0002_temporal_asset_availability_hardening") not in rows
            assert ("finance", "0006_resources_receipt_provenance") not in rows

        _restore_head()
        tables = set(connection.introspection.table_names())
        assert "resources_supplier" in tables
        assert "resources_stockmovement" in tables
        assert "finance_financialsourcereference" in tables
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM resources_supplier")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT count(*) FROM resources_stockmovement")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT count(*) FROM resources_supplyreceiptline")
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                "SELECT app, name FROM django_migrations "
                "WHERE (app = 'resources' AND name IN ("
                "'0001_initial', '0002_temporal_asset_availability_hardening')) "
                "OR (app = 'finance' AND name = '0006_resources_receipt_provenance') "
                "ORDER BY app, name"
            )
            assert cursor.fetchall() == [
                ("finance", "0006_resources_receipt_provenance"),
                ("resources", "0001_initial"),
                ("resources", "0002_temporal_asset_availability_hardening"),
            ]

        MigrationExecutor(connection).migrate(
            [
                ("finance", "0005_baseline_and_expense_cash_attribution"),
                ("resources", None),
            ]
        )
        _restore_head()
    finally:
        _restore_head()
