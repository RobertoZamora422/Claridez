"""Aislamiento PostgreSQL real de OrganizationSettings."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction

from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.models import Membership, Organization, OrganizationSettings
from claridez.organizations.services import create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
PASSWORD = "correct-horse-battery-staple-rls-42"


def _active_user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
    )


def _organization(prefix: str) -> tuple[User, Organization]:
    owner = _active_user(f"{prefix}-owner@example.com")
    organization = create_organization(
        owner_user_id=owner.pk,
        name=f"Organization {prefix}",
    ).organization
    return owner, organization


def _bare_organization(owner: User, prefix: str) -> Organization:
    organization = Organization.objects.create(
        name=f"Bare {prefix}",
        slug=f"bare-{prefix}-{uuid4().hex[:8]}",
        status=Organization.Status.ACTIVE,
    )
    Membership.objects.create(
        organization=organization,
        user=owner,
        role=Membership.Role.OWNER,
        status=Membership.Status.ACTIVE,
    )
    return organization


def _current_guc() -> str | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('claridez.organization_id', true)")
        value = cursor.fetchone()[0]
    return value if isinstance(value, str) else None


def test_rls_is_fail_closed_for_orm_sql_relations_and_reused_connection() -> None:
    first_owner, first = _organization("rls-first")
    _, second = _organization("rls-second")

    assert OrganizationSettings.objects.count() == 0
    with connection.cursor() as cursor:
        cursor.execute("SELECT organization_id FROM organizations_organizationsettings")
        assert cursor.fetchall() == []

    with authorized_tenant_scope(
        first_owner,
        first.pk,
        Capability.ORGANIZATION_SETTINGS_READ,
    ):
        assert list(OrganizationSettings.objects.values_list("organization_id", flat=True)) == [
            first.pk
        ]
        assert Organization.objects.get(pk=first.pk).settings.organization_id == first.pk
        with pytest.raises(OrganizationSettings.DoesNotExist):
            _ = Organization.objects.get(pk=second.pk).settings
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT organization_id
                FROM organizations_organizationsettings
                ORDER BY organization_id
                """
            )
            assert cursor.fetchall() == [(first.pk,)]

    assert _current_guc() in (None, "")
    assert OrganizationSettings.objects.count() == 0


def test_using_and_with_check_cover_direct_sql_bulk_create_and_bulk_update() -> None:
    owner, first = _organization("bulk-first")
    _, second = _organization("bulk-second")
    allowed_target = _bare_organization(owner, "allowed")
    forbidden_target = _bare_organization(_active_user("bulk-foreign@example.com"), "foreign")

    with authorized_tenant_scope(
        owner,
        allowed_target.pk,
        Capability.ORGANIZATION_SETTINGS_UPDATE,
    ):
        OrganizationSettings.objects.bulk_create(
            [OrganizationSettings(organization=allowed_target)]
        )
        assert OrganizationSettings.objects.filter(organization=allowed_target).exists()

    with authorized_tenant_scope(
        owner,
        first.pk,
        Capability.ORGANIZATION_SETTINGS_UPDATE,
    ):
        first_settings = OrganizationSettings.objects.get(organization=first)
        first_settings.currency = "EUR"
        assert OrganizationSettings.objects.bulk_update([first_settings], ["currency"]) == 1

        cross_settings = OrganizationSettings(
            organization=second,
            currency="GBP",
            timezone="Europe/London",
        )
        assert OrganizationSettings.objects.bulk_update([cross_settings], ["currency"]) == 0

        with pytest.raises(DatabaseError), transaction.atomic():
            OrganizationSettings.objects.bulk_create(
                [OrganizationSettings(organization=forbidden_target)]
            )
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE organizations_organizationsettings
                SET organization_id = %s
                WHERE organization_id = %s
                """,
                (forbidden_target.pk, first.pk),
            )

    with authorized_tenant_scope(
        owner,
        first.pk,
        Capability.ORGANIZATION_SETTINGS_READ,
    ):
        assert OrganizationSettings.objects.get(organization=first).currency == "EUR"


def test_scope_commit_rollback_exception_and_lazy_evaluation_are_safe() -> None:
    owner, organization = _organization("transactions")

    with authorized_tenant_scope(
        owner,
        organization.pk,
        Capability.ORGANIZATION_SETTINGS_UPDATE,
    ):
        OrganizationSettings.objects.filter(organization=organization).update(currency="CAD")

    with (
        pytest.raises(RuntimeError, match="forced rollback"),
        authorized_tenant_scope(
            owner,
            organization.pk,
            Capability.ORGANIZATION_SETTINGS_UPDATE,
        ),
    ):
        OrganizationSettings.objects.filter(organization=organization).update(currency="JPY")
        raise RuntimeError("forced rollback")

    with authorized_tenant_scope(
        owner,
        organization.pk,
        Capability.ORGANIZATION_SETTINGS_READ,
    ):
        assert OrganizationSettings.objects.get().currency == "CAD"
        deferred = OrganizationSettings.objects.all()

    assert _current_guc() in (None, "")
    assert list(deferred) == []


def test_database_constraints_and_rls_metadata_are_exact() -> None:
    owner, organization = _organization("metadata")
    table = OrganizationSettings._meta.db_table

    with authorized_tenant_scope(
        owner,
        organization.pk,
        Capability.ORGANIZATION_SETTINGS_UPDATE,
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            OrganizationSettings.objects.filter(organization=organization).update(currency="usd")
        with pytest.raises(IntegrityError), transaction.atomic():
            OrganizationSettings.objects.filter(organization=organization).update(
                timezone=" America/Guayaquil "
            )
        with pytest.raises(DatabaseError), transaction.atomic():
            OrganizationSettings.objects.filter(organization=organization).update(
                timezone="Not/A-Timezone"
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            OrganizationSettings.objects.filter(organization=organization).update(timezone="PST")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                pg_get_userbyid(table_class.relowner),
                table_class.relrowsecurity,
                table_class.relforcerowsecurity
            FROM pg_class AS table_class
            WHERE table_class.oid = %s::regclass
            """,
            (table,),
        )
        owner_name, rls_enabled, rls_forced = cursor.fetchone()
        cursor.execute(
            """
            SELECT policyname, roles, cmd, qual, with_check
            FROM pg_policies
            WHERE schemaname = 'public' AND tablename = %s
            """,
            (table,),
        )
        policy = cursor.fetchone()
        cursor.execute(
            """
            SELECT
                has_table_privilege('claridez_app', %s, 'SELECT'),
                has_table_privilege('claridez_app', %s, 'INSERT'),
                has_table_privilege('claridez_app', %s, 'UPDATE'),
                has_table_privilege('claridez_app', %s, 'DELETE'),
                has_function_privilege(
                    'claridez_app',
                    'public.claridez_current_organization_id()',
                    'EXECUTE'
                ),
                has_function_privilege(
                    'claridez_app',
                    'public.claridez_is_iana_timezone(text)',
                    'EXECUTE'
                ),
                (
                    SELECT NOT EXISTS (
                        SELECT 1
                        FROM aclexplode(function_class.proacl) AS acl
                        WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                    )
                    FROM pg_proc AS function_class
                    WHERE function_class.oid =
                        'public.claridez_current_organization_id()'::regprocedure
                )
                AND (
                    SELECT NOT EXISTS (
                        SELECT 1
                        FROM aclexplode(function_class.proacl) AS acl
                        WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                    )
                    FROM pg_proc AS function_class
                    WHERE function_class.oid =
                        'public.claridez_is_iana_timezone(text)'::regprocedure
                )
            """,
            (table, table, table, table),
        )
        privileges = cursor.fetchone()

    assert owner_name == "claridez_test_runner"
    assert rls_enabled is True
    assert rls_forced is True
    assert policy is not None
    assert policy[0] == "organizations_settings_tenant_policy"
    assert set(policy[1]) == {"claridez_app", "claridez_migrator", "claridez_test_runner"}
    assert policy[2] == "ALL"
    assert "claridez_current_organization_id" in policy[3]
    assert "claridez_current_organization_id" in policy[4]
    assert privileges == (True, True, True, False, True, True, True)
