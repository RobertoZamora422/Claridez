"""Preparación, comprobación y reset protegido del PostgreSQL local."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg
from django.core.exceptions import ImproperlyConfigured
from psycopg import Connection, sql
from psycopg.rows import dict_row

API_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = API_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from claridez.settings.environment import BootstrapSettings, load_bootstrap_settings  # noqa: E402

EXPECTED_CLUSTER_NAME = "claridez-local"
EXPECTED_POSTGRESQL_MAJOR = 17
ROLE_SPECIFICATIONS: dict[str, dict[str, bool]] = {
    "claridez_migrator": {"rolsuper": False, "rolcreatedb": False},
    "claridez_app": {"rolsuper": False, "rolcreatedb": False},
    "claridez_test_runner": {"rolsuper": False, "rolcreatedb": True},
}
NO_DELETE_TABLES = {
    "organizations_organization",
    "organizations_membership",
    "organizations_organizationsettings",
    "commercial_person",
    "commercial_personrevision",
    "commercial_eventrequest",
    "commercial_quotationsequence",
    "commercial_quotation",
    "commercial_quotationversion",
    "commercial_reservation",
    "operations_eventpreparation",
    "operations_preparationitem",
    "operations_preparationtransition",
}


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
        options=(f"-c timezone=UTC -c statement_timeout={settings.db_statement_timeout_ms}"),
        autocommit=True,
        row_factory=dict_row,
    )


def _admin_connection(settings: BootstrapSettings) -> Connection[dict[str, Any]]:
    return _connect(
        settings,
        database=settings.postgres_admin_db,
        user=settings.postgres_admin_user,
        password=settings.postgres_admin_password.get_secret_value(),
    )


def _verify_expected_server(connection: Connection[dict[str, Any]]) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT
            current_setting('server_version_num')::integer AS server_version_num,
            current_setting('cluster_name') AS cluster_name,
            current_setting('server_encoding') AS server_encoding,
            current_setting('TimeZone') AS timezone
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("PostgreSQL no devolvió metadatos del servidor local.")
    if row["server_version_num"] // 10_000 != EXPECTED_POSTGRESQL_MAJOR:
        raise RuntimeError("La versión mayor de PostgreSQL local no es la esperada.")
    if row["cluster_name"] != EXPECTED_CLUSTER_NAME:
        raise RuntimeError("El clúster PostgreSQL no coincide con el entorno local esperado.")
    if row["server_encoding"] != "UTF8" or row["timezone"] != "UTC":
        raise RuntimeError("La codificación o zona horaria del clúster local es inválida.")
    return row


def _role_exists(connection: Connection[dict[str, Any]], role: str) -> bool:
    return (
        connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        is not None
    )


def _ensure_role(
    connection: Connection[dict[str, Any]],
    *,
    role: str,
    password: str,
    createdb: bool,
) -> None:
    identifier = sql.Identifier(role)
    if not _role_exists(connection, role):
        connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(identifier))
    createdb_clause = sql.SQL("CREATEDB") if createdb else sql.SQL("NOCREATEDB")
    connection.execute(
        sql.SQL(
            "ALTER ROLE {} WITH LOGIN NOSUPERUSER {} NOCREATEROLE NOINHERIT "
            "NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(identifier, createdb_clause, sql.Literal(password))
    )
    connection.execute(sql.SQL("ALTER ROLE {} SET timezone TO 'UTC'").format(identifier))


def _database_exists(connection: Connection[dict[str, Any]], database: str) -> bool:
    return (
        connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone()
        is not None
    )


def _ensure_application_database(
    connection: Connection[dict[str, Any]], settings: BootstrapSettings
) -> None:
    database = sql.Identifier(settings.db_name)
    migrator = sql.Identifier(settings.migration_db_user)
    application = sql.Identifier(settings.db_user)
    if not _database_exists(connection, settings.db_name):
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                database, migrator
            )
        )
    else:
        connection.execute(sql.SQL("ALTER DATABASE {} OWNER TO {}").format(database, migrator))
    connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(database))
    connection.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
            database,
            migrator,
            application,
        )
    )
    connection.execute(sql.SQL("ALTER DATABASE {} SET timezone TO 'UTC'").format(database))


def _grant_runtime_data_access(
    connection: Connection[dict[str, Any]], settings: BootstrapSettings
) -> None:
    application = sql.Identifier(settings.db_user)
    migrator = sql.Identifier(settings.migration_db_user)
    connection.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(migrator))
    connection.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    connection.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(application))
    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(application))

    tables = connection.execute(
        """
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public' AND tablename <> 'django_migrations'
        ORDER BY tablename
        """
    ).fetchall()
    for table in tables:
        table_identifier = sql.Identifier(table["tablename"])
        connection.execute(
            sql.SQL("REVOKE ALL ON TABLE {}.{} FROM {}").format(
                sql.Identifier("public"),
                table_identifier,
                application,
            )
        )
        privileges = (
            sql.SQL("SELECT, INSERT, UPDATE")
            if table["tablename"] in NO_DELETE_TABLES
            else sql.SQL("SELECT, INSERT, UPDATE, DELETE")
        )
        connection.execute(
            sql.SQL("GRANT {} ON TABLE {}.{} TO {}").format(
                privileges,
                sql.Identifier("public"),
                table_identifier,
                application,
            )
        )

    sequences = connection.execute(
        """
        SELECT sequencename
        FROM pg_sequences
        WHERE schemaname = 'public'
        ORDER BY sequencename
        """
    ).fetchall()
    for sequence in sequences:
        connection.execute(
            sql.SQL("GRANT USAGE, SELECT, UPDATE ON SEQUENCE {}.{} TO {}").format(
                sql.Identifier("public"),
                sql.Identifier(sequence["sequencename"]),
                application,
            )
        )


def _verify_role_contract(admin: Connection[dict[str, Any]], settings: BootstrapSettings) -> None:
    rows = admin.execute(
        """
        SELECT
            rolname,
            rolsuper,
            rolcreatedb,
            rolcreaterole,
            rolreplication,
            rolbypassrls
        FROM pg_roles
        WHERE rolname = ANY(%s)
        """,
        (list(ROLE_SPECIFICATIONS),),
    ).fetchall()
    by_name = {row["rolname"]: row for row in rows}
    if set(by_name) != set(ROLE_SPECIFICATIONS):
        raise RuntimeError("No se crearon todos los roles locales esperados.")
    for role, expected in ROLE_SPECIFICATIONS.items():
        actual = by_name[role]
        if actual["rolsuper"] != expected["rolsuper"]:
            raise RuntimeError("Un rol local tiene privilegios de superusuario inválidos.")
        if actual["rolcreatedb"] != expected["rolcreatedb"]:
            raise RuntimeError("Un rol local tiene un privilegio CREATEDB inválido.")
        if actual["rolcreaterole"] or actual["rolreplication"] or actual["rolbypassrls"]:
            raise RuntimeError("Un rol local conserva privilegios administrativos prohibidos.")

    with _connect(
        settings,
        database=settings.db_name,
        user=settings.postgres_admin_user,
        password=settings.postgres_admin_password.get_secret_value(),
    ) as application_database:
        privilege_row = application_database.execute(
            """
            SELECT
                has_schema_privilege(%s, 'public', 'USAGE') AS app_usage,
                has_schema_privilege(%s, 'public', 'CREATE') AS app_create,
                has_schema_privilege(%s, 'public', 'CREATE') AS migrator_create
            """,
            (settings.db_user, settings.db_user, settings.migration_db_user),
        ).fetchone()
        if privilege_row is None:
            raise RuntimeError("No se pudieron comprobar los privilegios del esquema local.")
        if not privilege_row["app_usage"] or privilege_row["app_create"]:
            raise RuntimeError("Los privilegios de esquema de la aplicación son inválidos.")
        if not privilege_row["migrator_create"]:
            raise RuntimeError("El migrador no puede crear objetos en el esquema local.")


def prepare_local_database(settings: BootstrapSettings, *, quiet: bool = False) -> None:
    """Crear o reconciliar roles, base local y privilegios de forma idempotente."""
    with _admin_connection(settings) as admin:
        _verify_expected_server(admin)
        _ensure_role(
            admin,
            role=settings.migration_db_user,
            password=settings.migration_db_password.get_secret_value(),
            createdb=False,
        )
        _ensure_role(
            admin,
            role=settings.db_user,
            password=settings.db_password.get_secret_value(),
            createdb=False,
        )
        _ensure_role(
            admin,
            role=settings.test_db_user,
            password=settings.test_db_password.get_secret_value(),
            createdb=True,
        )
        _ensure_application_database(admin, settings)

    with _connect(
        settings,
        database=settings.db_name,
        user=settings.postgres_admin_user,
        password=settings.postgres_admin_password.get_secret_value(),
    ) as application_database:
        _grant_runtime_data_access(application_database, settings)

    with _admin_connection(settings) as admin:
        _verify_role_contract(admin, settings)

    if not quiet:
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "database": settings.db_name,
                    "roles": sorted(ROLE_SPECIFICATIONS),
                },
                separators=(",", ":"),
            )
        )


def check_application_connection(settings: BootstrapSettings) -> None:
    """Comprobar versión, conexión y sesión usando exclusivamente claridez_app."""
    with _connect(
        settings,
        database=settings.db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
    ) as connection:
        server = _verify_expected_server(connection)
        row = connection.execute(
            """
            SELECT
                current_user AS database_user,
                current_database() AS database_name,
                current_setting('TimeZone') AS timezone,
                current_setting('server_encoding') AS server_encoding
            """
        ).fetchone()
    if row is None or row["database_user"] != settings.db_user:
        raise RuntimeError("La conexión normal no utiliza el rol de aplicación esperado.")
    print(
        json.dumps(
            {
                "status": "ok",
                "postgresql": str(server["server_version_num"]),
                "database": row["database_name"],
                "user": row["database_user"],
                "timezone": row["timezone"],
                "encoding": row["server_encoding"],
            },
            separators=(",", ":"),
        )
    )


def _has_remote_environment_indicators() -> bool:
    forbidden_fragments = ("STAGING", "PRODUCTION", "PROD_")
    return any(
        name.startswith("CLARIDEZ_")
        and any(fragment in name.upper() for fragment in forbidden_fragments)
        for name in os.environ
    )


def reset_local_databases(settings: BootstrapSettings, *, confirmed: bool) -> None:
    """Eliminar solo las dos bases locales autorizadas y reconstruir la principal."""
    if not confirmed:
        raise RuntimeError("Falta la confirmación explícita --confirm-local-data-loss.")
    if settings.environment != "local":
        raise RuntimeError("El reset solo está permitido en el entorno local.")
    if settings.db_name != "claridez_local" or settings.test_db_name != "claridez_test":
        raise RuntimeError("Los nombres de las bases no coinciden con el contrato local.")
    if _has_remote_environment_indicators():
        raise RuntimeError("Se detectaron indicios de un ambiente remoto.")

    with _admin_connection(settings) as admin:
        _verify_expected_server(admin)
        for database_name in (settings.test_db_name, settings.db_name):
            admin.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )

    prepare_local_database(settings, quiet=True)
    print(
        json.dumps(
            {
                "status": "reset",
                "recreated": [settings.db_name],
                "reserved_for_tests": settings.test_db_name,
            },
            separators=(",", ":"),
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="preparar roles, base y privilegios locales")
    subparsers.add_parser("check", help="comprobar la conexión normal y PostgreSQL")
    reset_parser = subparsers.add_parser("reset", help="restablecer solo datos locales")
    reset_parser.add_argument("--confirm-local-data-loss", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        settings = load_bootstrap_settings()
        if arguments.command == "prepare":
            prepare_local_database(settings)
        elif arguments.command == "check":
            check_application_connection(settings)
        elif arguments.command == "reset":
            reset_local_databases(
                settings,
                confirmed=bool(arguments.confirm_local_data_loss),
            )
    except ImproperlyConfigured as error:
        print(str(error), file=sys.stderr)
        return 2
    except (psycopg.Error, RuntimeError):
        print("No fue posible completar la operación local solicitada.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
