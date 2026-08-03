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
from django.utils import timezone

from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.models import EventRequestHistory
from claridez.commercial.services import create_event_request
from claridez.crm.models import FollowUpTask, FollowUpTaskHistory, Interaction
from claridez.crm.services import create_task, record_interaction
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.services import create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.people import services as people_services
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
