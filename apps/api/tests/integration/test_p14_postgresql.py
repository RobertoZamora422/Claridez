"""Migración aditiva, RLS, privilegios e integridad PostgreSQL de P14."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from claridez.communications.models import (
    Channel,
    CommunicationIntent,
    CommunicationOutbox,
    CommunicationPreferenceEvent,
    CommunicationTemplate,
    CommunicationTemplateVersion,
    Purpose,
)
from claridez.organizations.capabilities import Capability
from claridez.organizations.services import create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.people.models import ConsentEvent, Person
from claridez.people.services import create_person
from claridez.portal.models import PortalGrant, PublicForm, PublicFormSubmission
from claridez.portal.services import submit_public_form
from claridez.settings.environment import load_bootstrap_settings
from tests.test_p14 import _published_form, _submission, _user

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

COMMUNICATIONS_PRIVATE = (
    "communications_communicationauditevent",
    "communications_communicationintent",
    "communications_communicationoutbox",
    "communications_communicationtemplate",
    "communications_communicationtemplateversion",
    "communications_logicalmessage",
    "communications_deliveryattempt",
    "communications_providerevent",
    "communications_senderidentity",
    "communications_communicationpolicy",
    "communications_communicationpreferenceevent",
)
PORTAL_PRIVATE = (
    "portal_portalauditevent",
    "portal_portalprincipal",
    "portal_portalgrant",
    "portal_portalchallenge",
    "portal_portalsession",
    "portal_publicform",
    "portal_publicformversion",
    "portal_publicformsubmission",
)
PORTAL_GLOBAL_TECHNICAL = (
    "portal_portallocator",
    "portal_portalratelimitbucket",
    "portal_antiabusetokenuse",
)
APPEND_ONLY = (
    "communications_communicationauditevent",
    "communications_communicationpreferenceevent",
    "portal_portalauditevent",
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


def _restore_head() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_p14_private_tables_force_rls_and_keep_minimum_runtime_privileges() -> None:
    private = (*COMMUNICATIONS_PRIVATE, *PORTAL_PRIVATE)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(%s) ORDER BY relname",
            [list(private)],
        )
        assert cursor.fetchall() == sorted((table, True, True) for table in private)
        cursor.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'claridez_app'")
        assert cursor.fetchone() == (False,)
        for table in private:
            cursor.execute(
                "SELECT has_table_privilege('claridez_app', %s, 'SELECT'), "
                "has_table_privilege('claridez_app', %s, 'INSERT'), "
                "has_table_privilege('claridez_app', %s, 'UPDATE'), "
                "has_table_privilege('claridez_app', %s, 'DELETE'), "
                "has_table_privilege('claridez_app', %s, 'TRUNCATE')",
                [table] * 5,
            )
            select, insert, update, delete, truncate = cursor.fetchone()
            assert (select, insert, delete, truncate) == (True, True, False, False)
            assert update is (table not in APPEND_ONLY)

        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'portal_portallocator' "
            "ORDER BY column_name"
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "created_at",
            "expires_at",
            "id",
            "kind",
            "organization_id",
            "revoked_at",
            "target_reference",
            "token_hmac",
        }
        for table in PORTAL_GLOBAL_TECHNICAL:
            cursor.execute(
                "SELECT has_table_privilege('claridez_app', %s, 'DELETE'), "
                "has_table_privilege('claridez_app', %s, 'TRUNCATE')",
                [table, table],
            )
            assert cursor.fetchone() == (False, False)


def test_p14_rls_is_fail_closed_and_cross_tenant_negative_with_claridez_app() -> None:
    first_owner = _user("p14-rls-first@example.com")
    first = create_organization(owner_user_id=first_owner.pk, name="P14 RLS A")
    second_owner = _user("p14-rls-second@example.com")
    second = create_organization(owner_user_id=second_owner.pk, name="P14 RLS B")
    with authorized_tenant_scope(
        first_owner, first.organization.pk, Capability.COMMUNICATION_TEMPLATE_READ
    ):
        CommunicationTemplate.objects.create(
            organization_id=first.organization.pk,
            name="Solo tenant A",
            channel=Channel.EMAIL,
            purpose=Purpose.PORTAL_AUTHENTICATION,
            created_by_membership_id=first.owner_membership.pk,
        )
        PublicForm.objects.create(
            organization_id=first.organization.pk,
            name="Formulario A",
            created_by_membership_id=first.owner_membership.pk,
        )

    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM communications_communicationtemplate")
        assert cursor.fetchone() == (0,)
        cursor.execute("SELECT count(*) FROM portal_publicform")
        assert cursor.fetchone() == (0,)
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            [str(first.organization.pk)],
        )
        cursor.execute("SELECT count(*) FROM communications_communicationtemplate")
        assert cursor.fetchone() == (1,)
        cursor.execute("SELECT count(*) FROM portal_publicform")
        assert cursor.fetchone() == (1,)
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            [str(second.organization.pk)],
        )
        cursor.execute("SELECT count(*) FROM communications_communicationtemplate")
        assert cursor.fetchone() == (0,)
        cursor.execute("SELECT count(*) FROM portal_publicform")
        assert cursor.fetchone() == (0,)


def test_p14_database_guards_preserve_provenance_and_immutable_history() -> None:
    owner = _user("p14-guards@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="P14 guards")
    person_data = create_person(
        owner,
        creation.organization.pk,
        full_name="Persona interna",
        phone="0991234599",
        email="guard@example.com",
        origin="other",
        origin_detail="Prueba",
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        person = Person.objects.get(pk=person_data["id"])
        with pytest.raises(IntegrityError), transaction.atomic():
            ConsentEvent.objects.create(
                organization_id=creation.organization.pk,
                person=person,
                purpose="service_update",
                channel="email",
                event_type=ConsentEvent.EventType.GRANT,
                decision="granted",
                source="public_form",
                evidence_reference="submission:evidence",
                recorder_kind=ConsentEvent.RecorderKind.EXTERNAL_SUBJECT,
                recorded_by_membership_id=creation.owner_membership.pk,
                external_submission_reference="submission",
                external_evidence_sha256="a" * 64,
                observed_text_sha256="b" * 64,
                occurred_at=timezone.now(),
                presentation_version="v1",
            )

        template = CommunicationTemplate.objects.create(
            organization_id=creation.organization.pk,
            name="Inmutable",
            channel=Channel.EMAIL,
            purpose=Purpose.PORTAL_AUTHENTICATION,
            created_by_membership_id=creation.owner_membership.pk,
        )
        version = CommunicationTemplateVersion.objects.create(
            organization_id=creation.organization.pk,
            template=template,
            version=1,
            status=CommunicationTemplateVersion.Status.PUBLISHED,
            body_template="Código {code}",
            variable_names=["code"],
            content_sha256="a" * 64,
        )
        with pytest.raises(Exception, match="immutable"), transaction.atomic():  # noqa: B017
            CommunicationTemplateVersion.objects.filter(pk=version.pk).update(
                body_template="Reescrito"
            )
        preference = CommunicationPreferenceEvent.objects.create(
            organization_id=creation.organization.pk,
            person_reference=person.pk,
            canonical_set=[str(person.pk)],
            channel=Channel.EMAIL,
            purpose=Purpose.SERVICE_UPDATE,
            action=CommunicationPreferenceEvent.Action.CLIENT_UNSUBSCRIBE,
            portal_principal_reference=uuid4(),
            evidence_sha256="e" * 64,
            occurred_at=timezone.now(),
        )
        with pytest.raises(Exception, match="append-only"), transaction.atomic():  # noqa: B017
            CommunicationPreferenceEvent.objects.filter(pk=preference.pk).update(reason="editado")

    locator, form_version, _ = _published_form(owner, creation)
    capture = submit_public_form(
        locator,
        idempotency_key="database-guard-capture",
        data=_submission(form_version),
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        submission = PublicFormSubmission.objects.get(pk=UUID(str(capture["submission_id"])))
        grant = PortalGrant.objects.get(
            event_request_reference=UUID(str(capture["event_request_id"]))
        )
        intent = CommunicationIntent.objects.create(
            organization_id=creation.organization.pk,
            purpose=Purpose.PORTAL_AUTHENTICATION,
            channel=Channel.EMAIL,
            recipient_person_id=UUID(str(submission.person_reference)),
            template_version=version,
            aggregate_type="portal_challenge",
            aggregate_id=uuid4(),
            variables={"challenge_reference": str(uuid4())},
            payload_sha256="c" * 64,
            idempotency_key="direct-sql-outbox-guard",
            not_before=timezone.now(),
        )
        outbox = CommunicationOutbox.objects.create(
            organization_id=creation.organization.pk,
            intent=intent,
            next_attempt_at=timezone.now(),
        )

    with _app_connection() as app_connection, app_connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            [str(creation.organization.pk)],
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "UPDATE portal_publicformsubmission SET payload_sha256 = %s WHERE id = %s",
                ["d" * 64, submission.pk],
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "UPDATE portal_portalgrant SET scopes = %s::jsonb WHERE id = %s",
                ['["event:read", "documents:accept"]', grant.pk],
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "UPDATE communications_communicationoutbox SET state = 'succeeded' WHERE id = %s",
                [outbox.pk],
            )
        with pytest.raises(psycopg.errors.RaiseException):
            cursor.execute(
                "UPDATE communications_communicationtemplateversion "
                "SET body_template = 'Reescrito' WHERE id = %s",
                [version.pk],
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(
                "UPDATE communications_communicationpreferenceevent "
                "SET reason = 'Reescrito' WHERE id = %s",
                [preference.pk],
            )


def test_public_capture_concurrent_replay_materializes_one_submission() -> None:
    owner = _user("p14-concurrent-capture@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="P14 capture concurrente")
    locator, version, _ = _published_form(owner, creation)
    payload = _submission(version)
    barrier = Barrier(2)

    def submit_once() -> dict[str, object]:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return submit_public_form(locator, idempotency_key="concurrent-once", data=payload)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: submit_once(), range(2)))
    assert results[0] == results[1]
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        assert PublicFormSubmission.objects.count() == 1


def test_p13_final_to_p14_is_additive_and_does_not_fabricate_history() -> None:
    try:
        executor = MigrationExecutor(connection)
        targets = [
            target
            for target in executor.loader.graph.leaf_nodes()
            if target[0] not in {"communications", "portal", "people", "documents", "crm"}
        ]
        targets.extend(
            [
                ("communications", None),
                ("portal", None),
                ("people", "0004_contact_ownership_locking"),
                ("documents", "0010_domain_asset_security"),
                ("crm", "0003_corrective_integrity"),
            ]
        )
        executor.migrate(targets)
        tables = set(connection.introspection.table_names())
        assert not any(table.startswith("communications_") for table in tables)
        assert not any(table.startswith("portal_") for table in tables)

        _restore_head()
        tables = set(connection.introspection.table_names())
        assert set(COMMUNICATIONS_PRIVATE + PORTAL_PRIVATE + PORTAL_GLOBAL_TECHNICAL).issubset(
            tables
        )
        with connection.cursor() as cursor:
            for table in COMMUNICATIONS_PRIVATE + PORTAL_PRIVATE + PORTAL_GLOBAL_TECHNICAL:
                cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608
                assert cursor.fetchone() == (0,)
    finally:
        _restore_head()
