from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.errors import CommercialError
from claridez.commercial.models import EventRequest, QuotationVersion, Reservation
from claridez.commercial.normalization import canonical_phone, money
from claridez.commercial.services import (
    accept_quotation_version,
    cancel_reservation,
    close_event_request,
    confirm_reservation,
    create_event_request,
    create_person,
    create_quotation,
    issue_quotation_version,
    list_availability,
    read_person,
    read_reservation,
    replace_quotation_draft,
    update_person,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.models import Membership
from claridez.organizations.services import (
    OrganizationCreation,
    add_membership,
    create_organization,
)
from claridez.organizations.tenant_scope import authorized_tenant_scope

PASSWORD = "correct-horse-battery-staple-commercial-42"


def _user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _owner(slug: str) -> tuple[User, OrganizationCreation]:
    owner = _user(f"{slug}@example.com")
    creation = create_organization(owner_user_id=owner.pk, name=f"Organización {slug}")
    return owner, creation


def _person(owner: User, organization_id: UUID, phone: str = "0991234567") -> dict[str, Any]:
    return create_person(
        owner,
        organization_id,
        full_name="María Pérez",
        phone=phone,
        email=f"maria-{phone}@example.com",
        origin="whatsapp",
        origin_detail=None,
    )


def _p6_refs(owner: User, organization_id: UUID, name: str) -> tuple[Any, Any]:
    event_type = next(
        (row for row in list_event_types(owner, organization_id) if row["name"] == name),
        None,
    )
    if event_type is None:
        event_type = create_event_type(owner, organization_id, name=name)
    return event_type["id"], list_venues(owner, organization_id)[0]["spaces"][0]["id"]


def _request(
    owner: User,
    organization_id: UUID,
    person_id: UUID | str,
    *,
    start_offset: timedelta = timedelta(days=10),
) -> dict[str, Any]:
    start = timezone.now() + start_offset
    event_type_id, space_id = _p6_refs(owner, organization_id, "Boda")
    return create_event_request(
        owner,
        organization_id,
        person_id=person_id,
        event_type_id=event_type_id,
        space_id=space_id,
        starts_at=start,
        ends_at=start + timedelta(hours=5),
        estimated_guests=120,
        general_need="Recepción completa",
        notes="Sin impuestos en 5.1",
        origin="referral",
        origin_detail="Cliente anterior",
    )


def _accepted(
    owner: User,
    organization_id: UUID,
    request_id: UUID | str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    quotation = create_quotation(
        owner,
        organization_id,
        request_id=request_id,
        valid_until=timezone.now() + timedelta(days=3),
    )
    version = quotation["versions"][0]
    quotation = replace_quotation_draft(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=version["revision"],
        valid_until=timezone.now() + timedelta(days=3),
        notes="Propuesta comercial",
        lines=[
            {
                "description": "Alquiler del salón",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("1000.00"),
                "discount_amount": Decimal("50.00"),
            },
            {
                "description": "Servicio por invitado",
                "unit_label": "persona",
                "quantity": Decimal("120.000"),
                "unit_price": Decimal("5.555"),
                "discount_amount": Decimal("0.00"),
            },
        ],
    )
    issue_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
    )
    reservation = accept_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        channel="whatsapp",
        note="Aceptada por el cliente",
    )
    return quotation, reservation


def test_phone_and_money_normalization() -> None:
    assert canonical_phone("099 123-4567") == "+593991234567"
    assert canonical_phone("+593 2 234 5678") == "+59322345678"
    assert money(Decimal("1.005")) == Decimal("1.01")
    with pytest.raises(ValueError):
        canonical_phone("123")


@pytest.mark.django_db
def test_person_duplicate_revision_and_derived_client_survive_cancellation() -> None:
    owner, creation = _owner("persona")
    organization_id = creation.organization.pk
    person = _person(owner, organization_id)

    with pytest.raises(CommercialError) as duplicate:
        _person(owner, organization_id, "099-123-4567")
    assert duplicate.value.code == "duplicate_person"

    updated = update_person(
        owner,
        organization_id,
        person_id=person["id"],
        revision=person["revision"],
        changes={"full_name": "María del Carmen Pérez"},
    )
    assert updated["revision"] == 2
    with pytest.raises(CommercialError) as stale:
        update_person(
            owner,
            organization_id,
            person_id=person["id"],
            revision=1,
            changes={"full_name": "Nombre obsoleto"},
        )
    assert stale.value.code == "stale_revision"

    event_request = _request(owner, organization_id, person["id"])
    _, provisional = _accepted(owner, organization_id, event_request["id"])
    confirmed = confirm_reservation(
        owner,
        organization_id,
        reservation_id=provisional["id"],
        kind="external_deposit",
        recognized_amount=Decimal("300.00"),
        reported_at=timezone.now(),
        reference="Transferencia reportada por el cliente",
    )
    assert confirmed["status"] == "confirmed"
    with pytest.raises(CommercialError) as cannot_lose:
        close_event_request(
            owner,
            organization_id,
            request_id=event_request["id"],
            reason="No puede perderse después de confirmar",
        )
    assert cannot_lose.value.code == "invalid_transition"
    cancel_reservation(
        owner,
        organization_id,
        reservation_id=provisional["id"],
        reason="El cliente canceló el evento",
    )

    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        request_status = EventRequest.objects.get(pk=event_request["id"]).status
    assert request_status == EventRequest.Status.CANCELLED
    assert (
        read_person(owner, organization_id, person_id=person["id"])["commercial_type"] == "client"
    )


@pytest.mark.django_db
def test_quote_totals_snapshots_and_issued_rows_are_immutable() -> None:
    owner, creation = _owner("quote")
    person = _person(owner, creation.organization.pk)
    event_request = _request(owner, creation.organization.pk, person["id"])
    quotation, _ = _accepted(owner, creation.organization.pk, event_request["id"])
    detail = quotation["versions"][0]
    assert detail["subtotal"] == Decimal("1667.20")
    assert detail["discount_total"] == Decimal("50.00")
    assert detail["total"] == Decimal("1617.20")

    with (
        authorized_tenant_scope(owner, creation.organization.pk, Capability.SALES_MANAGE),
        pytest.raises(DatabaseError),
        transaction.atomic(),
    ):
        QuotationVersion.objects.filter(
            organization_id=creation.organization.pk,
            quotation_id=quotation["id"],
        ).update(total=Decimal("1.00"))


@pytest.mark.django_db
def test_expiration_is_idempotent_releases_slot_and_returns_request_to_quoted() -> None:
    owner, creation = _owner("expiry")
    organization_id = creation.organization.pk
    person = _person(owner, organization_id)
    event_request = _request(owner, organization_id, person["id"])
    _, provisional = _accepted(owner, organization_id, event_request["id"])

    with authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE):
        Reservation.objects.filter(pk=provisional["id"]).update(
            hold_expires_at=timezone.now() - timedelta(seconds=1)
        )
    agenda = list_availability(
        owner,
        organization_id,
        space_id=event_request["space"]["id"],
        starts_at=event_request["starts_at"],
        ends_at=event_request["ends_at"],
    )
    assert agenda["available"] is True
    first = read_reservation(owner, organization_id, reservation_id=provisional["id"])
    second = read_reservation(owner, organization_id, reservation_id=provisional["id"])
    assert first["status"] == second["status"] == Reservation.Status.EXPIRED
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        assert EventRequest.objects.get(pk=event_request["id"]).status == EventRequest.Status.QUOTED
        assert (
            QuotationVersion.objects.get(reservation__pk=provisional["id"]).status
            == QuotationVersion.Status.ACCEPTED
        )


@pytest.mark.django_db
def test_expiration_before_failed_confirmation_is_persisted() -> None:
    owner, creation = _owner("expiry-confirm")
    organization_id = creation.organization.pk
    person = _person(owner, organization_id)
    event_request = _request(owner, organization_id, person["id"])
    _, provisional = _accepted(owner, organization_id, event_request["id"])
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_MANAGE):
        Reservation.objects.filter(pk=provisional["id"]).update(
            hold_expires_at=timezone.now() - timedelta(seconds=1)
        )

    with pytest.raises(CommercialError) as expired:
        confirm_reservation(
            owner,
            organization_id,
            reservation_id=provisional["id"],
            kind="external_deposit",
            recognized_amount=Decimal("100.00"),
            reported_at=timezone.now(),
            reference="Llegó fuera de plazo",
        )
    assert expired.value.code == "invalid_transition"
    assert read_reservation(owner, organization_id, reservation_id=provisional["id"])["status"] == (
        Reservation.Status.EXPIRED
    )
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        assert EventRequest.objects.get(pk=event_request["id"]).status == EventRequest.Status.QUOTED


@pytest.mark.django_db
def test_cancelling_provisional_closes_lost_without_creating_a_client() -> None:
    owner, creation = _owner("cancel-provisional")
    organization_id = creation.organization.pk
    person = _person(owner, organization_id)
    event_request = _request(owner, organization_id, person["id"])
    _, provisional = _accepted(owner, organization_id, event_request["id"])

    cancelled = cancel_reservation(
        owner,
        organization_id,
        reservation_id=provisional["id"],
        reason="No se concretó el anticipo",
    )

    assert cancelled["status"] == Reservation.Status.CANCELLED
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        assert (
            EventRequest.objects.get(pk=event_request["id"]).status
            == EventRequest.Status.CLOSED_LOST
        )
    assert read_person(owner, organization_id, person_id=person["id"])["commercial_type"] == "lead"


@pytest.mark.django_db
def test_overlap_conflicts_but_adjacent_interval_is_allowed() -> None:
    owner, creation = _owner("agenda")
    organization_id = creation.organization.pk
    first_person = _person(owner, organization_id, "0991111111")
    first_request = _request(owner, organization_id, first_person["id"])
    _, first_reservation = _accepted(owner, organization_id, first_request["id"])
    start = first_request["starts_at"]
    end = first_request["ends_at"]

    second_person = _person(owner, organization_id, "0992222222")
    birthday_type_id, space_id = _p6_refs(owner, organization_id, "Cumpleaños")
    overlap = create_event_request(
        owner,
        organization_id,
        person_id=second_person["id"],
        event_type_id=birthday_type_id,
        space_id=space_id,
        starts_at=start + timedelta(hours=1),
        ends_at=end + timedelta(hours=1),
        estimated_guests=50,
        general_need="Alquiler",
        notes="",
        origin="phone_call",
        origin_detail=None,
    )
    with pytest.raises(CommercialError) as schedule:
        _accepted(owner, organization_id, overlap["id"])
    assert schedule.value.code == "schedule_conflict"

    reception_type_id, _ = _p6_refs(owner, organization_id, "Recepción")
    adjacent = create_event_request(
        owner,
        organization_id,
        person_id=second_person["id"],
        event_type_id=reception_type_id,
        space_id=space_id,
        starts_at=end,
        ends_at=end + timedelta(hours=2),
        estimated_guests=30,
        general_need="Alquiler",
        notes="",
        origin="phone_call",
        origin_detail=None,
    )
    _, adjacent_reservation = _accepted(owner, organization_id, adjacent["id"])
    agenda = list_availability(
        owner,
        organization_id,
        space_id=space_id,
        starts_at=start,
        ends_at=end + timedelta(hours=2),
    )
    assert {block["id"] for block in agenda["blocks"]} == {
        first_reservation["id"],
        adjacent_reservation["id"],
    }


@pytest.mark.django_db
def test_finance_can_confirm_external_deposit_but_cannot_waive() -> None:
    owner, creation = _owner("finance")
    finance = _user("finance-member@example.com")
    add_membership(
        organization_id=creation.organization.pk,
        user_id=finance.pk,
        role=Membership.Role.FINANCE,
    )
    person = _person(owner, creation.organization.pk)
    event_request = _request(owner, creation.organization.pk, person["id"])
    _, provisional = _accepted(owner, creation.organization.pk, event_request["id"])

    with pytest.raises(Exception) as denied:
        confirm_reservation(
            finance,
            creation.organization.pk,
            reservation_id=provisional["id"],
            kind="waiver",
            waiver_reason="Excepción solicitada",
        )
    assert denied.type.__name__ == "AuthorizationDenied"

    confirmed = confirm_reservation(
        finance,
        creation.organization.pk,
        reservation_id=provisional["id"],
        kind="external_deposit",
        recognized_amount=Decimal("100.00"),
        reported_at=timezone.now(),
        reference="Constancia externa",
    )
    assert confirmed["status"] == Reservation.Status.CONFIRMED
