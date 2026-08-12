"""Contrato HTTP de contexto y lecturas organizacionales."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator

from claridez.identity.models import User
from claridez.identity.sessions import SESSION_ABSOLUTE_EXPIRY_KEY
from claridez.organizations.models import Membership, Organization
from claridez.organizations.services import add_membership, create_organization

PASSWORD = "correct-horse-battery-staple-http-42"


def _active_verified_user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _csrf(client: Client) -> str:
    return str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])


def _post(client: Client, path: str, payload: dict[str, str], token: str) -> Any:
    return client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )


def _login(client: Client, user: User) -> None:
    response = _post(
        client,
        "/api/v1/auth/login/",
        {"email": user.email, "password": PASSWORD},
        _csrf(client),
    )
    assert response.status_code == 200


def _set_session_context(client: Client, organization: Organization | str) -> None:
    session = client.session
    session["last_organization_id"] = str(
        organization.pk if isinstance(organization, Organization) else organization
    )
    session.save()


@pytest.mark.django_db
def test_organization_endpoints_require_a_valid_session() -> None:
    client = Client(enforce_csrf_checks=True)
    paths = [
        "/api/v1/organizations/",
        "/api/v1/organizations/context/",
        "/api/v1/organizations/00000000-0000-4000-8000-000000000001/settings/",
        "/api/v1/organizations/00000000-0000-4000-8000-000000000001/memberships/",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 401
        assert response["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_list_only_contains_active_organizations_with_active_membership() -> None:
    actor = _active_verified_user("list-owner@example.com")
    visible = create_organization(owner_user_id=actor.pk, name="Visible").organization
    inactive_membership_org = create_organization(
        owner_user_id=actor.pk,
        name="Inactive membership",
    )
    inactive_organization = create_organization(
        owner_user_id=actor.pk,
        name="Inactive organization",
    )
    Membership.objects.filter(pk=inactive_membership_org.owner_membership.pk).update(
        status=Membership.Status.SUSPENDED,
        suspended_at=inactive_membership_org.owner_membership.joined_at,
    )
    Organization.objects.filter(pk=inactive_organization.organization.pk).update(
        status=Organization.Status.SUSPENDED
    )
    client = Client(enforce_csrf_checks=True)
    _login(client, actor)

    response = client.get("/api/v1/organizations/")

    assert response.status_code == 200
    assert response.json() == {
        "organizations": [{"id": str(visible.pk), "name": "Visible", "slug": "visible"}]
    }


@pytest.mark.django_db
def test_context_selection_requires_csrf_does_not_slide_and_rejects_stale_context() -> None:
    actor = _active_verified_user("context-owner@example.com")
    first = create_organization(owner_user_id=actor.pk, name="Context first")
    second = create_organization(owner_user_id=actor.pk, name="Context second")
    suspended_organization = create_organization(
        owner_user_id=actor.pk,
        name="Context suspended organization",
    )
    client = Client(enforce_csrf_checks=True)
    _login(client, actor)
    original_absolute = client.session[SESSION_ABSOLUTE_EXPIRY_KEY]
    original_django_expiry = client.session.get("_session_expiry")
    path = "/api/v1/organizations/context/"

    missing = client.post(
        path,
        data=json.dumps({"organization_id": str(first.organization.pk)}),
        content_type="application/json",
    )
    wrong = _post(
        client,
        path,
        {"organization_id": str(first.organization.pk)},
        "wrong-token",
    )
    selected = _post(
        client,
        path,
        {"organization_id": str(first.organization.pk)},
        _csrf(client),
    )
    changed = _post(
        client,
        path,
        {"organization_id": str(second.organization.pk)},
        _csrf(client),
    )

    assert missing.status_code == wrong.status_code == 403
    assert selected.status_code == 200
    assert changed.status_code == 200
    assert changed.json()["organization"]["id"] == str(second.organization.pk)
    assert client.session[SESSION_ABSOLUTE_EXPIRY_KEY] == original_absolute
    assert client.session.get("_session_expiry") == original_django_expiry
    assert client.get(path).json()["organization"]["id"] == str(second.organization.pk)

    Membership.objects.filter(pk=second.owner_membership.pk).update(
        status=Membership.Status.SUSPENDED,
        suspended_at=second.owner_membership.joined_at,
    )
    suspended = client.get(path)
    assert suspended.status_code == 200
    assert suspended.json() == {"organization": None}

    _set_session_context(client, first.organization)
    Membership.objects.filter(pk=first.owner_membership.pk).update(
        status=Membership.Status.REVOKED,
        revoked_at=first.owner_membership.joined_at,
    )
    revoked = client.get(path)
    assert revoked.status_code == 200
    assert revoked.json() == {"organization": None}

    _set_session_context(client, suspended_organization.organization)
    Organization.objects.filter(pk=suspended_organization.organization.pk).update(
        status=Organization.Status.SUSPENDED
    )
    inactive = client.get(path)
    assert inactive.status_code == 200
    assert inactive.json() == {"organization": None}

    _set_session_context(client, "00000000-0000-4000-8000-000000000099")
    missing_organization = client.get(path)
    assert missing_organization.status_code == 200
    assert missing_organization.json() == {"organization": None}
    assert "last_organization_id" not in client.session


@pytest.mark.django_db
def test_settings_and_memberships_deny_cross_tenant_without_leaking_reason() -> None:
    actor = _active_verified_user("cross-owner@example.com")
    own = create_organization(owner_user_id=actor.pk, name="Own")
    other_owner = _active_verified_user("cross-other@example.com")
    other = create_organization(owner_user_id=other_owner.pk, name="Other")
    client = Client(enforce_csrf_checks=True)
    _login(client, actor)

    own_settings = client.get(f"/api/v1/organizations/{own.organization.pk}/settings/")
    foreign = client.get(f"/api/v1/organizations/{other.organization.pk}/settings/")
    missing = client.get("/api/v1/organizations/00000000-0000-4000-8000-000000000099/settings/")
    foreign_context = _post(
        client,
        "/api/v1/organizations/context/",
        {"organization_id": str(other.organization.pk)},
        _csrf(client),
    )
    Organization.objects.filter(pk=other.organization.pk).update(
        status=Organization.Status.SUSPENDED
    )
    inactive = client.get(f"/api/v1/organizations/{other.organization.pk}/settings/")

    assert own_settings.status_code == 200
    assert own_settings.json()["settings"]["organization_id"] == str(own.organization.pk)
    public_errors = [
        (response.status_code, response.json()) for response in (foreign, missing, inactive)
    ]
    assert len({json.dumps(error, sort_keys=True) for error in public_errors}) == 1
    assert public_errors[0][0] == 404
    assert foreign_context.status_code == 404
    assert foreign_context.json() == foreign.json()


@pytest.mark.django_db
def test_membership_read_requires_approved_role_and_has_no_write_endpoint() -> None:
    owner = _active_verified_user("members-http-owner@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Members HTTP")
    commercial = _active_verified_user("members-http-commercial@example.com")
    add_membership(
        organization_id=creation.organization.pk,
        user_id=commercial.pk,
        role=Membership.Role.COMMERCIAL,
    )
    owner_client = Client(enforce_csrf_checks=True)
    _login(owner_client, owner)
    commercial_client = Client(enforce_csrf_checks=True)
    _login(commercial_client, commercial)
    path = f"/api/v1/organizations/{creation.organization.pk}/memberships/"

    visible = owner_client.get(path)
    denied = commercial_client.get(path)
    forbidden_write = _post(owner_client, path, {}, _csrf(owner_client))

    assert visible.status_code == 200
    assert len(visible.json()["memberships"]) == 2
    assert denied.status_code == 403
    assert forbidden_write.status_code == 405


def test_openapi_contains_only_approved_organization_commercial_and_operations_methods() -> None:
    schema = SchemaGenerator().get_schema(request=None, public=True)  # type: ignore[no-untyped-call]
    assert schema is not None
    organization_paths = {
        path: set(methods)
        for path, methods in schema["paths"].items()
        if path.startswith("/api/v1/organizations/")
    }
    expected_paths = {
        "/api/v1/organizations/": {"get"},
        "/api/v1/organizations/context/": {"get", "post"},
        "/api/v1/organizations/{organization_id}/settings/": {"get"},
        "/api/v1/organizations/{organization_id}/memberships/": {"get"},
        "/api/v1/organizations/{organization_id}/configuration/capabilities/": {"get"},
        "/api/v1/organizations/{organization_id}/configuration/": {"get", "patch"},
        "/api/v1/organizations/{organization_id}/venues/": {"get", "post"},
        "/api/v1/organizations/{organization_id}/venues/{venue_id}/": {"patch"},
        "/api/v1/organizations/{organization_id}/venues/{venue_id}/spaces/": {"post"},
        "/api/v1/organizations/{organization_id}/spaces/{space_id}/": {"patch"},
        "/api/v1/organizations/{organization_id}/event-types/": {"get", "post"},
        "/api/v1/organizations/{organization_id}/event-types/{event_type_id}/": {"patch"},
        "/api/v1/organizations/{organization_id}/catalog/items/": {"get", "post"},
        "/api/v1/organizations/{organization_id}/catalog/items/{item_id}/": {"patch"},
        "/api/v1/organizations/{organization_id}/catalog/items/{item_id}/prices/": {"post"},
        "/api/v1/organizations/{organization_id}/commercial/capabilities/": {"get"},
        "/api/v1/organizations/{organization_id}/people/": {"get", "post"},
        "/api/v1/organizations/{organization_id}/people/{person_id}/": {"get", "patch"},
        "/api/v1/organizations/{organization_id}/people/{person_id}/revisions/": {"get"},
        "/api/v1/organizations/{organization_id}/people/merge/": {"post"},
        "/api/v1/organizations/{organization_id}/people/{person_id}/consents/": {
            "get",
            "post",
        },
        "/api/v1/organizations/{organization_id}/event-requests/": {"get", "post"},
        "/api/v1/organizations/{organization_id}/event-requests/{event_request_id}/": {
            "get",
            "patch",
        },
        "/api/v1/organizations/{organization_id}/event-requests/{event_request_id}/close/": {
            "post"
        },
        "/api/v1/organizations/{organization_id}/availability/": {"get"},
        "/api/v1/organizations/{organization_id}/event-requests/{event_request_id}/quotations/": {
            "post"
        },
        "/api/v1/organizations/{organization_id}/quotations/{quotation_id}/": {"get"},
        "/api/v1/organizations/{organization_id}/quotations/{quotation_id}/versions/": {"post"},
        "/api/v1/organizations/{organization_id}/quotations/{quotation_id}/versions/{version}/": {
            "put"
        },
        (
            "/api/v1/organizations/{organization_id}/quotations/{quotation_id}/versions/"
            "{version}/issue/"
        ): {"post"},
        (
            "/api/v1/organizations/{organization_id}/quotations/{quotation_id}/versions/"
            "{version}/accept/"
        ): {"post"},
        "/api/v1/organizations/{organization_id}/reservations/{reservation_id}/": {"get"},
        "/api/v1/organizations/{organization_id}/reservations/{reservation_id}/confirm/": {"post"},
        "/api/v1/organizations/{organization_id}/reservations/{reservation_id}/cancel/": {"post"},
        "/api/v1/organizations/{organization_id}/reservations/{reservation_id}/reschedule/": {
            "post"
        },
        "/api/v1/organizations/{organization_id}/reservations/{reservation_id}/schedule-history/": {
            "get"
        },
        "/api/v1/organizations/{organization_id}/scheduling/capabilities/": {"get"},
        "/api/v1/organizations/{organization_id}/scheduling/calendar/": {"get"},
        "/api/v1/organizations/{organization_id}/scheduling/calendar.ics": {"get"},
        "/api/v1/organizations/{organization_id}/scheduling/availability/": {"post"},
        "/api/v1/organizations/{organization_id}/scheduling/spaces/{space_id}/policy/": {
            "get",
            "patch",
        },
        "/api/v1/organizations/{organization_id}/scheduling/blocks/": {"get", "post"},
        "/api/v1/organizations/{organization_id}/scheduling/blocks/{block_id}/release/": {"post"},
        "/api/v1/organizations/{organization_id}/scheduling/blocks/{block_id}/cancel/": {"post"},
        "/api/v1/organizations/{organization_id}/crm/capabilities/": {"get"},
        "/api/v1/organizations/{organization_id}/crm/opportunities/": {"get"},
        "/api/v1/organizations/{organization_id}/crm/opportunities/{event_request_id}/": {"get"},
        ("/api/v1/organizations/{organization_id}/crm/opportunities/{event_request_id}/history/"): {
            "get"
        },
        "/api/v1/organizations/{organization_id}/crm/interactions/": {"get", "post"},
        "/api/v1/organizations/{organization_id}/crm/tasks/": {"get", "post"},
        "/api/v1/organizations/{organization_id}/crm/tasks/{task_id}/": {"patch"},
        "/api/v1/organizations/{organization_id}/crm/indicators/": {"get"},
        "/api/v1/organizations/{organization_id}/crm/people/{person_id}/": {"get"},
        "/api/v1/organizations/{organization_id}/operations/capabilities/": {"get"},
        "/api/v1/organizations/{organization_id}/operations/assignees/": {"get"},
        "/api/v1/organizations/{organization_id}/operations/events/": {"get"},
        "/api/v1/organizations/{organization_id}/operations/events/{reservation_id}/": {"get"},
        (
            "/api/v1/organizations/{organization_id}/operations/events/"
            "{reservation_id}/preparation/"
        ): {"patch"},
        ("/api/v1/organizations/{organization_id}/operations/events/{reservation_id}/assign/"): {
            "post"
        },
        ("/api/v1/organizations/{organization_id}/operations/events/{reservation_id}/items/"): {
            "post"
        },
        (
            "/api/v1/organizations/{organization_id}/operations/events/"
            "{reservation_id}/items/{item_id}/"
        ): {"patch"},
        ("/api/v1/organizations/{organization_id}/operations/events/{reservation_id}/ready/"): {
            "post"
        },
        ("/api/v1/organizations/{organization_id}/operations/events/{reservation_id}/start/"): {
            "post"
        },
        ("/api/v1/organizations/{organization_id}/operations/events/{reservation_id}/complete/"): {
            "post"
        },
    }
    assert organization_paths == expected_paths
