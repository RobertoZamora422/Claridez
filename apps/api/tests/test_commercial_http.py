from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from claridez.identity.models import User
from claridez.organizations.services import create_organization

PASSWORD = "correct-horse-battery-staple-commercial-http"


def _user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _csrf(client: Client) -> str:
    return str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])


def _post(client: Client, path: str, payload: dict[str, Any], token: str) -> Any:
    return client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )


def _put(client: Client, path: str, payload: dict[str, Any], token: str) -> Any:
    return client.put(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )


def _login(client: Client, user: User) -> str:
    token = _csrf(client)
    response = _post(
        client,
        "/api/v1/auth/login/",
        {"email": user.email, "password": PASSWORD},
        token,
    )
    assert response.status_code == 200
    return _csrf(client)


@pytest.mark.django_db
def test_complete_commercial_http_flow_csrf_and_cross_tenant_errors() -> None:
    owner = _user("commercial-http-owner@example.com")
    own = create_organization(owner_user_id=owner.pk, name="HTTP own")
    foreign_owner = _user("commercial-http-foreign@example.com")
    foreign = create_organization(owner_user_id=foreign_owner.pk, name="HTTP foreign")
    client = Client(enforce_csrf_checks=True)
    token = _login(client, owner)
    base = f"/api/v1/organizations/{own.organization.pk}"

    missing_csrf = client.post(
        f"{base}/people/",
        data=json.dumps(
            {
                "full_name": "Ana Torres",
                "phone": "0987654321",
                "origin": "whatsapp",
            }
        ),
        content_type="application/json",
    )
    assert missing_csrf.status_code == 403

    person_response = _post(
        client,
        f"{base}/people/",
        {
            "full_name": "Ana Torres",
            "phone": "0987654321",
            "email": "ana@example.com",
            "origin": "whatsapp",
        },
        token,
    )
    assert person_response.status_code == 201
    person = person_response.json()
    event_type_response = _post(
        client,
        f"{base}/event-types/",
        {"name": "Graduación"},
        token,
    )
    assert event_type_response.status_code == 201
    event_type = event_type_response.json()
    venues_response = client.get(f"{base}/venues/")
    assert venues_response.status_code == 200
    space_id = venues_response.json()["venues"][0]["spaces"][0]["id"]

    start = timezone.now() + timedelta(days=15)
    end = start + timedelta(hours=6)
    request_response = _post(
        client,
        f"{base}/event-requests/",
        {
            "person_id": person["id"],
            "event_type_id": event_type["id"],
            "space_id": space_id,
            "starts_at": start.isoformat(),
            "ends_at": end.isoformat(),
            "estimated_guests": 80,
            "general_need": "Salón y servicio",
            "notes": "Prueba API",
            "origin": "referral",
        },
        token,
    )
    assert request_response.status_code == 201
    event_request = request_response.json()

    quote_response = _post(
        client,
        f"{base}/event-requests/{event_request['id']}/quotations/",
        {"valid_until": (timezone.now() + timedelta(days=4)).isoformat()},
        token,
    )
    assert quote_response.status_code == 201
    quotation = quote_response.json()
    draft = quotation["versions"][0]
    saved = _put(
        client,
        f"{base}/quotations/{quotation['id']}/versions/1/",
        {
            "revision": draft["revision"],
            "valid_until": (timezone.now() + timedelta(days=4)).isoformat(),
            "notes": "Válida cuatro días",
            "lines": [
                {
                    "description": "Servicio integral",
                    "unit_label": "evento",
                    "quantity": "1.000",
                    "unit_price": "1200.00",
                    "discount_amount": "100.00",
                }
            ],
        },
        token,
    )
    assert saved.status_code == 200
    assert saved.json()["versions"][0]["total"] == "1100.00"

    issued = _post(
        client,
        f"{base}/quotations/{quotation['id']}/versions/1/issue/",
        {},
        token,
    )
    assert issued.status_code == 200
    accepted = _post(
        client,
        f"{base}/quotations/{quotation['id']}/versions/1/accept/",
        {"channel": "whatsapp", "note": "Aceptada"},
        token,
    )
    assert accepted.status_code == 200
    reservation = accepted.json()
    assert reservation["status"] == "provisional"

    query = urlencode({"from": start.isoformat(), "to": end.isoformat(), "space_id": space_id})
    agenda = client.get(f"{base}/availability/?{query}")
    assert agenda.status_code == 200
    assert agenda.json()["available"] is False

    confirmed = _post(
        client,
        f"{base}/reservations/{reservation['id']}/confirm/",
        {
            "kind": "external_deposit",
            "recognized_amount": "250.00",
            "reported_at": timezone.now().isoformat(),
            "reference": "Transferencia confirmada fuera de Claridez",
        },
        token,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["recognized_deposit_amount"] == "250.00"

    cancelled = _post(
        client,
        f"{base}/reservations/{reservation['id']}/cancel/",
        {"reason": "Cancelación solicitada por el cliente"},
        token,
    )
    assert cancelled.status_code == 200
    detail = client.get(f"{base}/event-requests/{event_request['id']}/")
    assert detail.status_code == 200
    assert detail.json()["status"] == "cancelled"

    cross = client.get(f"/api/v1/organizations/{foreign.organization.pk}/people/")
    missing = client.get("/api/v1/organizations/00000000-0000-4000-8000-000000000099/people/")
    assert cross.status_code == missing.status_code == 404
    assert cross.json() == missing.json()
