"""Pruebas de integración del esquema de identidad en PostgreSQL."""

from __future__ import annotations

import pytest
from django.db import connection

from claridez.identity.models import User

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_identity_constraints_and_indexes_exist_in_postgresql() -> None:
    assert connection.vendor == "postgresql"

    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, User._meta.db_table)
        cursor.execute(
            """
            SELECT
                current_user,
                current_database(),
                pg_get_userbyid(table_class.relowner),
                table_class.relrowsecurity,
                table_class.relforcerowsecurity
            FROM pg_class AS table_class
            JOIN pg_namespace AS namespace ON namespace.oid = table_class.relnamespace
            WHERE namespace.nspname = 'public' AND table_class.relname = %s
            """,
            (User._meta.db_table,),
        )
        database_user, database_name, owner, rls_enabled, rls_forced = cursor.fetchone()

    assert database_user == "claridez_test_runner"
    assert database_name == "claridez_test"
    assert owner == "claridez_test_runner"
    assert rls_enabled is False
    assert rls_forced is False
    assert constraints["identity_user_email_canonical"]["check"] is True
    assert constraints["identity_user_status_active_consistent"]["check"] is True
    assert constraints["identity_user_security_version_positive"]["check"] is True
    assert any(
        details["unique"] and details["columns"] == ["email"] for details in constraints.values()
    )
    assert any(
        details["index"] and details["columns"] == ["email"] for details in constraints.values()
    )


def test_no_private_tenant_tables_exist_before_later_subiterations() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND (
                tablename LIKE 'tenancy%%'
                OR tablename = 'organizations_organizationsettings'
              )
            """
        )
        tables = cursor.fetchall()

    assert tables == []
