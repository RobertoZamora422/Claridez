from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone

from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.models import EventRequest
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
from claridez.crm.services import create_task, list_tasks, person_overview
from claridez.identity.models import User
from claridez.operations.models import EventPreparation, PreparationItem
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
    calendar_entries,
    create_block,
    export_icalendar,
    reschedule_reservation,
    schedule_history,
    terminate_block,
    update_policy,
)
from claridez.scheduling.temporal import calendar_bounds, local_interval

PASSWORD = "correct-horse-battery-staple-p8"


def _owner(slug: str) -> tuple[User, UUID]:
    owner = User.objects.create_user(
        email=f"{slug}@example.test",
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    creation = create_organization(owner_user_id=owner.pk, name=f"Agenda {slug}")
    return owner, creation.organization.pk


def _commercial_hold(
    owner: User,
    organization_id: UUID,
    *,
    phone: str = "0991234567",
    starts_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    venues = list_venues(owner, organization_id)
    space_id = venues[0]["spaces"][0]["id"]
    event_type = next(iter(list_event_types(owner, organization_id)), None)
    if event_type is None:
        event_type = create_event_type(owner, organization_id, name="Boda")
    person = create_person(
        owner,
        organization_id,
        full_name="Persona de agenda",
        phone=phone,
        email=f"agenda-{phone}@example.test",
        origin="whatsapp",
        origin_detail=None,
    )
    start = starts_at or (timezone.now() + timedelta(days=20))
    request = create_event_request(
        owner,
        organization_id,
        person_id=person["id"],
        event_type_id=event_type["id"],
        space_id=space_id,
        starts_at=start,
        ends_at=start + timedelta(hours=4),
        estimated_guests=80,
        general_need="Evento con agenda avanzada",
        notes="",
        origin="whatsapp",
        origin_detail=None,
    )
    quotation = create_quotation(
        owner,
        organization_id,
        request_id=request["id"],
        valid_until=timezone.now() + timedelta(days=4),
    )
    draft = quotation["versions"][0]
    replace_quotation_draft(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=draft["revision"],
        valid_until=timezone.now() + timedelta(days=4),
        notes="Condiciones originales",
        lines=[
            {
                "description": "Servicio aceptado",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("900.00"),
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
    hold = accept_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        channel="whatsapp",
        note="Aceptada",
    )
    return request, hold


def _force_hold_expired(owner: User, organization_id: UUID, reservation_id: UUID | str) -> None:
    """Simulate elapsed wall-clock time without changing domain code."""

    with (
        authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE),
        connection.cursor() as cursor,
    ):
        cursor.execute("ALTER TABLE public.commercial_reservation DISABLE TRIGGER USER")
        try:
            cursor.execute(
                "UPDATE public.commercial_reservation SET hold_expires_at = %s "
                "WHERE organization_id = %s AND id = %s",
                [timezone.now() - timedelta(seconds=1), organization_id, reservation_id],
            )
            assert cursor.rowcount == 1
        finally:
            cursor.execute("ALTER TABLE public.commercial_reservation ENABLE TRIGGER USER")


def test_local_time_contract_and_calendar_boundaries() -> None:
    crossing = local_interval(
        datetime(2026, 8, 15, 22, 0),
        datetime(2026, 8, 16, 2, 0),
        "America/Guayaquil",
    )
    assert crossing.ends_at - crossing.starts_at == timedelta(hours=4)

    with pytest.raises(SchedulingError) as ambiguous:
        local_interval(
            datetime(2026, 11, 1, 1, 15),
            datetime(2026, 11, 1, 2, 15),
            "America/New_York",
        )
    assert ambiguous.value.code == "ambiguous_local_time"

    with pytest.raises(SchedulingError) as nonexistent:
        local_interval(
            datetime(2026, 3, 8, 2, 15),
            datetime(2026, 3, 8, 4, 15),
            "America/New_York",
        )
    assert nonexistent.value.code == "nonexistent_local_time"

    start, end = calendar_bounds("month", datetime(2026, 8, 15).date(), "America/Guayaquil")
    assert start == datetime(2026, 8, 1, 5, 0, tzinfo=UTC)
    assert end == datetime(2026, 9, 1, 5, 0, tzinfo=UTC)


@pytest.mark.django_db
def test_policy_snapshot_block_calendar_and_icalendar() -> None:
    owner, organization_id = _owner("policy")
    venues = list_venues(owner, organization_id)
    venue_id = UUID(str(venues[0]["id"]))
    space_id = UUID(str(venues[0]["spaces"][0]["id"]))
    policy = update_policy(
        owner,
        organization_id,
        space_id=space_id,
        revision=0,
        setup_minutes=30,
        teardown_minutes=20,
        buffer_before_minutes=15,
        buffer_after_minutes=10,
    )
    assert policy["revision"] == 1
    request, hold = _commercial_hold(owner, organization_id)
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        reservation = Reservation.objects.get(pk=hold["id"])
        allocation = ScheduleAllocation.objects.get(reservation_id=reservation.pk)
        assert allocation.occupied_interval.lower == reservation.event_interval.lower - timedelta(
            minutes=45
        )
        assert allocation.occupied_interval.upper == reservation.event_interval.upper + timedelta(
            minutes=30
        )
        assert ScheduleEvent.objects.get(
            reservation_id=reservation.pk,
            kind=ScheduleEvent.Kind.RESERVATION_HOLD_CREATED,
        )

    second_space = create_space(
        owner,
        organization_id,
        venue_id=venue_id,
        name="Espacio alterno",
    )
    key = uuid4()
    block, created = create_block(
        owner,
        organization_id,
        idempotency_key=key,
        scope=ScheduleBlock.Scope.SPACES,
        venue_id=venue_id,
        space_ids=(UUID(str(second_space["id"])),),
        starts_at_local=datetime(2026, 9, 10, 9, 0),
        ends_at_local=datetime(2026, 9, 10, 12, 0),
        timezone_name="America/Guayaquil",
        reason="Mantenimiento preventivo",
    )
    assert created is True
    replay, replay_created = create_block(
        owner,
        organization_id,
        idempotency_key=key,
        scope=ScheduleBlock.Scope.SPACES,
        venue_id=venue_id,
        space_ids=(UUID(str(second_space["id"])),),
        starts_at_local=datetime(2026, 9, 10, 9, 0),
        ends_at_local=datetime(2026, 9, 10, 12, 0),
        timezone_name="America/Guayaquil",
        reason="Mantenimiento preventivo",
    )
    assert replay_created is False and replay["id"] == block["id"]
    availability_result = availability(
        owner,
        organization_id,
        space_ids=(UUID(str(second_space["id"])),),
        starts_at_local=datetime(2026, 9, 10, 10, 0),
        ends_at_local=datetime(2026, 9, 10, 11, 0),
        timezone_name="America/Guayaquil",
    )
    assert availability_result["spaces"][0]["available"] is False
    terminated = terminate_block(
        owner,
        organization_id,
        block_id=UUID(str(block["id"])),
        revision=1,
        reason="Mantenimiento terminado",
        action="release",
    )
    assert terminated["status"] == "released"

    agenda = calendar_entries(
        owner,
        organization_id,
        view="month",
        anchor_date=request["starts_at"].date(),
    )
    assert any(entry["id"] == hold["id"] for entry in agenda["entries"])
    ical = export_icalendar(
        owner,
        organization_id,
        view="month",
        anchor_date=request["starts_at"].date(),
    )
    assert "BEGIN:VCALENDAR" in ical and str(hold["id"]) in ical


@pytest.mark.django_db
def test_confirmed_reschedule_is_atomic_idempotent_and_preserves_evidence() -> None:
    owner, organization_id = _owner("reschedule")
    request, hold = _commercial_hold(owner, organization_id, phone="0992223344")
    confirmed = confirm_reservation(
        owner,
        organization_id,
        reservation_id=hold["id"],
        kind="external_deposit",
        recognized_amount=Decimal("200.00"),
        reported_at=timezone.now(),
        reference="Transferencia original",
    )
    due_at = timezone.now() + timedelta(days=2)
    task = create_task(
        owner,
        organization_id,
        person_id=request["person"]["id"],
        event_request_id=request["id"],
        title="Revisar detalles con cliente",
        due_at=due_at,
        next_contact_at=due_at - timedelta(hours=2),
    )
    key = uuid4()
    command = {
        "reservation_id": confirmed["id"],
        "revision": confirmed["revision"],
        "idempotency_key": key,
        "space_id": UUID(str(confirmed["space_id"])),
        "starts_at_local": datetime(2026, 10, 8, 18, 0),
        "ends_at_local": datetime(2026, 10, 8, 23, 0),
        "timezone_name": "America/Guayaquil",
        "reason": "Cambio solicitado por cliente",
        "commercial_terms_unchanged": True,
    }
    result = reschedule_reservation(owner, organization_id, **command)
    replay = reschedule_reservation(owner, organization_id, **command)
    assert replay["reservation"]["id"] == result["reservation"]["id"]

    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        previous = Reservation.objects.get(pk=confirmed["id"])
        successor = Reservation.objects.get(pk=result["reservation"]["id"])
        assert previous.status == Reservation.Status.RESCHEDULED
        assert successor.predecessor_id == previous.pk
        assert successor.root_id == previous.root_id
        assert successor.event_request_id == previous.event_request_id == request["id"]
        assert successor.quotation_version_id == previous.quotation_version_id
        assert successor.confirmation_source_id == previous.pk
        old_preparation = EventPreparation.objects.get(reservation_id=previous.pk)
        new_preparation = EventPreparation.objects.get(reservation_id=successor.pk)
        assert old_preparation.status == EventPreparation.Status.RESCHEDULED
        assert old_preparation.rescheduled_to_reservation_id == successor.pk
        assert new_preparation.status == EventPreparation.Status.PREPARING
        assert (
            PreparationItem.objects.filter(
                preparation_id=successor.pk,
                baseline_key__isnull=False,
                status=PreparationItem.Status.PENDING,
            ).count()
            == 7
        )
        assert (
            ScheduleEvent.objects.filter(
                root_reservation_id=previous.root_id,
                kind=ScheduleEvent.Kind.RESERVATION_RESCHEDULED,
            ).count()
            == 1
        )
        assert ScheduleAllocation.objects.get(reservation_id=previous.pk).is_blocking is False
        assert ScheduleAllocation.objects.get(reservation_id=successor.pk).is_blocking is True

    changed = {**command, "reason": "Payload diferente"}
    with pytest.raises(SchedulingError) as conflict:
        reschedule_reservation(owner, organization_id, **changed)
    assert conflict.value.code == "idempotency_conflict"
    history = schedule_history(
        owner,
        organization_id,
        reservation_id=UUID(str(result["reservation"]["id"])),
    )
    assert [event["kind"] for event in history][-1] == "reservation_rescheduled"
    derived = list_tasks(
        owner,
        organization_id,
        event_request_id=request["id"],
    )[0]
    assert derived["requires_schedule_review"] is True
    assert derived["revision"] == task["revision"]
    assert derived["due_at"] == task["due_at"]
    assert derived["next_contact_at"] == task["next_contact_at"]
    overview = person_overview(
        owner,
        organization_id,
        person_id=request["person"]["id"],
    )
    assert any(item["type"] == "schedule" for item in overview["timeline"])

    cancelled = cancel_reservation(
        owner,
        organization_id,
        reservation_id=result["reservation"]["id"],
        reason="Cancelación posterior a reprogramación",
    )
    assert cancelled["status"] == Reservation.Status.CANCELLED
    replayed_cancel = cancel_reservation(
        owner,
        organization_id,
        reservation_id=result["reservation"]["id"],
        reason="Cancelación posterior a reprogramación",
    )
    assert replayed_cancel["revision"] == cancelled["revision"]
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        assert Reservation.objects.get(pk=confirmed["id"]).status == Reservation.Status.RESCHEDULED
        assert (
            ScheduleAllocation.objects.get(reservation_id=result["reservation"]["id"]).is_blocking
            is False
        )
        assert (
            EventPreparation.objects.get(reservation_id=result["reservation"]["id"]).status
            == EventPreparation.Status.CANCELLED
        )
        assert (
            ScheduleEvent.objects.filter(
                reservation_id=result["reservation"]["id"],
                kind=ScheduleEvent.Kind.RESERVATION_CANCELLED,
            ).count()
            == 1
        )


@pytest.mark.django_db
def test_provisional_reschedule_preserves_hold_and_never_creates_preparation() -> None:
    owner, organization_id = _owner("provisional-reschedule")
    request, hold = _commercial_hold(owner, organization_id, phone="0992233445")
    venue = list_venues(owner, organization_id)[0]
    destination = create_space(
        owner,
        organization_id,
        venue_id=venue["id"],
        name="Espacio sucesor provisional",
    )
    original_expiration = hold["hold_expires_at"]
    key = uuid4()
    command = {
        "reservation_id": hold["id"],
        "revision": hold["revision"],
        "idempotency_key": key,
        "space_id": UUID(str(destination["id"])),
        "starts_at_local": datetime(2026, 10, 18, 18, 0),
        "ends_at_local": datetime(2026, 10, 18, 23, 0),
        "timezone_name": "America/Guayaquil",
        "reason": "Nueva fecha antes de confirmar",
        "commercial_terms_unchanged": True,
    }

    result = reschedule_reservation(owner, organization_id, **command)
    replay = reschedule_reservation(owner, organization_id, **command)
    assert replay["reservation"]["id"] == result["reservation"]["id"]

    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        predecessor = Reservation.objects.get(pk=hold["id"])
        successor = Reservation.objects.get(pk=result["reservation"]["id"])
        assert predecessor.status == Reservation.Status.RESCHEDULED
        assert successor.status == Reservation.Status.PROVISIONAL
        assert successor.root_id == predecessor.root_id
        assert successor.event_request_id == predecessor.event_request_id
        assert successor.event_request_id == UUID(str(request["id"]))
        assert successor.quotation_version_id == predecessor.quotation_version_id
        assert successor.predecessor_id == predecessor.pk
        assert successor.confirmation_source_id is None
        assert successor.hold_expires_at == predecessor.hold_expires_at == original_expiration
        assert not EventPreparation.objects.filter(
            reservation_id__in=(predecessor.pk, successor.pk)
        ).exists()
        assert ScheduleAllocation.objects.get(reservation_id=predecessor.pk).is_blocking is False
        assert ScheduleAllocation.objects.get(reservation_id=successor.pk).is_blocking is True
        assert (
            ScheduleEvent.objects.filter(
                root_reservation_id=predecessor.root_id,
                kind=ScheduleEvent.Kind.RESERVATION_RESCHEDULED,
            ).count()
            == 1
        )
        assert Reservation.objects.filter(predecessor_id=predecessor.pk).count() == 1
        assert EventRequest.objects.get(pk=request["id"]).status == EventRequest.Status.ACCEPTED

    with pytest.raises(SchedulingError) as idempotency_conflict:
        reschedule_reservation(
            owner,
            organization_id,
            **{**command, "reason": "Otra razón con la misma clave"},
        )
    assert idempotency_conflict.value.code == "idempotency_conflict"


@pytest.mark.django_db(transaction=True)
def test_expired_provisional_cannot_be_rescheduled_and_leaves_no_partial_state() -> None:
    owner, organization_id = _owner("expired-provisional-reschedule")
    request, hold = _commercial_hold(owner, organization_id, phone="0992233446")
    _force_hold_expired(owner, organization_id, hold["id"])

    with pytest.raises(SchedulingError) as expired:
        reschedule_reservation(
            owner,
            organization_id,
            reservation_id=hold["id"],
            revision=hold["revision"],
            idempotency_key=uuid4(),
            space_id=UUID(str(hold["space_id"])),
            starts_at_local=datetime(2026, 10, 28, 18, 0),
            ends_at_local=datetime(2026, 10, 28, 23, 0),
            timezone_name="America/Guayaquil",
            reason="Intento después del vencimiento",
            commercial_terms_unchanged=True,
        )
    assert expired.value.code == "hold_expired"

    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        predecessor = Reservation.objects.get(pk=hold["id"])
        assert predecessor.status == Reservation.Status.EXPIRED
        assert not Reservation.objects.filter(predecessor_id=predecessor.pk).exists()
        assert not ScheduleEvent.objects.filter(
            predecessor_id=predecessor.pk,
            kind=ScheduleEvent.Kind.RESERVATION_RESCHEDULED,
        ).exists()
        assert ScheduleAllocation.objects.get(reservation_id=predecessor.pk).is_blocking is False
        assert not EventPreparation.objects.filter(reservation_id=predecessor.pk).exists()
        assert EventRequest.objects.get(pk=request["id"]).status == EventRequest.Status.QUOTED


def _authenticated_client(user: User) -> tuple[Client, str]:
    client = Client(enforce_csrf_checks=True)
    login_token = str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])
    response = client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": user.email, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=login_token,
    )
    assert response.status_code == 200
    return client, str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])


@pytest.mark.django_db
def test_scheduling_http_session_csrf_membership_tenant_and_conjunctive_capabilities() -> None:
    owner, organization_id = _owner("http")
    venue = list_venues(owner, organization_id)[0]
    venue_id = str(venue["id"])
    space_id = str(venue["spaces"][0]["id"])
    calendar_path = f"/api/v1/organizations/{organization_id}/scheduling/calendar/"
    calendar_query = {"view": "month", "anchor_date": "2026-11-15"}

    anonymous = Client(enforce_csrf_checks=True)
    assert anonymous.get(calendar_path, calendar_query).status_code == 401

    client, token = _authenticated_client(owner)
    calendar_response = client.get(calendar_path, calendar_query)
    assert calendar_response.status_code == 200
    assert calendar_response.json()["view"] == "month"
    capabilities = client.get(f"/api/v1/organizations/{organization_id}/scheduling/capabilities/")
    assert capabilities.status_code == 200
    assert "schedule:block" in capabilities.json()["capabilities"]

    block_path = f"/api/v1/organizations/{organization_id}/scheduling/blocks/"
    payload = {
        "idempotency_key": str(uuid4()),
        "scope": "spaces",
        "venue_id": venue_id,
        "space_ids": [space_id],
        "starts_at_local": "2026-11-20T09:00",
        "ends_at_local": "2026-11-20T12:00",
        "timezone": "America/Guayaquil",
        "reason": "Mantenimiento HTTP",
    }
    assert (
        client.post(
            block_path, data=json.dumps(payload), content_type="application/json"
        ).status_code
        == 403
    )
    created = client.post(
        block_path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert created.status_code == 201
    replay = client.post(
        block_path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == created.json()["id"]

    foreign_owner, foreign_id = _owner("http-foreign")
    assert foreign_owner.pk != owner.pk
    foreign_path = f"/api/v1/organizations/{foreign_id}/scheduling/calendar/"
    assert client.get(foreign_path, calendar_query).status_code == 404

    commercial = User.objects.create_user(
        email="p8-http-commercial@example.test",
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    Membership.objects.create(
        organization_id=organization_id,
        user=commercial,
        role=Membership.Role.COMMERCIAL,
        status=Membership.Status.ACTIVE,
        joined_at=timezone.now(),
    )
    commercial_client, commercial_token = _authenticated_client(commercial)
    forbidden = commercial_client.post(
        block_path,
        data=json.dumps({**payload, "idempotency_key": str(uuid4())}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=commercial_token,
    )
    assert forbidden.status_code == 403

    membership = Membership.objects.get(organization_id=organization_id, user=owner)
    membership.status = Membership.Status.SUSPENDED
    membership.suspended_at = timezone.now()
    membership.save(update_fields=["status", "suspended_at", "updated_at"])
    assert client.get(calendar_path, calendar_query).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_reschedule_http_accepts_current_provisional_and_reports_expired_hold() -> None:
    owner, organization_id = _owner("http-provisional-reschedule")
    request, hold = _commercial_hold(owner, organization_id, phone="0992233447")
    venue = list_venues(owner, organization_id)[0]
    destination = create_space(
        owner,
        organization_id,
        venue_id=venue["id"],
        name="Destino HTTP provisional",
    )
    client, token = _authenticated_client(owner)
    path = f"/api/v1/organizations/{organization_id}/reservations/{hold['id']}/reschedule/"
    key = uuid4()
    payload = {
        "revision": hold["revision"],
        "idempotency_key": str(key),
        "space_id": str(destination["id"]),
        "starts_at_local": "2026-11-10T18:00",
        "ends_at_local": "2026-11-10T23:00",
        "timezone": "America/Guayaquil",
        "reason": "Cambio provisional por API",
        "commercial_terms_unchanged": True,
    }
    assert (
        client.post(path, data=json.dumps(payload), content_type="application/json").status_code
        == 403
    )
    response = client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reservation"]["status"] == Reservation.Status.PROVISIONAL
    assert body["reservation"]["predecessor_id"] == str(hold["id"])
    assert body["reservation"]["hold_expires_at"] == hold["hold_expires_at"].isoformat().replace(
        "+00:00", "Z"
    )
    replay = client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert replay.status_code == 200
    assert replay.json()["reservation"]["id"] == body["reservation"]["id"]
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        assert EventRequest.objects.get(pk=request["id"]).status == EventRequest.Status.ACCEPTED

    expired_request, expired_hold = _commercial_hold(
        owner,
        organization_id,
        phone="0992233448",
        starts_at=timezone.now() + timedelta(days=45),
    )
    _force_hold_expired(owner, organization_id, expired_hold["id"])
    expired_path = (
        f"/api/v1/organizations/{organization_id}/reservations/{expired_hold['id']}/reschedule/"
    )
    expired_payload = {
        **payload,
        "revision": expired_hold["revision"],
        "idempotency_key": str(uuid4()),
        "space_id": str(expired_hold["space_id"]),
        "starts_at_local": "2026-12-12T18:00",
        "ends_at_local": "2026-12-12T23:00",
    }
    expired_response = client.post(
        expired_path,
        data=json.dumps(expired_payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert expired_response.status_code == 409
    assert expired_response.json()["error"]["code"] == "hold_expired"
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        expired_row = Reservation.objects.get(pk=expired_hold["id"])
        assert expired_row.status == Reservation.Status.EXPIRED
        assert not Reservation.objects.filter(predecessor_id=expired_row.pk).exists()
        assert ScheduleAllocation.objects.get(reservation_id=expired_row.pk).is_blocking is False
        assert not ScheduleEvent.objects.filter(
            predecessor_id=expired_row.pk,
            kind=ScheduleEvent.Kind.RESERVATION_RESCHEDULED,
        ).exists()
        assert (
            EventRequest.objects.get(pk=expired_request["id"]).status == EventRequest.Status.QUOTED
        )
