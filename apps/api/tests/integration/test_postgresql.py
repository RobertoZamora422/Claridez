"""Pruebas reales del contrato de PostgreSQL y sus roles locales."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from django.db import connection
from psycopg import Connection, sql
from psycopg.rows import dict_row

from claridez.settings.environment import BootstrapSettings, load_bootstrap_settings
from tools.local_database import check_application_connection, prepare_local_database

pytestmark = pytest.mark.integration
API_ROOT = Path(__file__).resolve().parents[2]


def _connect(
    settings: BootstrapSettings,
    *,
    database: str,
    user: str,
    password: str,
) -> Connection[dict[str, Any]]:
    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=database,
        user=user,
        password=password,
        connect_timeout=settings.db_connect_timeout,
        options="-c timezone=UTC",
        autocommit=True,
        row_factory=dict_row,
    )


@pytest.mark.django_db
def test_django_creates_real_postgresql_test_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                current_user,
                current_database(),
                current_setting('server_version_num'),
                current_setting('TimeZone')
            """
        )
        user, database, version, timezone = cursor.fetchone()

    assert user == "claridez_test_runner"
    assert database == "claridez_test"
    assert str(version).startswith("17")
    assert timezone == "UTC"


def test_exact_role_attributes() -> None:
    settings = load_bootstrap_settings()
    with _connect(
        settings,
        database=settings.postgres_admin_db,
        user=settings.postgres_admin_user,
        password=settings.postgres_admin_password.get_secret_value(),
    ) as admin:
        rows = admin.execute(
            """
            SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
            FROM pg_roles
            WHERE rolname = ANY(%s)
            ORDER BY rolname
            """,
            ([settings.db_user, settings.migration_db_user, settings.test_db_user],),
        ).fetchall()

    roles = {row["rolname"]: row for row in rows}
    assert set(roles) == {"claridez_app", "claridez_migrator", "claridez_test_runner"}
    assert roles["claridez_app"]["rolcreatedb"] is False
    assert roles["claridez_migrator"]["rolcreatedb"] is False
    assert roles["claridez_test_runner"]["rolcreatedb"] is True
    for role in roles.values():
        assert role["rolsuper"] is False
        assert role["rolcreaterole"] is False
        assert role["rolbypassrls"] is False


def test_migrator_owns_ddl_and_application_is_limited_to_dml() -> None:
    settings = load_bootstrap_settings()
    probe_table = "claridez_platform_privilege_probe"

    with _connect(
        settings,
        database=settings.db_name,
        user=settings.migration_db_user,
        password=settings.migration_db_password.get_secret_value(),
    ) as migrator:
        migrator.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(probe_table)))
        migrator.execute(
            sql.SQL(
                "CREATE TABLE {} (id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                "value text NOT NULL)"
            ).format(sql.Identifier(probe_table))
        )

    try:
        prepare_local_database(settings, quiet=True)
        with _connect(
            settings,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password.get_secret_value(),
        ) as application:
            row = application.execute(
                sql.SQL("INSERT INTO {} (value) VALUES (%s) RETURNING value").format(
                    sql.Identifier(probe_table)
                ),
                ("technical-probe",),
            ).fetchone()
            assert row is not None and row["value"] == "technical-probe"

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                application.execute("CREATE TABLE forbidden_ddl (id integer)")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                application.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(probe_table)))
    finally:
        with _connect(
            settings,
            database=settings.db_name,
            user=settings.migration_db_user,
            password=settings.migration_db_password.get_secret_value(),
        ) as migrator:
            migrator.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(probe_table)))


def test_finance_migrations_then_prepare_preserve_append_only_runtime_grants() -> None:
    settings = load_bootstrap_settings()
    subprocess.run(
        [
            sys.executable,
            "manage.py",
            "migrate",
            "finance",
            "0006",
            "--settings=claridez.settings.migration",
            "--noinput",
        ],
        cwd=API_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    with _connect(
        settings,
        database=settings.db_name,
        user=settings.migration_db_user,
        password=settings.migration_db_password.get_secret_value(),
    ) as migrator:
        migration = migrator.execute(
            """
            SELECT name
            FROM django_migrations
            WHERE app = 'finance'
            ORDER BY applied DESC, name DESC
            LIMIT 1
            """
        ).fetchone()
        assert migration is not None
        assert migration["name"] == "0006_resources_receipt_provenance"

    prepare_local_database(settings, quiet=True)
    check_application_connection(settings)

    with _connect(
        settings,
        database=settings.db_name,
        user=settings.migration_db_user,
        password=settings.migration_db_password.get_secret_value(),
    ) as migrator:
        grants = migrator.execute(
            """
            SELECT
                tablename,
                has_table_privilege(
                    %s, 'public.' || quote_ident(tablename), 'SELECT'
                ) AS can_select,
                has_table_privilege(
                    %s, 'public.' || quote_ident(tablename), 'INSERT'
                ) AS can_insert,
                has_table_privilege(
                    %s, 'public.' || quote_ident(tablename), 'UPDATE'
                ) AS can_update,
                has_table_privilege(
                    %s, 'public.' || quote_ident(tablename), 'DELETE'
                ) AS can_delete,
                has_table_privilege(
                    %s, 'public.' || quote_ident(tablename), 'TRUNCATE'
                ) AS can_truncate
            FROM pg_tables
            WHERE schemaname = 'public' AND left(tablename, 8) = 'finance_'
            ORDER BY tablename
            """,
            (settings.db_user,) * 5,
        ).fetchall()
    assert len(grants) == 21
    assert all(
        row["can_select"]
        and row["can_insert"]
        and not row["can_update"]
        and not row["can_delete"]
        and not row["can_truncate"]
        for row in grants
    )

    with _connect(
        settings,
        database=settings.db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
    ) as application:
        application.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            (str(uuid4()),),
        )
        row = application.execute(
            "SELECT count(*) AS total FROM finance_financecategory"
        ).fetchone()
        assert row is not None and row["total"] == 0
