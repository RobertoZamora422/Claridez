"""Pruebas PostgreSQL del esquema y privilegios organizacionales."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from psycopg import Connection
from psycopg.rows import dict_row

from claridez.identity.models import User
from claridez.organizations.models import Membership, Organization
from claridez.organizations.services import add_membership, create_organization
from claridez.settings.environment import BootstrapSettings, load_bootstrap_settings

pytestmark = [pytest.mark.integration, pytest.mark.django_db]
PASSWORD = "correct-horse-battery-staple-42"


def _active_user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )


def _runtime_connection(settings: BootstrapSettings) -> Connection[dict[str, Any]]:
    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        connect_timeout=settings.db_connect_timeout,
        options="-c timezone=UTC",
        autocommit=True,
        row_factory=dict_row,
    )


def test_organization_constraints_indexes_and_global_table_contract() -> None:
    assert connection.vendor == "postgresql"
    expected_constraints = {
        Organization._meta.db_table: {
            "organizations_organization_name_canonical",
            "organizations_organization_slug_canonical",
            "organizations_organization_slug_unique",
            "organizations_organization_status_valid",
        },
        Membership._meta.db_table: {
            "organizations_membership_org_user_unique",
            "organizations_membership_role_valid",
            "organizations_membership_status_valid",
            "organizations_membership_status_dates_consistent",
            "organizations_membership_suspended_after_joined",
            "organizations_membership_revoked_after_joined",
        },
    }

    with connection.cursor() as cursor:
        for table, expected in expected_constraints.items():
            constraints = connection.introspection.get_constraints(cursor, table)
            assert expected <= set(constraints)
        cursor.execute(
            """
            SELECT
                table_class.relname,
                pg_get_userbyid(table_class.relowner),
                table_class.relrowsecurity,
                table_class.relforcerowsecurity
            FROM pg_class AS table_class
            JOIN pg_namespace AS namespace ON namespace.oid = table_class.relnamespace
            WHERE namespace.nspname = 'public'
              AND table_class.relname = ANY(%s)
            ORDER BY table_class.relname
            """,
            ([Organization._meta.db_table, Membership._meta.db_table],),
        )
        table_contract = cursor.fetchall()
        cursor.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = %s
            """,
            (Membership._meta.db_table,),
        )
        indexes = dict(cursor.fetchall())

    assert table_contract == [
        (Membership._meta.db_table, "claridez_test_runner", False, False),
        (Organization._meta.db_table, "claridez_test_runner", False, False),
    ]
    assert "organizations_active_owner_idx" in indexes
    assert "WHERE" in indexes["organizations_active_owner_idx"]
    assert "organizations_organizationsettings" not in connection.introspection.table_names()


@pytest.mark.django_db(transaction=True)
def test_postgresql_rejects_invalid_organization_and_membership_rows() -> None:
    owner = _active_user("constraints-owner@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Constraints")
    member_user = _active_user("constraints-member@example.com")
    membership = add_membership(
        organization_id=creation.organization.pk,
        user_id=member_user.pk,
        role=Membership.Role.COMMERCIAL,
    )

    invalid_organization_updates: list[dict[str, object]] = [
        {"name": " Con espacios "},
        {"slug": "NOT-CANONICAL"},
        {"slug": "double--hyphen"},
        {"status": "arbitrary"},
    ]
    for organization_update in invalid_organization_updates:
        with pytest.raises(IntegrityError), transaction.atomic():
            Organization.objects.filter(pk=creation.organization.pk).update(**organization_update)

    invalid_membership_updates: list[dict[str, object]] = [
        {"role": "arbitrary"},
        {"status": "arbitrary"},
        {"status": Membership.Status.ACTIVE, "suspended_at": timezone.now()},
        {"status": Membership.Status.SUSPENDED, "suspended_at": None},
        {"status": Membership.Status.REVOKED, "revoked_at": None},
        {
            "status": Membership.Status.SUSPENDED,
            "suspended_at": membership.joined_at - timedelta(seconds=1),
        },
        {
            "status": Membership.Status.REVOKED,
            "revoked_at": membership.joined_at - timedelta(seconds=1),
        },
    ]
    for membership_update in invalid_membership_updates:
        with pytest.raises(IntegrityError), transaction.atomic():
            Membership.objects.filter(pk=membership.pk).update(**membership_update)


@pytest.mark.django_db(transaction=True)
def test_postgresql_rejects_duplicates_and_protects_foreign_keys() -> None:
    owner = _active_user("foreign-owner@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Foreign keys")

    with pytest.raises(IntegrityError), transaction.atomic():
        Organization.objects.create(
            name="Otra",
            slug=creation.organization.slug,
            status=Organization.Status.ACTIVE,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(
            organization=creation.organization,
            user=owner,
            role=Membership.Role.FINANCE,
            status=Membership.Status.ACTIVE,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.filter(pk=creation.owner_membership.pk).update(user_id=uuid.uuid4())

    with pytest.raises(ProtectedError):
        owner.delete()
    with pytest.raises(ProtectedError):
        creation.organization.delete()


def test_application_role_has_dml_without_delete_or_ddl() -> None:
    settings = load_bootstrap_settings()
    with _runtime_connection(settings) as application:
        privileges = application.execute(
            """
            SELECT
                current_user,
                pg_get_userbyid(table_class.relowner) AS owner,
                has_table_privilege(current_user, %s, 'SELECT') AS can_select,
                has_table_privilege(current_user, %s, 'INSERT') AS can_insert,
                has_table_privilege(current_user, %s, 'UPDATE') AS can_update,
                has_table_privilege(current_user, %s, 'DELETE') AS can_delete
            FROM pg_class AS table_class
            WHERE table_class.oid = %s::regclass
            """,
            (
                Organization._meta.db_table,
                Organization._meta.db_table,
                Organization._meta.db_table,
                Organization._meta.db_table,
                Organization._meta.db_table,
            ),
        ).fetchone()
        assert privileges is not None
        assert privileges == {
            "current_user": "claridez_app",
            "owner": "claridez_migrator",
            "can_select": True,
            "can_insert": True,
            "can_update": True,
            "can_delete": False,
        }

        for table in (Organization._meta.db_table, Membership._meta.db_table):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                application.execute(f'DELETE FROM "{table}" WHERE false')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            application.execute(
                f'ALTER TABLE "{Organization._meta.db_table}" ADD COLUMN forbidden integer'
            )
