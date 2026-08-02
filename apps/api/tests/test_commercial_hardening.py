from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import pytest
from django.test import Client
from django.utils import timezone

from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.models import QuotationVersion
from claridez.commercial.services import (
    accept_quotation_version,
    create_event_request,
    create_person,
    create_quotation,
    issue_quotation_version,
    list_availability,
    list_person_revisions,
    read_event_request,
    read_quotation,
    read_reservation,
    replace_quotation_draft,
    update_event_request,
    update_person,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.models import Membership
from claridez.organizations.services import add_membership, create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope

PASSWORD = "commercial-hardening-tests-42!"
PII = ("María Pérez", "+593991234567", "maria@example.com")


def _user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _actor_for_role(owner: User, organization_id: Any, role: Membership.Role) -> User:
    if role == Membership.Role.OWNER:
        return owner
    actor = _user(f"hardening-{role}@example.com")
    add_membership(organization_id=organization_id, user_id=actor.pk, role=role)
    return actor


def _p6_refs(owner: User, organization_id: Any, name: str = "Boda") -> tuple[Any, Any]:
    event_type = next(
        (row for row in list_event_types(owner, organization_id) if row["name"] == name),
        None,
    )
    if event_type is None:
        event_type = create_event_type(owner, organization_id, name=name)
    space_id = list_venues(owner, organization_id)[0]["spaces"][0]["id"]
    return event_type["id"], space_id


def _commercial_flow() -> tuple[User, Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    owner = _user("hardening-owner@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Hardening comercial")
    organization_id = creation.organization.pk
    person = create_person(
        owner,
        organization_id,
        full_name=PII[0],
        phone="0991234567",
        email=PII[2],
        origin="whatsapp",
        origin_detail=None,
    )
    start = timezone.now() + timedelta(days=30)
    event_type_id, space_id = _p6_refs(owner, organization_id)
    event_request = create_event_request(
        owner,
        organization_id,
        person_id=person["id"],
        event_type_id=event_type_id,
        space_id=space_id,
        starts_at=start,
        ends_at=start + timedelta(hours=5),
        estimated_guests=90,
        general_need="Salón completo",
        notes="",
        origin="referral",
        origin_detail=None,
    )
    quotation = create_quotation(
        owner,
        organization_id,
        request_id=event_request["id"],
        valid_until=timezone.now() + timedelta(days=5),
    )
    quotation = replace_quotation_draft(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=quotation["versions"][0]["revision"],
        valid_until=timezone.now() + timedelta(days=5),
        notes="Propuesta",
        lines=[
            {
                "description": "Alquiler del salón",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("500.00"),
                "discount_amount": Decimal("0.00"),
            }
        ],
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
    return owner, creation, event_request, quotation, reservation


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role", "can_read_person"),
    [
        (Membership.Role.OWNER, True),
        (Membership.Role.ADMINISTRATOR, True),
        (Membership.Role.COMMERCIAL, True),
        (Membership.Role.OPERATIONS, False),
        (Membership.Role.FINANCE, False),
    ],
)
def test_service_representations_enforce_person_read(
    role: Membership.Role, can_read_person: bool
) -> None:
    owner, creation, event_request, quotation, reservation = _commercial_flow()
    organization_id = creation.organization.pk
    actor = _actor_for_role(owner, organization_id, role)

    request_payload = read_event_request(actor, organization_id, request_id=event_request["id"])
    quotation_payload = read_quotation(actor, organization_id, quotation_id=quotation["id"])
    reservation_payload = read_reservation(actor, organization_id, reservation_id=reservation["id"])
    availability_payload = list_availability(
        actor,
        organization_id,
        space_id=event_request["space"]["id"],
        starts_at=event_request["starts_at"] - timedelta(hours=1),
        ends_at=event_request["ends_at"] + timedelta(hours=1),
    )
    snapshot_person = quotation_payload["versions"][0]["person"]
    serialized = json.dumps(
        [request_payload, quotation_payload, reservation_payload, availability_payload],
        default=str,
        ensure_ascii=False,
    )

    if can_read_person:
        assert request_payload["person"]["full_name"] == PII[0]
        assert snapshot_person == {
            "full_name": PII[0],
            "phone_e164": PII[1],
            "email": PII[2],
        }
    else:
        assert request_payload["person"] == {
            "id": request_payload["person"]["id"],
            "commercial_type": "lead",
            "revision": 1,
            "created_at": request_payload["person"]["created_at"],
            "updated_at": request_payload["person"]["updated_at"],
        }
        assert snapshot_person == {"restricted": True}
        assert all(value not in serialized for value in PII)

    with authorized_tenant_scope(owner, organization_id, Capability.PERSON_READ):
        stored = QuotationVersion.objects.get(pk=quotation_payload["versions"][0]["id"])
        assert (
            stored.person_name_snapshot,
            stored.person_phone_snapshot,
            stored.person_email_snapshot,
        ) == PII


def _csrf(client: Client) -> str:
    return str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])


def _login(client: Client, actor: User) -> str:
    token = _csrf(client)
    response = client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": actor.email, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200
    return _csrf(client)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role", "can_read_person"),
    [
        (Membership.Role.OWNER, True),
        (Membership.Role.ADMINISTRATOR, True),
        (Membership.Role.COMMERCIAL, True),
        (Membership.Role.OPERATIONS, False),
        (Membership.Role.FINANCE, False),
    ],
)
def test_http_representations_enforce_person_read(
    role: Membership.Role, can_read_person: bool
) -> None:
    owner, creation, event_request, quotation, reservation = _commercial_flow()
    organization_id = creation.organization.pk
    actor = _actor_for_role(owner, organization_id, role)
    client = Client(enforce_csrf_checks=True)
    _login(client, actor)
    base = f"/api/v1/organizations/{organization_id}"
    query = urlencode(
        {
            "space_id": str(event_request["space"]["id"]),
            "from": (event_request["starts_at"] - timedelta(hours=1)).isoformat(),
            "to": (event_request["ends_at"] + timedelta(hours=1)).isoformat(),
        }
    )
    responses = [
        client.get(f"{base}/event-requests/{event_request['id']}/"),
        client.get(f"{base}/quotations/{quotation['id']}/"),
        client.get(f"{base}/reservations/{reservation['id']}/"),
        client.get(f"{base}/availability/?{query}"),
    ]

    assert all(response.status_code == 200 for response in responses)
    payloads = [response.json() for response in responses]
    snapshot_person = payloads[1]["versions"][0]["person"]
    serialized = json.dumps(payloads, ensure_ascii=False)
    if can_read_person:
        assert payloads[0]["person"]["full_name"] == PII[0]
        assert snapshot_person["phone_e164"] == PII[1]
    else:
        assert "full_name" not in payloads[0]["person"]
        assert snapshot_person == {"restricted": True}
        assert all(value not in serialized for value in PII)


@pytest.mark.django_db
def test_service_patch_without_effective_changes_is_idempotent() -> None:
    owner = _user("hardening-no-change-service@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Sin cambios servicio")
    organization_id = creation.organization.pk
    person = create_person(
        owner,
        organization_id,
        full_name=PII[0],
        phone="0991234567",
        email=PII[2],
        origin="whatsapp",
        origin_detail=None,
    )
    start = timezone.now() + timedelta(days=20)
    event_type_id, space_id = _p6_refs(owner, organization_id)
    event_request = create_event_request(
        owner,
        organization_id,
        person_id=person["id"],
        event_type_id=event_type_id,
        space_id=space_id,
        starts_at=start,
        ends_at=start + timedelta(hours=4),
        estimated_guests=50,
        general_need="Salón completo",
        notes="",
        origin="referral",
        origin_detail=None,
    )

    assert (
        update_person(
            owner,
            organization_id,
            person_id=person["id"],
            revision=1,
            changes={},
        )["revision"]
        == 1
    )
    assert (
        update_person(
            owner,
            organization_id,
            person_id=person["id"],
            revision=1,
            changes={
                "full_name": "  María   Pérez ",
                "phone": "+593 99 123 4567",
                "email": " MARIA@example.com ",
                "origin": "whatsapp",
                "origin_detail": " ",
            },
        )["revision"]
        == 1
    )
    assert len(list_person_revisions(owner, organization_id, person_id=person["id"])) == 1

    assert (
        update_event_request(
            owner,
            organization_id,
            request_id=event_request["id"],
            revision=1,
            changes={},
        )["revision"]
        == 1
    )
    assert (
        update_event_request(
            owner,
            organization_id,
            request_id=event_request["id"],
            revision=1,
            changes={
                "event_type_id": event_type_id,
                "space_id": space_id,
                "starts_at": event_request["starts_at"],
                "ends_at": event_request["ends_at"],
                "estimated_guests": 50,
                "general_need": "Salón   completo",
                "notes": " ",
                "origin": "referral",
                "origin_detail": " ",
                "responsible_membership_id": creation.owner_membership.pk,
            },
        )["revision"]
        == 1
    )


@pytest.mark.django_db
def test_http_patch_without_effective_changes_is_idempotent() -> None:
    owner = _user("hardening-no-change-http@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Sin cambios HTTP")
    organization_id = creation.organization.pk
    person = create_person(
        owner,
        organization_id,
        full_name=PII[0],
        phone="0991234567",
        email=PII[2],
        origin="whatsapp",
        origin_detail=None,
    )
    start = timezone.now() + timedelta(days=20)
    event_type_id, space_id = _p6_refs(owner, organization_id)
    event_request = create_event_request(
        owner,
        organization_id,
        person_id=person["id"],
        event_type_id=event_type_id,
        space_id=space_id,
        starts_at=start,
        ends_at=start + timedelta(hours=4),
        estimated_guests=50,
        general_need="Salón completo",
        notes="",
        origin="referral",
        origin_detail=None,
    )
    client = Client(enforce_csrf_checks=True)
    token = _login(client, owner)
    base = f"/api/v1/organizations/{organization_id}"

    person_only_revision = client.patch(
        f"{base}/people/{person['id']}/",
        data=json.dumps({"revision": 1}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    person_normalized = client.patch(
        f"{base}/people/{person['id']}/",
        data=json.dumps(
            {
                "revision": 1,
                "full_name": "María   Pérez",
                "phone": "099-123-4567",
                "email": "MARIA@example.com",
            }
        ),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    request_only_revision = client.patch(
        f"{base}/event-requests/{event_request['id']}/",
        data=json.dumps({"revision": 1}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    request_normalized = client.patch(
        f"{base}/event-requests/{event_request['id']}/",
        data=json.dumps(
            {
                "revision": 1,
                "event_type_id": str(event_type_id),
                "space_id": str(space_id),
                "general_need": "Salón   completo",
                "notes": " ",
            }
        ),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert person_only_revision.status_code == person_normalized.status_code == 200
    assert request_only_revision.status_code == request_normalized.status_code == 200
    assert person_only_revision.json()["revision"] == person_normalized.json()["revision"] == 1
    assert request_only_revision.json()["revision"] == request_normalized.json()["revision"] == 1
    revisions = client.get(f"{base}/people/{person['id']}/revisions/")
    assert revisions.status_code == 200
    assert len(revisions.json()["revisions"]) == 1
