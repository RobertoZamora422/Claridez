from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.services import (
    accept_quotation_version,
    confirm_reservation,
    create_event_request,
    create_person,
    create_quotation,
    issue_quotation_version,
    replace_quotation_draft,
)
from claridez.identity.models import User
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.services import create_organization
from claridez.scheduling.cutover import verify_scheduling_cutover
from claridez.scheduling.models import Reservation, ScheduleAllocation, ScheduleEvent
from claridez.scheduling.services import read_reservation

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]

P7_TARGETS = [
    ("identity", "0001_initial"),
    ("organizations", "0004_venues_and_spaces"),
    ("catalog", "0002_catalog_history_integrity"),
    ("commercial", "0006_repair_cutover_history"),
    ("operations", "0002_commercial_operations_guardian"),
    ("people", "0004_contact_ownership_locking"),
    ("crm", "0003_corrective_integrity"),
    ("scheduling", None),
]
P6_TARGETS = [
    ("identity", "0001_initial"),
    ("organizations", "0004_venues_and_spaces"),
    ("catalog", "0002_catalog_history_integrity"),
    ("commercial", "0004_multi_space_and_catalog"),
    ("operations", "0002_commercial_operations_guardian"),
    ("people", None),
    ("crm", None),
    ("scheduling", None),
]


def _owner() -> tuple[User, UUID]:
    owner = User.objects.create_user(
        email=f"p8-migrations-{uuid4()}@example.test",
        password="p8-migration-test-password-42!",
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    creation = create_organization(
        owner_user_id=owner.pk,
        name="P8 migration rehearsal",
        slug=f"p8-migration-{uuid4()}",
    )
    return owner, creation.organization.pk


def _hold(
    owner: User,
    organization_id: UUID,
    *,
    phone: str,
    days: int,
) -> dict[str, Any]:
    venue = list_venues(owner, organization_id)[0]
    event_type = next(iter(list_event_types(owner, organization_id)), None)
    if event_type is None:
        event_type = create_event_type(owner, organization_id, name="Evento de migración")
    person = create_person(
        owner,
        organization_id,
        full_name=f"Persona {phone}",
        phone=phone,
        email=None,
        origin="referral",
        origin_detail=None,
    )
    starts_at = timezone.now() + timedelta(days=days)
    request = create_event_request(
        owner,
        organization_id,
        person_id=person["id"],
        event_type_id=event_type["id"],
        space_id=venue["spaces"][0]["id"],
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=4),
        estimated_guests=40,
        general_need="Ensayo sintético de cutover",
        notes="",
        origin="referral",
        origin_detail=None,
    )
    quotation = create_quotation(
        owner,
        organization_id,
        request_id=request["id"],
        valid_until=timezone.now() + timedelta(days=2),
    )
    draft = quotation["versions"][0]
    replace_quotation_draft(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=draft["revision"],
        valid_until=timezone.now() + timedelta(days=2),
        notes="Evidencia comercial inmutable",
        lines=[
            {
                "description": "Servicio sintético",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("500.00"),
                "discount_amount": Decimal("0.00"),
            }
        ],
    )
    issue_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
    )
    return accept_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        channel="email",
        note="Aceptación sintética",
    )


def _set_tenant(organization_id: UUID | str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('claridez.organization_id', %s, false)",
            (str(organization_id),),
        )


def _restore_head() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def test_p8_from_p7_preserves_rows_and_backfills_without_inventing_history() -> None:
    owner, organization_id = _owner()
    provisional = _hold(owner, organization_id, phone="0998100001", days=120)
    confirmed_hold = _hold(owner, organization_id, phone="0998100002", days=125)
    confirmed = confirm_reservation(
        owner,
        organization_id,
        reservation_id=confirmed_hold["id"],
        kind="external_deposit",
        recognized_amount=Decimal("50.00"),
        reported_at=timezone.now(),
        reference="Depósito sintético",
    )
    expired_hold = _hold(owner, organization_id, phone="0998100003", days=130)
    _set_tenant(organization_id)
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE public.commercial_reservation DISABLE TRIGGER USER")
        cursor.execute(
            "UPDATE public.commercial_reservation SET hold_expires_at = %s WHERE id = %s",
            (timezone.now() - timedelta(seconds=1), expired_hold["id"]),
        )
        cursor.execute("ALTER TABLE public.commercial_reservation ENABLE TRIGGER USER")
    expired = read_reservation(owner, organization_id, reservation_id=expired_hold["id"])
    assert expired["status"] == "expired"
    reservation_ids = {
        UUID(str(provisional["id"])),
        UUID(str(confirmed["id"])),
        UUID(str(expired_hold["id"])),
    }

    try:
        MigrationExecutor(connection).migrate(P7_TARGETS)
        _set_tenant(organization_id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, status FROM public.commercial_reservation "
                "WHERE organization_id = %s ORDER BY id",
                (organization_id,),
            )
            p7_rows = cursor.fetchall()
            cursor.execute(
                "UPDATE public.commercial_reservation SET hold_expires_at = %s WHERE id = %s",
                (timezone.now() - timedelta(seconds=1), provisional["id"]),
            )
        assert {row[0] for row in p7_rows} == reservation_ids

        _restore_head()
        _set_tenant(organization_id)
        rows = list(Reservation.objects.filter(organization_id=organization_id).order_by("id"))
        assert {row.pk for row in rows} == reservation_ids
        assert all(row.root_id == row.pk and row.predecessor_id is None for row in rows)
        assert all(
            (
                row.setup_minutes,
                row.teardown_minutes,
                row.buffer_before_minutes,
                row.buffer_after_minutes,
            )
            == (0, 0, 0, 0)
            for row in rows
        )
        assert ScheduleAllocation.objects.filter(organization_id=organization_id).count() == 3
        assert (
            ScheduleEvent.objects.filter(
                organization_id=organization_id,
                kind=ScheduleEvent.Kind.CUTOVER_SNAPSHOT,
            ).count()
            == 3
        )
        assert (
            ScheduleEvent.objects.filter(
                organization_id=organization_id,
                reservation_id=provisional["id"],
                kind=ScheduleEvent.Kind.RESERVATION_EXPIRED,
            ).count()
            == 1
        )
        assert (
            ScheduleEvent.objects.filter(
                organization_id=organization_id,
                reservation_id=expired_hold["id"],
                kind=ScheduleEvent.Kind.RESERVATION_EXPIRED,
            ).count()
            == 0
        )
        assert Reservation.objects.get(pk=confirmed["id"]).status == Reservation.Status.CONFIRMED
        assert verify_scheduling_cutover()["status"] == "ok"
    finally:
        _restore_head()


@pytest.mark.parametrize("targets", [P6_TARGETS, P7_TARGETS], ids=["p6", "p7"])
def test_p8_migration_paths_and_immediate_rollback_are_reapplicable(
    targets: list[tuple[str, str | None]],
) -> None:
    owner, organization_id = _owner()
    hold = _hold(owner, organization_id, phone=f"09{uuid4().int % 100000000:08d}", days=145)
    reservation_id = UUID(str(hold["id"]))
    try:
        MigrationExecutor(connection).migrate(targets)
        _set_tenant(organization_id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM public.commercial_reservation WHERE id = %s",
                (reservation_id,),
            )
            assert cursor.fetchone()[0] == 1
        _restore_head()
        _set_tenant(organization_id)
        assert Reservation.objects.filter(pk=reservation_id).exists()
        assert ScheduleAllocation.objects.filter(reservation_id=reservation_id).count() == 1
        assert verify_scheduling_cutover()["status"] == "ok"
    finally:
        _restore_head()


def test_p8_empty_database_installs_single_temporal_exclusion() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                to_regclass('public.commercial_reservation') IS NOT NULL,
                to_regclass('public.scheduling_scheduleallocation') IS NOT NULL,
                count(*) FILTER (WHERE conname = 'scheduling_allocation_no_overlap'),
                count(*) FILTER (WHERE conname = 'commercial_reservation_no_overlap')
            FROM pg_constraint
            WHERE contype = 'x'
            """
        )
        physical_reservation, allocation, unified, legacy = cursor.fetchone()
    assert (physical_reservation, allocation, unified, legacy) == (True, True, 1, 0)
