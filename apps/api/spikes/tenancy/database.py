"""Ciclo de vida protegido de la base desechable del spike."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg import Connection, sql
from psycopg.rows import dict_row

API_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = API_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from claridez.settings.environment import BootstrapSettings, load_bootstrap_settings  # noqa: E402
from spikes.tenancy import SPIKE_DATABASE_NAME  # noqa: E402

EXPECTED_CLUSTER_NAME = "claridez-local"
EXPECTED_POSTGRESQL_MAJOR = 17
CLARIDEZ_ROLES = ("claridez_migrator", "claridez_app", "claridez_test_runner")
SPIKE_TABLES = (
    "claridez_spike_organization",
    "claridez_spike_app_record",
    "claridez_spike_app_child",
    "claridez_spike_rls_record",
    "claridez_spike_rls_child",
    "claridez_spike_rls_default_deny",
)


def _password_for(settings: BootstrapSettings, role: str) -> str:
    passwords = {
        settings.postgres_admin_user: settings.postgres_admin_password,
        settings.migration_db_user: settings.migration_db_password,
        settings.db_user: settings.db_password,
        settings.test_db_user: settings.test_db_password,
    }
    try:
        return passwords[role].get_secret_value()
    except KeyError as error:
        raise RuntimeError("Se solicitó un rol fuera del contrato local.") from error


def connect(
    settings: BootstrapSettings,
    *,
    database: str,
    role: str,
    autocommit: bool = True,
) -> Connection[dict[str, Any]]:
    """Abrir una conexión local sin registrar credenciales."""
    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=database,
        user=role,
        password=_password_for(settings, role),
        connect_timeout=settings.db_connect_timeout,
        options=(f"-c timezone=UTC -c statement_timeout={settings.db_statement_timeout_ms}"),
        autocommit=autocommit,
        row_factory=dict_row,
    )


def _verify_local_server(connection: Connection[dict[str, Any]]) -> dict[str, Any]:
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
        raise RuntimeError("PostgreSQL no devolvió metadatos del servidor.")
    if row["server_version_num"] // 10_000 != EXPECTED_POSTGRESQL_MAJOR:
        raise RuntimeError("La versión mayor de PostgreSQL no corresponde al spike local.")
    if row["cluster_name"] != EXPECTED_CLUSTER_NAME:
        raise RuntimeError("El clúster no corresponde al PostgreSQL local esperado.")
    if row["server_encoding"] != "UTF8" or row["timezone"] != "UTC":
        raise RuntimeError("La codificación o zona horaria del clúster no es válida.")
    return row


def _database_exists(connection: Connection[dict[str, Any]]) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (SPIKE_DATABASE_NAME,)
        ).fetchone()
        is not None
    )


def database_exists(settings: BootstrapSettings | None = None) -> bool:
    """Comprobar si la base desechable sigue presente."""
    settings = settings or load_bootstrap_settings()
    with connect(
        settings,
        database=settings.postgres_admin_db,
        role=settings.postgres_admin_user,
    ) as admin:
        _verify_local_server(admin)
        return _database_exists(admin)


def database_names(settings: BootstrapSettings | None = None) -> set[str]:
    """Obtener nombres locales para detectar bases creadas fuera del ciclo autorizado."""
    settings = settings or load_bootstrap_settings()
    with connect(
        settings,
        database=settings.postgres_admin_db,
        role=settings.postgres_admin_user,
    ) as admin:
        _verify_local_server(admin)
        rows = admin.execute("SELECT datname FROM pg_database").fetchall()
    return {str(row["datname"]) for row in rows}


def _drop_database(admin: Connection[dict[str, Any]]) -> None:
    admin.execute(
        """
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = %s AND pid <> pg_backend_pid()
        """,
        (SPIKE_DATABASE_NAME,),
    )
    admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(SPIKE_DATABASE_NAME)))


def prepare_database(
    settings: BootstrapSettings | None = None, *, replace_existing: bool = False
) -> None:
    """Crear la base exacta, con el migrador como propietario."""
    settings = settings or load_bootstrap_settings()
    with connect(
        settings,
        database=settings.postgres_admin_db,
        role=settings.postgres_admin_user,
    ) as admin:
        _verify_local_server(admin)
        if _database_exists(admin):
            if not replace_existing:
                raise RuntimeError("La base desechable ya existe; no se asumirá su propiedad.")
            _drop_database(admin)
        admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(SPIKE_DATABASE_NAME),
                sql.Identifier(settings.migration_db_user),
            )
        )
        admin.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                sql.Identifier(SPIKE_DATABASE_NAME)
            )
        )
        admin.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}, {}").format(
                sql.Identifier(SPIKE_DATABASE_NAME),
                sql.Identifier(settings.migration_db_user),
                sql.Identifier(settings.db_user),
                sql.Identifier(settings.test_db_user),
            )
        )
        admin.execute(
            sql.SQL("ALTER DATABASE {} SET timezone TO 'UTC'").format(
                sql.Identifier(SPIKE_DATABASE_NAME)
            )
        )


def grant_runtime_privileges(settings: BootstrapSettings | None = None) -> None:
    """Conceder solo los privilegios necesarios después de migrar."""
    settings = settings or load_bootstrap_settings()
    with connect(
        settings,
        database=SPIKE_DATABASE_NAME,
        role=settings.migration_db_user,
    ) as migrator:
        _verify_local_server(migrator)
        app = sql.Identifier(settings.db_user)
        test_runner = sql.Identifier(settings.test_db_user)
        migrator.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        migrator.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}, {}").format(app, test_runner))
        migrator.execute(
            sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}, {}").format(app, test_runner)
        )
        for table_name in SPIKE_TABLES:
            table = sql.Identifier(table_name)
            migrator.execute(
                sql.SQL("REVOKE ALL ON TABLE {} FROM PUBLIC, {}, {}").format(
                    table, app, test_runner
                )
            )

        migrator.execute(
            sql.SQL("GRANT SELECT ON TABLE {} TO {}, {}").format(
                sql.Identifier("claridez_spike_organization"), app, test_runner
            )
        )
        for table_name in ("claridez_spike_app_record", "claridez_spike_app_child"):
            table = sql.Identifier(table_name)
            migrator.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}").format(
                    table, test_runner
                )
            )
            migrator.execute(sql.SQL("GRANT SELECT, DELETE ON TABLE {} TO {}").format(table, app))

        migrator.execute(
            sql.SQL(
                "GRANT INSERT (id, organization_id, external_key, payload) ON TABLE {} TO {}"
            ).format(sql.Identifier("claridez_spike_app_record"), app)
        )
        migrator.execute(
            sql.SQL("GRANT UPDATE (external_key, payload) ON TABLE {} TO {}").format(
                sql.Identifier("claridez_spike_app_record"), app
            )
        )
        migrator.execute(
            sql.SQL(
                "GRANT INSERT (id, organization_id, external_key, payload, parent_id) "
                "ON TABLE {} TO {}"
            ).format(sql.Identifier("claridez_spike_app_child"), app)
        )
        migrator.execute(
            sql.SQL("GRANT UPDATE (external_key, payload, parent_id) ON TABLE {} TO {}").format(
                sql.Identifier("claridez_spike_app_child"), app
            )
        )

        for table_name in (
            "claridez_spike_rls_record",
            "claridez_spike_rls_child",
            "claridez_spike_rls_default_deny",
        ):
            table = sql.Identifier(table_name)
            migrator.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}, {}").format(
                    table, app, test_runner
                )
            )


def collect_catalog_evidence(settings: BootstrapSettings | None = None) -> dict[str, Any]:
    """Recoger propietarios, roles, políticas, restricciones y privilegios no sensibles."""
    settings = settings or load_bootstrap_settings()
    with connect(
        settings,
        database=SPIKE_DATABASE_NAME,
        role=settings.postgres_admin_user,
    ) as connection:
        server = _verify_local_server(connection)
        owners = connection.execute(
            """
            SELECT c.relname AS table_name, r.rolname AS owner,
                   c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS rls_forced
            FROM pg_class c
            JOIN pg_roles r ON r.oid = c.relowner
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND (c.relname LIKE 'claridez_spike_%' OR c.relname = 'django_migrations')
            ORDER BY c.relname
            """
        ).fetchall()
        roles = connection.execute(
            """
            SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
            FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname
            """,
            (list(CLARIDEZ_ROLES),),
        ).fetchall()
        policies = connection.execute(
            """
            SELECT tablename, policyname, cmd, roles, qual, with_check
            FROM pg_policies WHERE schemaname = 'public'
              AND tablename LIKE 'claridez_spike_%'
            ORDER BY tablename, policyname
            """
        ).fetchall()
        constraints = connection.execute(
            """
            SELECT conname, conrelid::regclass::text AS table_name, contype
            FROM pg_constraint
            WHERE connamespace = 'public'::regnamespace
              AND conrelid::regclass::text LIKE 'claridez_spike_%'
            ORDER BY table_name, conname
            """
        ).fetchall()
        privileges = connection.execute(
            """
            SELECT grantee, table_name, privilege_type,
                   COALESCE(column_name, '*') AS column_name
            FROM information_schema.role_table_grants
            FULL JOIN information_schema.role_column_grants
              USING (grantor, grantee, table_catalog, table_schema, table_name, privilege_type)
            WHERE table_schema = 'public'
              AND table_name LIKE 'claridez_spike_%%'
              AND grantee = ANY(%s)
            ORDER BY grantee, table_name, privilege_type, column_name
            """,
            (list(CLARIDEZ_ROLES),),
        ).fetchall()
    return {
        "postgresql_version_num": server["server_version_num"],
        "backend_pid_observed": None,
        "owners": owners,
        "roles": roles,
        "policies": policies,
        "constraints": constraints,
        "privileges": privileges,
    }


def verify_preconditions(settings: BootstrapSettings | None = None) -> dict[str, Any]:
    """Comprobar las invariantes que deben existir antes de las pruebas."""
    settings = settings or load_bootstrap_settings()
    evidence = collect_catalog_evidence(settings)
    owners = evidence["owners"]
    if not owners or any(row["owner"] != settings.migration_db_user for row in owners):
        raise RuntimeError("El migrador no es propietario de todas las tablas técnicas.")
    roles = {row["rolname"]: row for row in evidence["roles"]}
    if set(roles) != set(CLARIDEZ_ROLES):
        raise RuntimeError("Faltan roles locales requeridos para el spike.")
    if any(
        role["rolsuper"] or role["rolcreaterole"] or role["rolbypassrls"] for role in roles.values()
    ):
        raise RuntimeError("Un rol de Claridez conserva privilegios administrativos prohibidos.")
    return evidence


def cleanup_database(settings: BootstrapSettings | None = None, *, confirmed: bool = False) -> None:
    """Eliminar exclusivamente la base del spike después de confirmación explícita."""
    if not confirmed:
        raise RuntimeError("Falta --confirm-spike-data-loss para eliminar la base desechable.")
    settings = settings or load_bootstrap_settings()
    if settings.environment != "local":
        raise RuntimeError("La limpieza del spike solo se permite en el entorno local.")
    with connect(
        settings,
        database=settings.postgres_admin_db,
        role=settings.postgres_admin_user,
    ) as admin:
        _verify_local_server(admin)
        _drop_database(admin)


def _print_status(status: Literal["prepared", "granted", "checked", "removed"]) -> None:
    print(json.dumps({"database": SPIKE_DATABASE_NAME, "status": status}, separators=(",", ":")))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--replace-existing", action="store_true")
    subparsers.add_parser("grant")
    subparsers.add_parser("check")
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--confirm-spike-data-loss", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "prepare":
            prepare_database(replace_existing=bool(arguments.replace_existing))
            _print_status("prepared")
        elif arguments.command == "grant":
            grant_runtime_privileges()
            _print_status("granted")
        elif arguments.command == "check":
            verify_preconditions()
            _print_status("checked")
        elif arguments.command == "cleanup":
            cleanup_database(confirmed=bool(arguments.confirm_spike_data_loss))
            _print_status("removed")
    except (psycopg.Error, RuntimeError):
        print("No fue posible completar la operación protegida del spike.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
