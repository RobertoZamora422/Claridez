"""Defensas PostgreSQL y concurrencia del flujo comercial 5.1."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from django.db import (
    DatabaseError,
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone
from psycopg.types.range import Range

from claridez.commercial.errors import CommercialError
from claridez.commercial.models import (
    EventRequest,
    Person,
    PersonRevision,
    QuotationLine,
    QuotationVersion,
    Reservation,
)
from claridez.commercial.services import (
    accept_quotation_version,
    confirm_reservation,
    create_event_request,
    create_person,
    create_quotation,
    issue_quotation_version,
    replace_quotation_draft,
    update_person,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.services import create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
PASSWORD = "commercial-postgresql-concurrency-42!"
COMMERCIAL_TABLES = (
    "commercial_person",
    "commercial_personrevision",
    "commercial_eventrequest",
    "commercial_quotationsequence",
    "commercial_quotation",
    "commercial_quotationversion",
    "commercial_quotationline",
    "commercial_reservation",
)


def _owner(prefix: str) -> tuple[User, Any]:
    owner = User.objects.create_user(
        email=f"{prefix}@example.com",
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    creation = create_organization(owner_user_id=owner.pk, name=f"Organización {prefix}")
    return owner, creation


def _person(owner: User, organization_id: Any, phone: str) -> dict[str, Any]:
    return create_person(
        owner,
        organization_id,
        full_name="Contacto de prueba",
        phone=phone,
        email=None,
        origin="whatsapp",
        origin_detail=None,
    )


def _draft(
    owner: User,
    organization_id: Any,
    *,
    phone: str,
    starts_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    person = _person(owner, organization_id, phone)
    event_request = create_event_request(
        owner,
        organization_id,
        person_id=person["id"],
        event_type="Boda",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=5),
        estimated_guests=80,
        general_need="Salón completo",
        notes="",
        origin="referral",
        origin_detail=None,
    )
    quotation = create_quotation(
        owner,
        organization_id,
        request_id=event_request["id"],
        valid_until=timezone.now() + timedelta(days=3),
    )
    draft = quotation["versions"][0]
    quotation = replace_quotation_draft(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=draft["revision"],
        valid_until=timezone.now() + timedelta(days=3),
        notes="Snapshot emitible",
        lines=[
            {
                "description": "Alquiler del salón",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("1000.00"),
                "discount_amount": Decimal("50.00"),
            }
        ],
    )
    return event_request, quotation


def _issued(
    owner: User,
    organization_id: Any,
    *,
    phone: str,
    starts_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    event_request, quotation = _draft(owner, organization_id, phone=phone, starts_at=starts_at)
    quotation = issue_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
    )
    return event_request, quotation


def test_rls_tenant_relations_bulk_and_privileges_are_fail_closed() -> None:
    first_owner, first_creation = _owner("commercial-rls-first")
    second_owner, second_creation = _owner("commercial-rls-second")
    first_id = first_creation.organization.pk
    second_id = second_creation.organization.pk
    first = _person(first_owner, first_id, "0991111111")
    second = _person(second_owner, second_id, "0992222222")

    assert Person.objects.count() == 0
    with authorized_tenant_scope(first_owner, first_id, Capability.PERSON_MANAGE):
        assert list(Person.objects.values_list("pk", flat=True)) == [first["id"]]
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE commercial_person SET organization_id = %s WHERE id = %s",
                (second_id, first["id"]),
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            PersonRevision.objects.create(
                organization_id=first_id,
                person_id=second["id"],
                revision=99,
                full_name="Cruce inválido",
                phone_e164="+593992222222",
                email="",
                origin="whatsapp",
                origin_detail="",
                changed_by=first_owner,
            )

    with authorized_tenant_scope(second_owner, second_id, Capability.PERSON_READ):
        foreign_row = Person.objects.get(pk=second["id"])
    foreign_row.full_name = "Actualización cruzada"
    with authorized_tenant_scope(first_owner, first_id, Capability.PERSON_MANAGE):
        assert Person.objects.bulk_update([foreign_row], ["full_name"]) == 0

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = ANY(%s)
            ORDER BY relname
            """,
            (list(COMMERCIAL_TABLES),),
        )
        metadata = cursor.fetchall()
        cursor.execute(
            """
            SELECT tablename, policyname, cmd
            FROM pg_policies
            WHERE schemaname = 'public' AND tablename = ANY(%s)
            ORDER BY tablename
            """,
            (list(COMMERCIAL_TABLES),),
        )
        policies = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                has_table_privilege('claridez_app', 'commercial_person', 'DELETE'),
                has_table_privilege('claridez_app', 'commercial_quotationline', 'DELETE')
            """
        )
        delete_privileges = cursor.fetchone()

    assert len(metadata) == len(COMMERCIAL_TABLES)
    assert all(enabled and forced for _, enabled, forced in metadata)
    assert len(policies) == len(COMMERCIAL_TABLES)
    assert all(
        name == f"{table}_tenant_policy" and command == "ALL" for table, name, command in policies
    )
    assert delete_privileges == (False, True)


def test_sql_direct_bulk_totals_snapshots_and_lifecycle_are_guarded() -> None:
    owner, creation = _owner("commercial-sql")
    organization_id = creation.organization.pk
    event_request, quotation = _draft(
        owner,
        organization_id,
        phone="0993333333",
        starts_at=timezone.now() + timedelta(days=20),
    )
    version = quotation["versions"][0]

    with authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE):
        membership_id = creation.owner_membership.pk
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE commercial_quotationversion
                SET subtotal = 999.00, discount_total = 0.00, total = 999.00,
                    status = 'issued', issued_at = now(), issued_by_membership_id = %s
                WHERE id = %s
                """,
                (membership_id, version["id"]),
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            QuotationLine.objects.bulk_create(
                [
                    QuotationLine(
                        organization_id=organization_id,
                        quotation_version_id=version["id"],
                        position=2,
                        description="Línea inválida",
                        unit_label="unidad",
                        quantity=Decimal("0.000"),
                        unit_price=Decimal("1.00"),
                        discount_amount=Decimal("0.00"),
                        line_subtotal=Decimal("0.00"),
                        line_total=Decimal("0.00"),
                    )
                ]
            )

    issue_quotation_version(owner, organization_id, quotation_id=quotation["id"], version=1)
    reservation = accept_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        channel="phone_call",
        note="Aceptada",
    )
    with (
        authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE),
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            UPDATE commercial_reservation
            SET status = 'confirmed', confirmation_kind = 'external_deposit',
                recognized_deposit_amount = 5000.00, deposit_reported_at = now(),
                deposit_reference = 'Referencia externa', confirmed_at = now(),
                confirmed_by_membership_id = %s
            WHERE id = %s
            """,
            (creation.owner_membership.pk, reservation["id"]),
        )

    confirm_reservation(
        owner,
        organization_id,
        reservation_id=reservation["id"],
        kind="external_deposit",
        recognized_amount=Decimal("200.00"),
        reported_at=timezone.now(),
        reference="Constancia externa",
    )
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE):
        with pytest.raises(DatabaseError), transaction.atomic():
            EventRequest.objects.filter(pk=event_request["id"]).update(status="closed_lost")
        with pytest.raises(DatabaseError), transaction.atomic():
            PersonRevision.objects.filter(person_id=event_request["person"]["id"]).update(
                full_name="Historia alterada"
            )


def test_two_concurrent_acceptances_leave_one_active_reservation() -> None:
    owner, creation = _owner("commercial-double-accept")
    organization_id = creation.organization.pk
    starts_at = timezone.now() + timedelta(days=30)
    first_request, first_quote = _issued(
        owner, organization_id, phone="0994444444", starts_at=starts_at
    )
    second_request, second_quote = _issued(
        owner, organization_id, phone="0995555555", starts_at=starts_at
    )
    barrier = Barrier(2)

    def worker(quotation_id: Any) -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            barrier.wait(timeout=5)
            accept_quotation_version(
                actor,
                organization_id,
                quotation_id=quotation_id,
                version=1,
                channel="whatsapp",
                note="Aceptación concurrente",
            )
            return "ok"
        except CommercialError as error:
            return error.code
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, (first_quote["id"], second_quote["id"]), timeout=15))

    assert sorted(results) == ["ok", "schedule_conflict"]
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        assert (
            Reservation.objects.filter(
                status__in=[Reservation.Status.PROVISIONAL, Reservation.Status.CONFIRMED]
            ).count()
            == 1
        )
        assert sorted(
            EventRequest.objects.filter(
                pk__in=[first_request["id"], second_request["id"]]
            ).values_list("status", flat=True)
        ) == [EventRequest.Status.ACCEPTED, EventRequest.Status.QUOTED]
        assert sorted(
            QuotationVersion.objects.filter(
                pk__in=[first_quote["versions"][0]["id"], second_quote["versions"][0]["id"]]
            ).values_list("status", flat=True)
        ) == [QuotationVersion.Status.ACCEPTED, QuotationVersion.Status.ISSUED]


def test_two_concurrent_person_revisions_have_one_winner() -> None:
    owner, creation = _owner("commercial-person-concurrency")
    organization_id = creation.organization.pk
    person = _person(owner, organization_id, "0996666666")
    barrier = Barrier(2)

    def worker(name: str) -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            barrier.wait(timeout=5)
            update_person(
                actor,
                organization_id,
                person_id=person["id"],
                revision=1,
                changes={"full_name": name},
            )
            return "ok"
        except CommercialError as error:
            return error.code
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, ("Nombre A", "Nombre B"), timeout=15))

    assert sorted(results) == ["ok", "stale_revision"]
    with authorized_tenant_scope(owner, organization_id, Capability.PERSON_READ):
        assert Person.objects.get(pk=person["id"]).revision == 2
        assert PersonRevision.objects.filter(person_id=person["id"]).count() == 2


def test_postgresql_enforces_line_multiplication_for_orm_bulk_and_sql() -> None:
    owner, creation = _owner("commercial-line-product")
    organization_id = creation.organization.pk
    _, quotation = _draft(
        owner,
        organization_id,
        phone="0997777777",
        starts_at=timezone.now() + timedelta(days=40),
    )
    version_id = quotation["versions"][0]["id"]

    def line(position: int, subtotal: str) -> QuotationLine:
        return QuotationLine(
            organization_id=organization_id,
            quotation_version_id=version_id,
            position=position,
            description="Redondeo monetario",
            unit_label="unidad",
            quantity=Decimal("1.005"),
            unit_price=Decimal("1.00"),
            discount_amount=Decimal("0.00"),
            line_subtotal=Decimal(subtotal),
            line_total=Decimal(subtotal),
        )

    with authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE):
        valid = line(2, "1.01")
        valid.save()
        assert valid.line_subtotal == Decimal("1.01")

        with pytest.raises(IntegrityError), transaction.atomic():
            line(3, "2.00").save()

        with pytest.raises(IntegrityError), transaction.atomic():
            QuotationLine.objects.bulk_create([line(3, "2.00")])

        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO commercial_quotationline (
                    id, organization_id, quotation_version_id, position,
                    description, unit_label, quantity, unit_price,
                    discount_amount, line_subtotal, line_total, created_at, updated_at
                ) VALUES (%s, %s, %s, 3, 'SQL incorrecto', 'unidad',
                          1.005, 1.00, 0.00, 2.00, 2.00, now(), now())
                """,
                (uuid4(), organization_id, version_id),
            )

        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE commercial_quotationversion
                SET subtotal = 1003.01, discount_total = 50.00, total = 953.01
                WHERE id = %s
                """,
                (version_id,),
            )
            cursor.execute(
                """
                INSERT INTO commercial_quotationline (
                    id, organization_id, quotation_version_id, position,
                    description, unit_label, quantity, unit_price,
                    discount_amount, line_subtotal, line_total, created_at, updated_at
                ) VALUES (%s, %s, %s, 3, 'Agregado coherente pero producto incorrecto',
                          'unidad', 1.005, 1.00, 0.00, 2.00, 2.00, now(), now())
                """,
                (uuid4(), organization_id, version_id),
            )

        stored = QuotationVersion.objects.get(pk=version_id)
        assert (stored.subtotal, stored.discount_total, stored.total) == (
            Decimal("1000.00"),
            Decimal("50.00"),
            Decimal("950.00"),
        )


def test_postgresql_enforces_reservation_request_snapshot_and_acceptance_coherence() -> None:
    owner, creation = _owner("commercial-reservation-coherence")
    organization_id = creation.organization.pk
    start = timezone.now() + timedelta(days=50)
    first_request, first_quote = _issued(
        owner,
        organization_id,
        phone="0998888888",
        starts_at=start,
    )
    reservation_payload = accept_quotation_version(
        owner,
        organization_id,
        quotation_id=first_quote["id"],
        version=1,
        channel="whatsapp",
        note="Aceptada",
    )
    second_request, second_quote = _draft(
        owner,
        organization_id,
        phone="0999999999",
        starts_at=start + timedelta(days=2),
    )
    invalid_version_id = second_quote["versions"][0]["id"]

    with authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE):
        reservation = Reservation.objects.get(pk=reservation_payload["id"])
        original = (
            reservation.event_request_id,
            reservation.quotation_version_id,
            reservation.event_interval,
            reservation.event_timezone,
        )
        invalid_interval = Range(
            reservation.event_interval.lower + timedelta(hours=1),
            reservation.event_interval.upper + timedelta(hours=1),
            bounds="[)",
        )
        orm_changes = (
            {"event_request_id": second_request["id"]},
            {"event_interval": invalid_interval},
            {"event_timezone": "UTC"},
            {"quotation_version_id": invalid_version_id},
        )
        for changes in orm_changes:
            with pytest.raises(DatabaseError), transaction.atomic():
                Reservation.objects.filter(pk=reservation.pk).update(**changes)

        sql_changes: tuple[tuple[str, Any], ...] = (
            ("event_request_id = %s", second_request["id"]),
            ("event_interval = %s", invalid_interval),
            ("event_timezone = %s", "UTC"),
            ("quotation_version_id = %s", invalid_version_id),
        )
        for assignment, value in sql_changes:
            with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE commercial_reservation SET {assignment} WHERE id = %s",
                    (value, reservation.pk),
                )

        invalid_version = QuotationVersion.objects.get(pk=invalid_version_id)
        with pytest.raises(DatabaseError), transaction.atomic():
            Reservation.objects.create(
                organization_id=organization_id,
                event_request_id=second_request["id"],
                quotation_version=invalid_version,
                event_interval=Range(
                    invalid_version.event_starts_at_snapshot,
                    invalid_version.event_ends_at_snapshot,
                    bounds="[)",
                ),
                event_timezone=invalid_version.event_timezone_snapshot,
                status=Reservation.Status.PROVISIONAL,
                hold_expires_at=timezone.now() + timedelta(hours=48),
            )

        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO commercial_reservation (
                    id, organization_id, event_request_id, quotation_version_id,
                    event_interval, event_timezone, status, hold_expires_at,
                    confirmation_kind, deposit_reference, waiver_reason,
                    cancellation_reason, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, tstzrange(%s, %s, '[)'), %s,
                    'provisional', now() + interval '48 hours', '', '', '', '', now(), now()
                )
                """,
                (
                    uuid4(),
                    organization_id,
                    second_request["id"],
                    invalid_version_id,
                    invalid_version.event_starts_at_snapshot,
                    invalid_version.event_ends_at_snapshot,
                    invalid_version.event_timezone_snapshot,
                ),
            )

        reservation.refresh_from_db()
        assert (
            reservation.event_request_id,
            reservation.quotation_version_id,
            reservation.event_interval,
            reservation.event_timezone,
        ) == original

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT prosecdef,
                       NOT EXISTS (
                           SELECT 1
                           FROM aclexplode(pg_proc.proacl) AS acl
                           WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                       )
                FROM pg_proc
                WHERE oid = 'public.claridez_validate_reservation_coherence()'::regprocedure
                """
            )
            assert cursor.fetchone() == (False, True)

        assert first_request["id"] == reservation.event_request_id
