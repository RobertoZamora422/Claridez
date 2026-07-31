"""Pruebas reales del contrato de PostgreSQL y sus roles locales."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from django.db import connection
from psycopg import Connection, sql
from psycopg.rows import dict_row

from claridez.settings.environment import BootstrapSettings, load_bootstrap_settings
from tools.local_database import prepare_local_database

pytestmark = pytest.mark.integration


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
