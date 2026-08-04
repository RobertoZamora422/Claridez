from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import (
    DatabaseError,
    IntegrityError,
    close_old_connections,
    connection,
    transaction,
)
from django.db.migrations.executor import MigrationExecutor
from django.db.models import F
from django.utils import timezone

from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.models import EventRequestHistory
from claridez.commercial.services import create_event_request
from claridez.crm.errors import CrmError
from claridez.crm.models import FollowUpTask, FollowUpTaskHistory, Interaction
from claridez.crm.services import create_task, record_interaction, update_task
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.services import create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.people import services as people_services
from claridez.people.errors import PeopleError
from claridez.people.models import ConsentEvent, Person, PersonContactAlias, PersonMerge

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
PASSWORD = "p7-postgresql-validation-password-42!"
P7_PRIVATE_TABLES = (
    "commercial_eventrequesthistory",
    "people_personmerge",
    "people_personcontactalias",
    "people_consentevent",
    "crm_interaction",
    "crm_followuptask",
    "crm_followuptaskhistory",
)


def _owner(slug: str) -> tuple[User, Any]:
    owner = User.objects.create_user(
        email=f"{slug}@example.com",
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    return owner, create_organization(owner_user_id=owner.pk, name=f"Organización {slug}")


def _person(actor: User, organization_id: UUID, *, phone: str, name: str) -> dict[str, Any]:
    return people_services.create_person(
        actor,
        organization_id,
        full_name=name,
        phone=phone,
        email=None,
        origin="website",
        origin_detail="Prueba PostgreSQL P7",
    )


def _request(
    actor: User, organization_id: UUID, person_id: UUID | str, *, days: int
) -> dict[str, Any]:
    event_type = next(
        (row for row in list_event_types(actor, organization_id) if row["name"] == "Boda"),
        None,
    )
    if event_type is None:
        event_type = create_event_type(actor, organization_id, name="Boda")
    starts_at = timezone.now() + timedelta(days=days)
    return create_event_request(
        actor,
        organization_id,
        person_id=person_id,
        event_type_id=event_type["id"],
        space_id=list_venues(actor, organization_id)[0]["spaces"][0]["id"],
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=5),
        estimated_guests=60,
        general_need="Validación PostgreSQL P7",
        notes="",
        origin="website",
        origin_detail="Formulario sintético",
    )


def test_p7_force_rls_sql_bulk_privileges_and_append_only_evidence() -> None:
    first_owner, first = _owner("p7-rls-first")
    second_owner, second = _owner("p7-rls-second")
    first_id = first.organization.pk
    second_id = second.organization.pk
    source = _person(first_owner, first_id, phone="0992000001", name="Origen RLS")
    target = _person(first_owner, first_id, phone="0992000002", name="Destino RLS")
    foreign = _person(second_owner, second_id, phone="0992000003", name="Otro tenant")
    event_request = _request(first_owner, first_id, source["id"], days=40)
    interaction = record_interaction(
        first_owner,
        first_id,
        person_id=source["id"],
        event_request_id=event_request["id"],
        channel="email",
        direction="outbound",
        occurred_at=timezone.now(),
        summary="Resumen mínimo sin cuerpo de conversación.",
    )
    task = create_task(
        first_owner,
        first_id,
        person_id=source["id"],
        event_request_id=event_request["id"],
        title="Revisar respuesta",
        due_at=timezone.now() + timedelta(days=1),
        next_contact_at=timezone.now() + timedelta(hours=8),
    )
    consent = people_services.record_consent(
        first_owner,
        first_id,
        person_id=source["id"],
        purpose="seguimiento_comercial",
        channel="email",
        event_type="grant",
        decision="granted",
        source="formulario_web",
        occurred_at=timezone.now(),
        evidence_reference="EVIDENCIA-SINTETICA-001",
    )
    people_services.merge_people(
        first_owner,
        first_id,
        source_person_id=source["id"],
        target_person_id=target["id"],
        source_revision=source["revision"],
        target_revision=target["revision"],
        reason="Duplicación verificada para prueba de aislamiento.",
        idempotency_key=uuid4(),
    )

    assert PersonMerge.objects.count() == 0
    assert Interaction.objects.count() == 0
    with authorized_tenant_scope(second_owner, second_id, Capability.PERSON_READ):
        assert PersonMerge.objects.count() == 0
        assert Interaction.objects.count() == 0
        assert FollowUpTask.objects.count() == 0

    with authorized_tenant_scope(first_owner, first_id, Capability.PERSON_READ):
        assert PersonMerge.objects.count() == 1
        assert Interaction.objects.count() == 1
        assert FollowUpTask.objects.count() == 1
        assert FollowUpTaskHistory.objects.count() == 1
        assert ConsentEvent.objects.count() == 1
        with pytest.raises(DatabaseError), transaction.atomic():
            Interaction.objects.filter(pk=interaction["id"]).update(summary="Sobrescrito")
        with pytest.raises(DatabaseError), transaction.atomic():
            ConsentEvent.objects.filter(pk=consent["id"]).update(decision="revoked")
        with pytest.raises(DatabaseError), transaction.atomic():
            PersonMerge.objects.update(reason="Sobrescrita")
        with pytest.raises(DatabaseError), transaction.atomic():
            EventRequestHistory.objects.filter(event_request_id=event_request["id"]).delete()
        with pytest.raises(DatabaseError), transaction.atomic():
            FollowUpTask.objects.bulk_create(
                [
                    FollowUpTask(
                        organization_id=first_id,
                        person_id=source["id"],
                        event_request_id=None,
                        title="Relación bulk inválida",
                        due_at=timezone.now() + timedelta(days=2),
                        responsible_membership_id=first.owner_membership.pk,
                        created_by_membership_id=first.owner_membership.pk,
                    )
                ]
            )
        with (
            pytest.raises((DatabaseError, IntegrityError)),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """
                INSERT INTO public.people_consentevent (
                    id, organization_id, person_id, purpose, channel, event_type,
                    decision, source, occurred_at, evidence_reference,
                    recorded_by_membership_id, created_at
                ) VALUES (
                    %s, %s, %s, 'seguimiento_comercial', 'email', 'grant',
                    'granted', 'sql_directo', CURRENT_TIMESTAMP, 'CRUCE-SINTETICO',
                    %s, CURRENT_TIMESTAMP
                )
                """,
                [uuid4(), second_id, foreign["id"], first.owner_membership.pk],
            )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = ANY(%s)
            ORDER BY relname
            """,
            [list(P7_PRIVATE_TABLES)],
        )
        metadata = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                has_table_privilege('claridez_app', 'people_personmerge', 'UPDATE'),
                has_table_privilege('claridez_app', 'people_personmerge', 'DELETE'),
                has_table_privilege('claridez_app', 'people_consentevent', 'UPDATE'),
                has_table_privilege('claridez_app', 'crm_interaction', 'UPDATE'),
                has_table_privilege('claridez_app', 'crm_followuptask', 'UPDATE'),
                has_table_privilege('claridez_app', 'crm_followuptask', 'DELETE')
            """
        )
        privileges = cursor.fetchone()
    assert metadata == sorted((table, True, True) for table in P7_PRIVATE_TABLES)
    assert privileges == (False, False, False, False, True, False)
    assert task["id"]


def test_concurrent_merge_is_single_and_idempotent() -> None:
    owner, creation = _owner("p7-concurrent-merge")
    organization_id = creation.organization.pk
    source = _person(owner, organization_id, phone="0992000004", name="Origen concurrente")
    target = _person(owner, organization_id, phone="0992000005", name="Destino concurrente")
    key = uuid4()
    barrier = Barrier(2)

    def merge_once() -> UUID:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            barrier.wait(timeout=10)
            result = people_services.merge_people(
                actor,
                organization_id,
                source_person_id=source["id"],
                target_person_id=target["id"],
                source_revision=source["revision"],
                target_revision=target["revision"],
                reason="La misma decisión concurrente.",
                idempotency_key=key,
            )
            return UUID(str(result["id"]))
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: merge_once(), range(2)))

    assert len(set(results)) == 1
    with authorized_tenant_scope(owner, organization_id, Capability.PERSON_READ):
        assert PersonMerge.objects.count() == 1
        assert PersonContactAlias.objects.filter(source_person_id=source["id"]).count() == 1


def test_corrective_contact_and_task_invariants_cover_sql_and_bulk() -> None:
    owner, creation = _owner("p7-corrective-sql-bulk")
    organization_id = creation.organization.pk
    person = people_services.create_person(
        owner,
        organization_id,
        full_name="Contacto SQL",
        phone="0992000010",
        email="sql-original@example.com",
        origin="website",
        origin_detail="Prueba correctiva",
    )
    other = people_services.create_person(
        owner,
        organization_id,
        full_name="Otro contacto SQL",
        phone="0992000011",
        email="otro-sql@example.com",
        origin="website",
        origin_detail="Prueba correctiva",
    )
    event_request = _request(owner, organization_id, person["id"], days=42)

    with authorized_tenant_scope(owner, organization_id, Capability.PERSON_MANAGE):
        changed = Person.objects.filter(pk=person["id"]).update(
            phone_e164="+593992000012",
            email="sql-actual@example.com",
            revision=F("revision") + 1,
        )
        assert changed == 1
        assert set(
            PersonContactAlias.objects.filter(person_id=person["id"]).values_list(
                "kind", "normalized_value"
            )
        ) >= {
            ("phone", "+593992000010"),
            ("email", "sql-original@example.com"),
        }
        with pytest.raises((DatabaseError, IntegrityError)), transaction.atomic():
            Person.objects.filter(pk=other["id"]).update(email="sql-original@example.com")

        person_row = Person.objects.get(pk=person["id"])
        person_row.phone_e164 = "+593992000013"
        person_row.revision += 1
        Person.objects.bulk_update([person_row], ["phone_e164", "revision"])
        assert PersonContactAlias.objects.filter(
            person_id=person["id"], kind="phone", normalized_value="+593992000012"
        ).exists()

    task = create_task(
        owner,
        organization_id,
        person_id=person["id"],
        event_request_id=event_request["id"],
        title="Tarea SQL",
        due_at=timezone.now() + timedelta(days=3),
        next_contact_at=None,
    )
    with authorized_tenant_scope(owner, organization_id, Capability.TASK_MANAGE):
        no_op = FollowUpTask.objects.filter(pk=task["id"]).update(title="Tarea SQL")
        assert no_op == 0
        assert FollowUpTaskHistory.objects.filter(task_id=task["id"]).count() == 1
        with pytest.raises((DatabaseError, IntegrityError)), transaction.atomic():
            FollowUpTask.objects.filter(pk=task["id"]).update(
                status="cancelled", revision=2, cancellation_reason=""
            )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.crm_followuptask
                SET status = 'cancelled', revision = revision + 1,
                    cancellation_reason = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                ["Cancelación verificada por SQL directo.", task["id"]],
            )
        cancelled_history = FollowUpTaskHistory.objects.get(task_id=task["id"], revision=2)
        assert cancelled_history.kind == "cancelled"
        assert cancelled_history.reason == "Cancelación verificada por SQL directo."

    bulk_task = create_task(
        owner,
        organization_id,
        person_id=person["id"],
        event_request_id=event_request["id"],
        title="Tarea bulk original",
        due_at=timezone.now() + timedelta(days=4),
        next_contact_at=None,
    )
    with authorized_tenant_scope(owner, organization_id, Capability.TASK_MANAGE):
        bulk_row = FollowUpTask.objects.get(pk=bulk_task["id"])
        bulk_row.title = "Tarea bulk corregida"
        bulk_row.revision += 1
        FollowUpTask.objects.bulk_update([bulk_row], ["title", "revision"])
        bulk_history = FollowUpTaskHistory.objects.get(task_id=bulk_task["id"], revision=2)
        assert bulk_history.kind == "updated"
        assert bulk_history.title == "Tarea bulk corregida"
        assert bulk_history.reason == ""


def test_concurrent_current_email_assignment_has_one_winner() -> None:
    owner, creation = _owner("p7-concurrent-email")
    organization_id = creation.organization.pk
    barrier = Barrier(2)

    def create_once(index: int) -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            barrier.wait(timeout=10)
            try:
                people_services.create_person(
                    actor,
                    organization_id,
                    full_name=f"Persona concurrente {index}",
                    phone=f"099200002{index}",
                    email="correo-concurrente@example.com",
                    origin="website",
                    origin_detail="Prueba concurrente",
                )
            except PeopleError as error:
                return error.code
            return "created"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create_once, range(2)))

    assert sorted(results) == ["created", "duplicate_person"]
    with authorized_tenant_scope(owner, organization_id, Capability.PERSON_READ):
        assert Person.objects.filter(email="correo-concurrente@example.com").count() == 1


def test_concurrent_task_revision_allows_only_one_update() -> None:
    owner, creation = _owner("p7-concurrent-task")
    organization_id = creation.organization.pk
    person = _person(owner, organization_id, phone="0992000030", name="Tarea concurrente")
    task = create_task(
        owner,
        organization_id,
        person_id=person["id"],
        event_request_id=None,
        title="Versión inicial",
        due_at=timezone.now() + timedelta(days=2),
        next_contact_at=None,
    )
    barrier = Barrier(2)

    def update_once(index: int) -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            barrier.wait(timeout=10)
            try:
                update_task(
                    actor,
                    organization_id,
                    task_id=task["id"],
                    revision=task["revision"],
                    changes={"title": f"Versión concurrente {index}"},
                )
            except CrmError as error:
                return error.code
            return "updated"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update_once, range(2)))

    assert sorted(results) == ["stale_revision", "updated"]
    with authorized_tenant_scope(owner, organization_id, Capability.TASK_MANAGE):
        stored = FollowUpTask.objects.get(pk=task["id"])
        assert stored.revision == 2
        assert FollowUpTaskHistory.objects.filter(task=stored).count() == 2


def test_postgresql_cluster_guardians_allow_corrections_but_keep_original_context() -> None:
    owner, creation = _owner("p7-cluster-sql")
    organization_id = creation.organization.pk
    source = _person(owner, organization_id, phone="0992000031", name="Fuente SQL")
    target = _person(owner, organization_id, phone="0992000032", name="Destino SQL")
    event_request = _request(owner, organization_id, source["id"], days=47)
    interaction = record_interaction(
        owner,
        organization_id,
        person_id=source["id"],
        event_request_id=event_request["id"],
        channel="email",
        direction="inbound",
        occurred_at=timezone.now() - timedelta(days=1),
        summary="Evidencia original SQL.",
    )
    consent = people_services.record_consent(
        owner,
        organization_id,
        person_id=source["id"],
        purpose="seguimiento_comercial",
        channel="email",
        event_type="grant",
        decision="granted",
        source="registro_sql",
        occurred_at=timezone.now() - timedelta(days=1),
        evidence_reference="SQL-CONSENT-001",
    )
    people_services.merge_people(
        owner,
        organization_id,
        source_person_id=source["id"],
        target_person_id=target["id"],
        source_revision=source["revision"],
        target_revision=target["revision"],
        reason="Fusión previa a correcciones SQL.",
        idempotency_key=uuid4(),
    )
    interaction_correction_id = uuid4()
    consent_correction_id = uuid4()

    with authorized_tenant_scope(owner, organization_id, Capability.INTERACTION_RECORD):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.crm_interaction (
                    id, organization_id, person_id, event_request_id, channel, direction,
                    occurred_at, responsible_membership_id, summary, correction_of_id,
                    recorded_by_membership_id, created_at
                ) VALUES (
                    %s, %s, %s, %s, 'email', 'inbound', CURRENT_TIMESTAMP,
                    %s, 'Corrección SQL dentro del cluster.', %s, %s, CURRENT_TIMESTAMP
                )
                """,
                [
                    interaction_correction_id,
                    organization_id,
                    target["id"],
                    event_request["id"],
                    creation.owner_membership.pk,
                    interaction["id"],
                    creation.owner_membership.pk,
                ],
            )
        assert Interaction.objects.filter(
            pk=interaction_correction_id, correction_of_id=interaction["id"]
        ).exists()
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.crm_interaction (
                    id, organization_id, person_id, event_request_id, channel, direction,
                    occurred_at, responsible_membership_id, summary, correction_of_id,
                    recorded_by_membership_id, created_at
                ) VALUES (
                    %s, %s, %s, NULL, 'email', 'inbound', CURRENT_TIMESTAMP,
                    %s, 'Contexto alterado.', %s, %s, CURRENT_TIMESTAMP
                )
                """,
                [
                    uuid4(),
                    organization_id,
                    target["id"],
                    creation.owner_membership.pk,
                    interaction["id"],
                    creation.owner_membership.pk,
                ],
            )

    with authorized_tenant_scope(owner, organization_id, Capability.CONSENT_MANAGE):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.people_consentevent (
                    id, organization_id, person_id, purpose, channel, event_type,
                    decision, source, occurred_at, evidence_reference, corrects_id,
                    recorded_by_membership_id, created_at
                ) VALUES (
                    %s, %s, %s, 'seguimiento_comercial', 'email', 'correction',
                    'revoked', 'rectificacion_sql', CURRENT_TIMESTAMP, 'SQL-CONSENT-002',
                    %s, %s, CURRENT_TIMESTAMP
                )
                """,
                [
                    consent_correction_id,
                    organization_id,
                    target["id"],
                    consent["id"],
                    creation.owner_membership.pk,
                ],
            )
        assert ConsentEvent.objects.filter(
            pk=consent_correction_id, corrects_id=consent["id"]
        ).exists()


def test_p7_migrates_existing_people_in_place_and_backfills_only_cutover_state() -> None:
    owner, creation = _owner("p7-migration")
    organization_id = creation.organization.pk
    person = _person(owner, organization_id, phone="0992000006", name="Persona preexistente")
    event_request = _request(owner, organization_id, person["id"], days=45)
    latest_targets: list[tuple[str, str | None]] = []

    try:
        executor = MigrationExecutor(connection)
        latest_targets = list(executor.loader.graph.leaf_nodes())
        old_targets = [
            node for node in latest_targets if node[0] not in {"commercial", "people", "crm"}
        ]
        old_targets.extend(
            [("commercial", "0004_multi_space_and_catalog"), ("people", None), ("crm", None)]
        )
        executor.migrate(old_targets)

        with (
            authorized_tenant_scope(owner, organization_id, Capability.PERSON_READ),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """
                SELECT
                    to_regclass('public.commercial_person'),
                    to_regclass('public.commercial_personrevision'),
                    to_regclass('public.people_person'),
                    (SELECT count(*) FROM public.commercial_person WHERE id = %s)
                """,
                [person["id"]],
            )
            physical_state = cursor.fetchone()
        assert physical_state == (
            "commercial_person",
            "commercial_personrevision",
            None,
            1,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
    finally:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            executor.migrate(executor.loader.graph.leaf_nodes())

    with authorized_tenant_scope(owner, organization_id, Capability.PERSON_READ):
        assert Person.objects.filter(pk=person["id"]).count() == 1
        history: Any = list(
            EventRequestHistory.objects.filter(event_request_id=event_request["id"]).values_list(
                "kind", "occurred_at", "provenance", "actor_membership_id"
            )
        )
    assert history == [("cutover_state", None, "cutover_snapshot", None)]


def test_corrective_migration_marks_unrecoverable_legacy_cancellation_reasons() -> None:
    owner, creation = _owner("p7-corrective-migration")
    organization_id = creation.organization.pk
    person = _person(owner, organization_id, phone="0992000040", name="Cancelación heredada")
    task = create_task(
        owner,
        organization_id,
        person_id=person["id"],
        event_request_id=None,
        title="Seguimiento cancelado antes de la corrección",
        due_at=timezone.now() + timedelta(days=2),
        next_contact_at=None,
    )
    update_task(
        owner,
        organization_id,
        task_id=task["id"],
        revision=task["revision"],
        changes={"status": "cancelled", "reason": "Razón que P7 descartaba."},
    )

    try:
        executor = MigrationExecutor(connection)
        latest_targets = list(executor.loader.graph.leaf_nodes())
        previous_targets = [node for node in latest_targets if node[0] != "crm"]
        previous_targets.append(("crm", "0002_interaction_correction_guard"))
        executor.migrate(previous_targets)

        with (
            authorized_tenant_scope(owner, organization_id, Capability.TASK_MANAGE),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "ALTER TABLE public.crm_followuptaskhistory "
                "DISABLE TRIGGER crm_taskhistory_immutable"
            )
            cursor.execute(
                "UPDATE public.crm_followuptaskhistory SET reason = '' WHERE task_id = %s",
                [task["id"]],
            )
            cursor.execute(
                "ALTER TABLE public.crm_followuptaskhistory "
                "ENABLE TRIGGER crm_taskhistory_immutable"
            )

        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
    finally:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            executor.migrate(executor.loader.graph.leaf_nodes())

    with authorized_tenant_scope(owner, organization_id, Capability.TASK_MANAGE):
        stored = FollowUpTask.objects.get(pk=task["id"])
        cancelled_history = FollowUpTaskHistory.objects.get(task_id=task["id"], revision=2)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname IN ('crm_followuptask', 'crm_followuptaskhistory')
            ORDER BY relname
            """
        )
        rls_state = cursor.fetchall()
    assert stored.status == "cancelled"
    assert stored.cancellation_reason == ""
    assert stored.cancellation_reason_unavailable is True
    assert cancelled_history.kind == "cancelled"
    assert cancelled_history.reason == ""
    assert cancelled_history.reason_unavailable is True
    assert rls_state == [
        ("crm_followuptask", True, True),
        ("crm_followuptaskhistory", True, True),
    ]
