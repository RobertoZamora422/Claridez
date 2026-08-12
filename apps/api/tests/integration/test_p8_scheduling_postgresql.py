"""C01-C18: concurrencia e integridad PostgreSQL reales de P8."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone

from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.errors import CommercialError
from claridez.commercial.services import (
    accept_quotation_version,
    cancel_reservation,
    confirm_reservation,
    create_event_request,
    create_person,
    create_quotation,
    issue_quotation_version,
    replace_quotation_draft,
)
from claridez.identity.models import User
from claridez.operations.errors import OperationsError
from claridez.operations.services import assign_preparation, mark_ready, read_event, update_item
from claridez.operations.services.transitions import start_event
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import create_space, list_venues
from claridez.organizations.models import Membership
from claridez.organizations.services import create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.scheduling.errors import SchedulingError
from claridez.scheduling.models import (
    Reservation,
    ScheduleAllocation,
    ScheduleBlock,
    ScheduleEvent,
)
from claridez.scheduling.services import (
    availability,
    create_block,
    reschedule_reservation,
    update_policy,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
PASSWORD = "p8-postgresql-concurrency-42!"
LOCAL_ZONE = ZoneInfo("America/Guayaquil")
P8_TABLES = (
    "scheduling_spaceschedulepolicy",
    "scheduling_scheduleblock",
    "scheduling_scheduleblocktarget",
    "scheduling_scheduleevent",
    "scheduling_scheduleallocation",
)


def _owner(slug: str) -> tuple[User, UUID]:
    owner = User.objects.create_user(
        email=f"{slug}-{uuid4()}@example.test",
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    creation = create_organization(owner_user_id=owner.pk, name=f"P8 {slug} {uuid4()}")
    return owner, creation.organization.pk


def _space_ids(owner: User, organization_id: UUID, count: int = 1) -> tuple[UUID, ...]:
    venue = list_venues(owner, organization_id)[0]
    identifiers = [UUID(str(item["id"])) for item in venue["spaces"]]
    while len(identifiers) < count:
        created = create_space(
            owner,
            organization_id,
            venue_id=venue["id"],
            name=f"Espacio {len(identifiers) + 1}",
        )
        identifiers.append(UUID(str(created["id"])))
    return tuple(identifiers[:count])


def _quote(
    owner: User,
    organization_id: UUID,
    *,
    phone: str,
    starts_at: datetime,
    space_id: UUID,
) -> tuple[dict[str, Any], dict[str, Any]]:
    event_type = next(iter(list_event_types(owner, organization_id)), None)
    if event_type is None:
        event_type = create_event_type(owner, organization_id, name="Evento P8")
    person = create_person(
        owner,
        organization_id,
        full_name=f"Contacto {phone}",
        phone=phone,
        email=None,
        origin="whatsapp",
        origin_detail=None,
    )
    request = create_event_request(
        owner,
        organization_id,
        person_id=person["id"],
        event_type_id=event_type["id"],
        space_id=space_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=4),
        estimated_guests=60,
        general_need="Concurrencia de agenda",
        notes="",
        origin="whatsapp",
        origin_detail=None,
    )
    quotation = create_quotation(
        owner,
        organization_id,
        request_id=request["id"],
        valid_until=timezone.now() + timedelta(days=3),
    )
    draft = quotation["versions"][0]
    replace_quotation_draft(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=draft["revision"],
        valid_until=timezone.now() + timedelta(days=3),
        notes="Snapshot concurrente",
        lines=[
            {
                "description": "Servicio",
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
    return request, quotation


def _accept(owner: User, organization_id: UUID, quotation: dict[str, Any]) -> dict[str, Any]:
    return accept_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        channel="whatsapp",
        note="Aceptada concurrentemente",
    )


def _confirmed(
    owner: User,
    organization_id: UUID,
    *,
    phone: str,
    starts_at: datetime,
    space_id: UUID,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request, quotation = _quote(
        owner,
        organization_id,
        phone=phone,
        starts_at=starts_at,
        space_id=space_id,
    )
    hold = _accept(owner, organization_id, quotation)
    confirmed = confirm_reservation(
        owner,
        organization_id,
        reservation_id=hold["id"],
        kind="external_deposit",
        recognized_amount=Decimal("100.00"),
        reported_at=timezone.now(),
        reference="Depósito concurrente",
    )
    return request, confirmed


def _local(value: datetime) -> datetime:
    return value.astimezone(LOCAL_ZONE).replace(tzinfo=None)


def _ready(owner: User, organization_id: UUID, reservation_id: UUID) -> dict[str, Any]:
    detail = read_event(owner, organization_id, reservation_id=reservation_id)
    with authorized_tenant_scope(owner, organization_id, Capability.OPERATION_MANAGE):
        membership_id = Membership.objects.get(
            organization_id=organization_id,
            user_id=owner.pk,
            status=Membership.Status.ACTIVE,
        ).pk
    assign_preparation(
        owner,
        organization_id,
        reservation_id=reservation_id,
        revision=detail["preparation"]["revision"],
        responsible_membership_id=membership_id,
    )
    detail = read_event(owner, organization_id, reservation_id=reservation_id)
    preparation_revision = detail["preparation"]["revision"]
    for item in detail["preparation"]["items"]:
        changed = update_item(
            owner,
            organization_id,
            reservation_id=reservation_id,
            item_id=item["id"],
            revision=item["revision"],
            values={"status": "completed"},
        )
        preparation_revision = changed["preparation_revision"]
    return mark_ready(
        owner,
        organization_id,
        reservation_id=reservation_id,
        revision=preparation_revision,
    )


def _parallel(*commands: Any) -> list[tuple[str, Any]]:
    barrier = Barrier(len(commands))

    def run(command: Any) -> tuple[str, Any]:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return "ok", command()
        except (CommercialError, SchedulingError, OperationsError, IntegrityError) as error:
            return "error", getattr(error, "code", error.__class__.__name__)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
        futures = [pool.submit(run, command) for command in commands]
        return [future.result(timeout=30) for future in futures]


def _block_command(
    owner: User,
    organization_id: UUID,
    venue_id: UUID,
    spaces: tuple[UUID, ...],
    start: datetime,
) -> Any:
    return lambda: create_block(
        owner,
        organization_id,
        idempotency_key=uuid4(),
        scope=ScheduleBlock.Scope.SPACES,
        venue_id=venue_id,
        space_ids=spaces,
        starts_at_local=_local(start),
        ends_at_local=_local(start + timedelta(hours=4)),
        timezone_name="America/Guayaquil",
        reason="Bloqueo concurrente",
    )


def test_c01_hold_vs_hold_and_c02_different_spaces() -> None:
    owner, organization_id = _owner("c01-c02")
    first_space, second_space = _space_ids(owner, organization_id, 2)
    start = timezone.now() + timedelta(days=30)
    _, first_quote = _quote(
        owner, organization_id, phone="0991000001", starts_at=start, space_id=first_space
    )
    _, overlap_quote = _quote(
        owner, organization_id, phone="0991000002", starts_at=start, space_id=first_space
    )
    overlap = _parallel(
        lambda: _accept(owner, organization_id, first_quote),
        lambda: _accept(owner, organization_id, overlap_quote),
    )
    assert [status for status, _ in overlap].count("ok") == 1
    assert {value for status, value in overlap if status == "error"} == {"schedule_conflict"}

    other_start = start + timedelta(days=2)
    _, quote_a = _quote(
        owner, organization_id, phone="0991000003", starts_at=other_start, space_id=first_space
    )
    _, quote_b = _quote(
        owner, organization_id, phone="0991000004", starts_at=other_start, space_id=second_space
    )
    different = _parallel(
        lambda: _accept(owner, organization_id, quote_a),
        lambda: _accept(owner, organization_id, quote_b),
    )
    assert [status for status, _ in different] == ["ok", "ok"]


def test_c03_hold_vs_block_and_c04_block_vs_block() -> None:
    owner, organization_id = _owner("c03-c04")
    (space_id,) = _space_ids(owner, organization_id)
    venue_id = UUID(str(list_venues(owner, organization_id)[0]["id"]))
    start = timezone.now() + timedelta(days=34)
    _, quotation = _quote(
        owner, organization_id, phone="0992000001", starts_at=start, space_id=space_id
    )
    hold_block = _parallel(
        lambda: _accept(owner, organization_id, quotation),
        _block_command(owner, organization_id, venue_id, (space_id,), start),
    )
    assert [status for status, _ in hold_block].count("ok") == 1

    block_start = start + timedelta(days=2)
    block_block = _parallel(
        _block_command(owner, organization_id, venue_id, (space_id,), block_start),
        _block_command(owner, organization_id, venue_id, (space_id,), block_start),
    )
    assert [status for status, _ in block_block].count("ok") == 1
    assert {value for status, value in block_block if status == "error"} == {
        "availability_conflict"
    }


def _force_expired(owner: User, organization_id: UUID, reservation_id: UUID) -> None:
    with (
        authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE),
        connection.cursor() as cursor,
    ):
        cursor.execute("ALTER TABLE public.commercial_reservation DISABLE TRIGGER USER")
        cursor.execute(
            "UPDATE public.commercial_reservation SET hold_expires_at = %s "
            "WHERE organization_id = %s AND id = %s",
            [timezone.now() - timedelta(seconds=1), organization_id, reservation_id],
        )
        assert cursor.rowcount == 1
        cursor.execute("ALTER TABLE public.commercial_reservation ENABLE TRIGGER USER")


def test_c05_confirmation_vs_expiration_and_c06_expiration_vs_new_hold() -> None:
    owner, organization_id = _owner("c05-c06")
    (space_id,) = _space_ids(owner, organization_id)
    start = timezone.now() + timedelta(days=38)
    _, quotation = _quote(
        owner, organization_id, phone="0993000001", starts_at=start, space_id=space_id
    )
    hold = _accept(owner, organization_id, quotation)
    _force_expired(owner, organization_id, UUID(str(hold["id"])))
    local_start = _local(start)
    raced = _parallel(
        lambda: confirm_reservation(
            owner,
            organization_id,
            reservation_id=hold["id"],
            kind="external_deposit",
            recognized_amount=Decimal("50.00"),
            reported_at=timezone.now(),
            reference="Límite",
        ),
        lambda: availability(
            owner,
            organization_id,
            starts_at_local=local_start,
            ends_at_local=local_start + timedelta(hours=4),
            timezone_name="America/Guayaquil",
            space_ids=(space_id,),
        ),
    )
    assert any(value == "hold_expired" for status, value in raced if status == "error"), raced
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        assert Reservation.objects.get(pk=hold["id"]).status == Reservation.Status.EXPIRED
        assert (
            ScheduleEvent.objects.filter(
                reservation_id=hold["id"], kind=ScheduleEvent.Kind.RESERVATION_EXPIRED
            ).count()
            == 1
        )

    replacement_start = start + timedelta(days=2)
    _, old_quote = _quote(
        owner,
        organization_id,
        phone="0993000002",
        starts_at=replacement_start,
        space_id=space_id,
    )
    old_hold = _accept(owner, organization_id, old_quote)
    _force_expired(owner, organization_id, UUID(str(old_hold["id"])))
    _, new_quote = _quote(
        owner,
        organization_id,
        phone="0993000003",
        starts_at=replacement_start,
        space_id=space_id,
    )
    replacement = _parallel(
        lambda: availability(
            owner,
            organization_id,
            starts_at_local=_local(replacement_start),
            ends_at_local=_local(replacement_start + timedelta(hours=4)),
            timezone_name="America/Guayaquil",
            space_ids=(space_id,),
        ),
        lambda: _accept(owner, organization_id, new_quote),
    )
    assert [status for status, _ in replacement] == ["ok", "ok"]


def _reschedule_command(
    owner: User,
    organization_id: UUID,
    reservation: dict[str, Any],
    *,
    destination: UUID,
    start: datetime,
    key: UUID | None = None,
) -> Any:
    idempotency_key = key or uuid4()
    return lambda: reschedule_reservation(
        owner,
        organization_id,
        reservation_id=reservation["id"],
        revision=reservation["revision"],
        idempotency_key=idempotency_key,
        space_id=destination,
        starts_at_local=_local(start),
        ends_at_local=_local(start + timedelta(hours=4)),
        timezone_name="America/Guayaquil",
        reason="Reprogramación concurrente",
        commercial_terms_unchanged=True,
    )


def test_c07_two_reschedules_and_c08_idempotent_retries() -> None:
    owner, organization_id = _owner("c07-c08")
    (space_id,) = _space_ids(owner, organization_id)
    start = timezone.now() + timedelta(days=44)
    _, reservation = _confirmed(
        owner,
        organization_id,
        phone="0994000001",
        starts_at=start,
        space_id=space_id,
    )
    target = start + timedelta(days=1)
    different_keys = _parallel(
        _reschedule_command(
            owner, organization_id, reservation, destination=space_id, start=target
        ),
        _reschedule_command(
            owner, organization_id, reservation, destination=space_id, start=target
        ),
    )
    assert [status for status, _ in different_keys].count("ok") == 1

    _, second = _confirmed(
        owner,
        organization_id,
        phone="0994000002",
        starts_at=start + timedelta(days=4),
        space_id=space_id,
    )
    key = uuid4()
    same_key = _parallel(
        _reschedule_command(
            owner,
            organization_id,
            second,
            destination=space_id,
            start=start + timedelta(days=5),
            key=key,
        ),
        _reschedule_command(
            owner,
            organization_id,
            second,
            destination=space_id,
            start=start + timedelta(days=5),
            key=key,
        ),
    )
    assert [status for status, _ in same_key] == ["ok", "ok"]
    assert same_key[0][1]["reservation"]["id"] == same_key[1][1]["reservation"]["id"]


def test_c09_destination_occupancy_and_c10_destination_block() -> None:
    owner, organization_id = _owner("c09-c10")
    source, destination = _space_ids(owner, organization_id, 2)
    venue_id = UUID(str(list_venues(owner, organization_id)[0]["id"]))
    start = timezone.now() + timedelta(days=51)
    _, reservation = _confirmed(
        owner,
        organization_id,
        phone="0995000001",
        starts_at=start,
        space_id=source,
    )
    target = start + timedelta(days=1)
    _, target_quote = _quote(
        owner,
        organization_id,
        phone="0995000002",
        starts_at=target,
        space_id=destination,
    )
    occupied = _parallel(
        _reschedule_command(
            owner, organization_id, reservation, destination=destination, start=target
        ),
        lambda: _accept(owner, organization_id, target_quote),
    )
    assert [status for status, _ in occupied].count("ok") == 1

    _, second = _confirmed(
        owner,
        organization_id,
        phone="0995000003",
        starts_at=start + timedelta(days=4),
        space_id=source,
    )
    blocked_target = start + timedelta(days=5)
    blocked = _parallel(
        _reschedule_command(
            owner, organization_id, second, destination=destination, start=blocked_target
        ),
        _block_command(owner, organization_id, venue_id, (destination,), blocked_target),
    )
    assert [status for status, _ in blocked].count("ok") == 1


def test_c11_reschedule_vs_cancel_and_c12_reschedule_vs_start() -> None:
    owner, organization_id = _owner("c11-c12")
    (space_id,) = _space_ids(owner, organization_id)
    start = timezone.now() + timedelta(days=58)
    _, reservation = _confirmed(
        owner,
        organization_id,
        phone="0996000001",
        starts_at=start,
        space_id=space_id,
    )
    cancel_race = _parallel(
        _reschedule_command(
            owner,
            organization_id,
            reservation,
            destination=space_id,
            start=start + timedelta(days=1),
        ),
        lambda: cancel_reservation(
            owner,
            organization_id,
            reservation_id=reservation["id"],
            reason="Cancelación concurrente",
        ),
    )
    assert [status for status, _ in cancel_race].count("ok") == 1

    _, second = _confirmed(
        owner,
        organization_id,
        phone="0996000002",
        starts_at=start + timedelta(days=4),
        space_id=space_id,
    )
    ready = _ready(owner, organization_id, UUID(str(second["id"])))
    start_race = _parallel(
        _reschedule_command(
            owner,
            organization_id,
            second,
            destination=space_id,
            start=start + timedelta(days=5),
        ),
        lambda: start_event(
            owner,
            organization_id,
            reservation_id=second["id"],
            revision=ready["preparation"]["revision"],
        ),
    )
    assert [status for status, _ in start_race].count("ok") == 1


def test_c13_swap_and_c14_inverse_multi_space_lock_order() -> None:
    owner, organization_id = _owner("c13-c14")
    first_space, second_space = _space_ids(owner, organization_id, 2)
    venue_id = UUID(str(list_venues(owner, organization_id)[0]["id"]))
    first_start = timezone.now() + timedelta(days=65)
    second_start = first_start + timedelta(days=1)
    _, first = _confirmed(
        owner,
        organization_id,
        phone="0997000001",
        starts_at=first_start,
        space_id=first_space,
    )
    _, second = _confirmed(
        owner,
        organization_id,
        phone="0997000002",
        starts_at=second_start,
        space_id=second_space,
    )
    swap = _parallel(
        _reschedule_command(
            owner,
            organization_id,
            first,
            destination=second_space,
            start=second_start,
        ),
        _reschedule_command(
            owner,
            organization_id,
            second,
            destination=first_space,
            start=first_start,
        ),
    )
    assert [status for status, _ in swap] == ["error", "error"]

    block_start = first_start + timedelta(days=4)
    inverse = _parallel(
        _block_command(owner, organization_id, venue_id, (first_space, second_space), block_start),
        _block_command(owner, organization_id, venue_id, (second_space, first_space), block_start),
    )
    assert [status for status, _ in inverse].count("ok") == 1


def test_c15_venue_closure_vs_space_creation_and_c16_policy_vs_hold() -> None:
    owner, organization_id = _owner("c15-c16")
    (space_id,) = _space_ids(owner, organization_id)
    venue_id = UUID(str(list_venues(owner, organization_id)[0]["id"]))
    start = timezone.now() + timedelta(days=72)

    def closure() -> Any:
        return create_block(
            owner,
            organization_id,
            idempotency_key=uuid4(),
            scope=ScheduleBlock.Scope.VENUE,
            venue_id=venue_id,
            space_ids=(),
            starts_at_local=_local(start),
            ends_at_local=_local(start + timedelta(hours=4)),
            timezone_name="America/Guayaquil",
            reason="Cierre total concurrente",
        )

    def space_creation() -> Any:
        return create_space(
            owner,
            organization_id,
            venue_id=venue_id,
            name=f"Espacio simultáneo {uuid4()}",
        )

    results = _parallel(closure, space_creation)
    assert [status for status, _ in results] == ["ok", "ok"]
    with authorized_tenant_scope(owner, organization_id, Capability.AVAILABILITY_READ):
        block = ScheduleBlock.objects.get(scope=ScheduleBlock.Scope.VENUE)
        assert block.targets.count() == 2
        assert block.targets.filter(allocation__is_blocking=True).count() == 2

    policy_start = start + timedelta(days=3)
    _, quotation = _quote(
        owner,
        organization_id,
        phone="0998000001",
        starts_at=policy_start,
        space_id=space_id,
    )
    policy_hold = _parallel(
        lambda: update_policy(
            owner,
            organization_id,
            space_id=space_id,
            revision=0,
            setup_minutes=20,
            teardown_minutes=30,
            buffer_before_minutes=10,
            buffer_after_minutes=5,
        ),
        lambda: _accept(owner, organization_id, quotation),
    )
    assert [status for status, _ in policy_hold] == ["ok", "ok"]
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        row = Reservation.objects.get(quotation_version__quotation_id=quotation["id"])
        assert (
            row.setup_minutes,
            row.teardown_minutes,
            row.buffer_before_minutes,
            row.buffer_after_minutes,
        ) in {(0, 0, 0, 0), (20, 30, 10, 5)}


def test_c17_sql_and_bulk_divergence_and_c18_equivalent_tenants() -> None:
    owner, organization_id = _owner("c17")
    (space_id,) = _space_ids(owner, organization_id)
    start = timezone.now() + timedelta(days=80)
    _, quotation = _quote(
        owner, organization_id, phone="0999000001", starts_at=start, space_id=space_id
    )
    hold = _accept(owner, organization_id, quotation)
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE):
        with pytest.raises(IntegrityError), transaction.atomic():
            ScheduleAllocation.objects.filter(reservation_id=hold["id"]).update(is_blocking=False)
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with pytest.raises(IntegrityError), transaction.atomic():
            ScheduleEvent.objects.filter(reservation_id=hold["id"]).update(reason="alterada")
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        assert ScheduleAllocation.objects.get(reservation_id=hold["id"]).is_blocking is True

    other_owner, other_organization = _owner("c18")
    (other_space,) = _space_ids(other_owner, other_organization)
    shared_start = start + timedelta(days=2)
    _, first_quote = _quote(
        owner,
        organization_id,
        phone="0999000002",
        starts_at=shared_start,
        space_id=space_id,
    )
    _, second_quote = _quote(
        other_owner,
        other_organization,
        phone="0999000003",
        starts_at=shared_start,
        space_id=other_space,
    )
    tenant_results = _parallel(
        lambda: _accept(owner, organization_id, first_quote),
        lambda: _accept(other_owner, other_organization, second_quote),
    )
    assert [status for status, _ in tenant_results] == ["ok", "ok"]


def test_p8_rls_force_privileges_and_helper_function_boundaries() -> None:
    owner, organization_id = _owner("rls-first")
    other_owner, other_id = _owner("rls-second")
    (space_id,) = _space_ids(owner, organization_id)
    start = timezone.now() + timedelta(days=86)
    _, quotation = _quote(
        owner, organization_id, phone="0999100001", starts_at=start, space_id=space_id
    )
    hold = _accept(owner, organization_id, quotation)

    assert ScheduleEvent.objects.count() == 0
    assert ScheduleAllocation.objects.count() == 0
    with authorized_tenant_scope(other_owner, other_id, Capability.AVAILABILITY_READ):
        assert ScheduleEvent.objects.count() == 0
        assert ScheduleAllocation.objects.count() == 0
    with authorized_tenant_scope(owner, organization_id, Capability.AVAILABILITY_READ):
        assert ScheduleEvent.objects.filter(reservation_id=hold["id"]).count() == 1
        assert ScheduleAllocation.objects.filter(reservation_id=hold["id"]).count() == 1

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = ANY(%s)
            ORDER BY relname
            """,
            [list(P8_TABLES)],
        )
        metadata = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                has_table_privilege('claridez_app',
                    'scheduling_scheduleevent', 'SELECT,INSERT'),
                has_table_privilege('claridez_app',
                    'scheduling_scheduleevent', 'UPDATE'),
                has_table_privilege('claridez_app',
                    'scheduling_scheduleevent', 'DELETE'),
                has_table_privilege('claridez_app',
                    'scheduling_scheduleallocation', 'SELECT,INSERT,UPDATE'),
                has_table_privilege('claridez_app',
                    'scheduling_scheduleallocation', 'DELETE'),
                has_table_privilege('claridez_migrator',
                    'scheduling_scheduleevent', 'SELECT,INSERT,UPDATE,DELETE'),
                has_table_privilege('claridez_test_runner',
                    'scheduling_scheduleevent', 'SELECT,INSERT,UPDATE,DELETE'),
                has_function_privilege('public',
                    'claridez_scheduling_expire_for_space(uuid,uuid)', 'EXECUTE')
            """
        )
        privileges = cursor.fetchone()
        cursor.execute(
            """
            SELECT p.prosecdef, p.proconfig
            FROM pg_proc AS p
            JOIN pg_namespace AS n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
              AND p.proname = 'claridez_scheduling_expire_for_space'
            """
        )
        helper = cursor.fetchone()
    assert metadata == sorted((table, True, True) for table in P8_TABLES)
    assert privileges == (True, False, False, True, False, True, True, False)
    assert helper == (False, ["search_path=pg_catalog, public"])
