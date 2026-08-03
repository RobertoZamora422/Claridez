from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Event
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.db import (
    DatabaseError,
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator

from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.errors import CommercialError
from claridez.commercial.models import Reservation
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
from claridez.operations.cutover import verify_operations_cutover
from claridez.operations.errors import OperationsError
from claridez.operations.models import EventPreparation, PreparationItem, PreparationTransition
from claridez.operations.representations import preparation_representation
from claridez.operations.services import (
    assign_preparation,
    complete_event,
    create_item,
    list_events,
    mark_ready,
    read_event,
    start_event,
    update_item,
)
from claridez.organizations.capabilities import Capability
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.models import Membership
from claridez.organizations.services import add_membership, create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope

PASSWORD = "correct-horse-battery-staple-operations"
HISTORICAL_ACTOR_FIELDS = {"membership_id", "display_name", "available"}
FORBIDDEN_HISTORICAL_ACTOR_FIELDS = {
    "role",
    "email",
    "user",
    "user_id",
    "phone",
    "phone_e164",
    "contact",
}


def _assert_minimal_historical_actor(actor: dict[str, Any]) -> None:
    assert set(actor) == HISTORICAL_ACTOR_FIELDS
    assert not (set(actor) & FORBIDDEN_HISTORICAL_ACTOR_FIELDS)


def _user(email: str, display_name: str = "Equipo Claridez") -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        display_name=display_name,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _accepted(
    owner: User, organization_id: UUID, *, days: int = 20, phone: str = "0991234567"
) -> dict[str, Any]:
    person = create_person(
        owner,
        organization_id,
        full_name="Contacto Operativo",
        phone=phone,
        email="contacto@example.com",
        origin="whatsapp",
        origin_detail=None,
    )
    starts_at = timezone.now() + timedelta(days=days)
    event_type = next(
        (row for row in list_event_types(owner, organization_id) if row["name"] == "Boda"),
        None,
    )
    if event_type is None:
        event_type = create_event_type(owner, organization_id, name="Boda")
    space_id = list_venues(owner, organization_id)[0]["spaces"][0]["id"]
    event_request = create_event_request(
        owner,
        organization_id,
        person_id=person["id"],
        event_type_id=event_type["id"],
        space_id=space_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=5),
        estimated_guests=90,
        general_need="Recepción y ceremonia",
        notes="Nota comercial privada",
        origin="whatsapp",
        origin_detail=None,
    )
    quotation = create_quotation(
        owner,
        organization_id,
        request_id=event_request["id"],
        valid_until=timezone.now() + timedelta(days=3),
    )
    version = quotation["versions"][0]
    replace_quotation_draft(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        revision=version["revision"],
        valid_until=timezone.now() + timedelta(days=3),
        notes="Monto privado",
        lines=[
            {
                "description": "Servicio de evento",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("1000.00"),
                "discount_amount": Decimal("0.00"),
            }
        ],
    )
    issue_quotation_version(owner, organization_id, quotation_id=quotation["id"], version=1)
    return accept_quotation_version(
        owner,
        organization_id,
        quotation_id=quotation["id"],
        version=1,
        channel="whatsapp",
        note="Aceptada",
    )


def _confirmed(
    owner: User, organization_id: UUID, *, days: int = 20, phone: str = "0991234567"
) -> dict[str, Any]:
    reservation = _accepted(owner, organization_id, days=days, phone=phone)
    return confirm_reservation(
        owner,
        organization_id,
        reservation_id=reservation["id"],
        kind="external_deposit",
        recognized_amount=Decimal("100.00"),
        reported_at=timezone.now(),
        reference="Transferencia externa",
    )


def _resolve_all(owner: User, organization_id: UUID, reservation_id: UUID) -> int:
    detail = read_event(owner, organization_id, reservation_id=reservation_id)
    revision = detail["preparation"]["revision"]
    for item in detail["preparation"]["items"]:
        changed = update_item(
            owner,
            organization_id,
            reservation_id=reservation_id,
            item_id=item["id"],
            revision=item["revision"],
            values={"status": "completed"},
        )
        revision = changed["preparation_revision"]
        resolved_by = changed["item"]["resolved_by"]
        assert resolved_by["display_name"] == "Equipo Claridez"
        _assert_minimal_historical_actor(resolved_by)
    return int(revision)


@pytest.mark.django_db
def test_confirmation_automatically_creates_exact_baseline_and_initialized_transition() -> None:
    owner = _user("operations-auto@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones auto")
    reservation = _confirmed(owner, creation.organization.pk)

    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        preparation = EventPreparation.objects.get(reservation_id=reservation["id"])
        assert preparation.status == EventPreparation.Status.PREPARING
        assert preparation.revision == 1
        assert PreparationItem.objects.filter(preparation=preparation).count() == 7
        assert set(
            PreparationItem.objects.filter(preparation=preparation).values_list(
                "baseline_key", flat=True
            )
        ) == {
            "space_layout",
            "guest_count",
            "special_requirements",
            "entry_schedule",
            "furniture",
            "decoration",
            "final_readiness_review",
        }
        transition = PreparationTransition.objects.get(preparation=preparation)
        assert transition.cause == PreparationTransition.Cause.INITIALIZED
        assert transition.actor_membership_id == creation.owner_membership.pk

    replay = confirm_reservation(
        owner,
        creation.organization.pk,
        reservation_id=reservation["id"],
        kind="external_deposit",
    )
    assert replay["id"] == reservation["id"]


@pytest.mark.django_db
def test_ready_start_complete_flow_resolution_evidence_and_phone_minimization() -> None:
    owner = _user("operations-flow@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones flow")
    reservation = _confirmed(owner, creation.organization.pk)
    reservation_id = UUID(str(reservation["id"]))

    detail = read_event(owner, creation.organization.pk, reservation_id=reservation_id)
    assert detail["contact"]["phone_e164"] == "+593991234567"
    assign_preparation(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        revision=detail["preparation"]["revision"],
        responsible_membership_id=creation.owner_membership.pk,
    )
    revision = _resolve_all(owner, creation.organization.pk, reservation_id)
    ready = mark_ready(
        owner, creation.organization.pk, reservation_id=reservation_id, revision=revision
    )
    assert ready["preparation"]["status"] == "ready"
    _assert_minimal_historical_actor(ready["preparation"]["ready_by"])
    started = start_event(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        revision=ready["preparation"]["revision"],
    )
    _assert_minimal_historical_actor(started["preparation"]["ready_by"])
    _assert_minimal_historical_actor(started["preparation"]["started_by"])
    completed = complete_event(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        revision=started["preparation"]["revision"],
    )
    assert completed["preparation"]["status"] == "completed"
    assert completed["contact"] == {"display_name": "Contacto Operativo"}
    for field in ("ready_by", "started_by", "completed_by"):
        _assert_minimal_historical_actor(completed["preparation"][field])
    serialized = str(completed).lower()
    for forbidden in (
        "contacto@example.com",
        "subtotal",
        "discount",
        "deposit",
        "anticipo",
        "operations-flow@example.com",
    ):
        assert forbidden not in serialized


@pytest.mark.django_db
def test_event_list_paginates_before_representation_with_bounded_queries() -> None:
    owner = _user("operations-list-volume@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones volumen")
    reservation_ids = [
        UUID(
            str(
                _confirmed(
                    owner,
                    creation.organization.pk,
                    days=day,
                    phone=f"099000{day:04d}",
                )["id"]
            )
        )
        for day in range(10, 35)
    ]
    from_date = timezone.localdate() + timedelta(days=1)
    to_date = timezone.localdate() + timedelta(days=60)

    with (
        CaptureQueriesContext(connection) as captured,
        patch(
            "claridez.operations.services.queries.preparation_representation",
            wraps=preparation_representation,
        ) as represent,
    ):
        first_page = list_events(
            owner,
            creation.organization.pk,
            from_date=from_date,
            to_date=to_date,
            page_size=7,
        )

    assert len(first_page["results"]) == 7
    assert first_page["next_cursor"]
    assert represent.call_count == 7
    assert len(captured) <= 13
    assert all("items" not in result["preparation"] for result in first_page["results"])
    assert all("operational_notes" not in result["preparation"] for result in first_page["results"])
    first_ids = [UUID(str(result["reservation_id"])) for result in first_page["results"]]
    assert first_ids == reservation_ids[:7]

    with CaptureQueriesContext(connection) as second_captured:
        second_page = list_events(
            owner,
            creation.organization.pk,
            from_date=from_date,
            to_date=to_date,
            cursor=first_page["next_cursor"],
            page_size=7,
        )
    second_ids = [UUID(str(result["reservation_id"])) for result in second_page["results"]]
    assert second_ids == reservation_ids[7:14]
    assert not set(first_ids) & set(second_ids)
    assert len(second_captured) <= 13


@pytest.mark.django_db
def test_operations_openapi_is_concrete_minimal_and_client_generation_ready() -> None:
    generator_class = cast(Any, SchemaGenerator)
    schema = generator_class().get_schema(request=None, public=True)
    assert schema is not None
    components = schema["components"]["schemas"]
    paths = schema["paths"]

    list_schema = paths["/api/v1/organizations/{organization_id}/operations/events/"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    detail_schema = paths[
        "/api/v1/organizations/{organization_id}/operations/events/{reservation_id}/"
    ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert list_schema == {"$ref": "#/components/schemas/EventListResponse"}
    assert detail_schema == {"$ref": "#/components/schemas/OperationEventDetail"}

    historical_actor = components["HistoricalActor"]
    assert set(historical_actor["properties"]) == HISTORICAL_ACTOR_FIELDS
    assert set(historical_actor["required"]) == HISTORICAL_ACTOR_FIELDS
    assert not (set(historical_actor["properties"]) & FORBIDDEN_HISTORICAL_ACTOR_FIELDS)
    assert "role" in components["ResponsibleMembership"]["properties"]

    contact = components["OperationalContact"]
    assert set(contact["properties"]) == {"display_name", "phone_e164"}
    assert contact["required"] == ["display_name"]
    assert "phone_e164" not in contact["required"]

    assert set(components["OperationPreparationStatus"]["enum"]) == {
        "preparing",
        "ready",
        "in_progress",
        "completed",
        "cancelled",
    }
    assert set(components["OperationItemStatus"]["enum"]) == {
        "pending",
        "in_progress",
        "blocked",
        "completed",
        "not_applicable",
    }
    assert components["EventListResponse"]["properties"]["results"]["type"] == "array"
    assert "next_cursor" in components["EventListResponse"]["required"]
    assert "operational_notes" not in components["PreparationSummary"]["properties"]
    assert "operational_notes" in components["PreparationDetail"]["properties"]
    assert components["OperationsErrorResponse"]["properties"]["error"] == {
        "$ref": "#/components/schemas/OperationsErrorDetail"
    }
    error_detail = components["OperationsErrorDetail"]
    assert "fields" in error_detail["properties"]
    error_code_ref = error_detail["properties"]["code"]["$ref"]
    error_codes = components[error_code_ref.rsplit("/", maxsplit=1)[-1]]["enum"]
    assert "invalid_request" in error_codes


@pytest.mark.django_db
def test_invalidating_ready_item_is_one_atomic_aggregate_revision() -> None:
    owner = _user("operations-reopen@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones reopen")
    reservation = _confirmed(owner, creation.organization.pk)
    reservation_id = UUID(str(reservation["id"]))
    detail = read_event(owner, creation.organization.pk, reservation_id=reservation_id)
    assign_preparation(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        revision=detail["preparation"]["revision"],
        responsible_membership_id=creation.owner_membership.pk,
    )
    revision = _resolve_all(owner, creation.organization.pk, reservation_id)
    ready = mark_ready(
        owner, creation.organization.pk, reservation_id=reservation_id, revision=revision
    )
    item = ready["preparation"]["items"][0]
    before = ready["preparation"]["revision"]
    reopened = update_item(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        item_id=item["id"],
        revision=item["revision"],
        values={"status": "pending"},
    )
    assert reopened["preparation"] == {"status": "preparing", "revision": before + 1}
    assert "resolved_at" not in reopened["item"]
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.OPERATION_READ):
        transition = PreparationTransition.objects.get(
            preparation_id=reservation_id,
            cause=PreparationTransition.Cause.CHECKLIST_REOPENED,
        )
        assert transition.preparation_revision == before + 1


@pytest.mark.django_db
def test_item_reordering_keeps_contiguous_order_and_one_aggregate_revision() -> None:
    owner = _user("operations-order@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones order")
    reservation = _confirmed(owner, creation.organization.pk)
    reservation_id = UUID(str(reservation["id"]))
    detail = read_event(owner, creation.organization.pk, reservation_id=reservation_id)
    before = detail["preparation"]["revision"]
    target = detail["preparation"]["items"][1]

    created, was_created = create_item(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        client_request_id=UUID("00000000-0000-0000-0000-000000000052"),
        values={
            "title": "Verificación libre",
            "section": "definitions",
            "is_required": False,
            "notes": "",
        },
        place_before_item_id=target["id"],
    )
    assert was_created
    assert created["preparation_revision"] == before + 1
    assert created["item"]["position"] == 2

    reordered = update_item(
        owner,
        creation.organization.pk,
        reservation_id=reservation_id,
        item_id=created["item"]["id"],
        revision=created["item"]["revision"],
        values={},
        place_before_item_id=None,
    )
    assert reordered["preparation_revision"] == before + 2
    current = read_event(owner, creation.organization.pk, reservation_id=reservation_id)
    positions = [item["position"] for item in current["preparation"]["items"]]
    assert positions == list(range(1, 9))
    assert current["preparation"]["items"][-1]["id"] == created["item"]["id"]


@pytest.mark.django_db
def test_commercial_cancellation_closes_preparation_and_rejects_after_start() -> None:
    owner = _user("operations-cancel@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones cancel")
    reservation = _confirmed(owner, creation.organization.pk)
    cancelled = cancel_reservation(
        owner,
        creation.organization.pk,
        reservation_id=reservation["id"],
        reason="Evento cancelado por cliente",
    )
    assert cancelled["status"] == "cancelled"
    detail = read_event(owner, creation.organization.pk, reservation_id=reservation["id"])
    assert detail["preparation"]["status"] == "cancelled"
    assert "phone_e164" not in detail["contact"]

    second = _confirmed(owner, creation.organization.pk, days=40, phone="0981234567")
    second_id = UUID(str(second["id"]))
    current = read_event(owner, creation.organization.pk, reservation_id=second_id)
    assign_preparation(
        owner,
        creation.organization.pk,
        reservation_id=second_id,
        revision=current["preparation"]["revision"],
        responsible_membership_id=creation.owner_membership.pk,
    )
    revision = _resolve_all(owner, creation.organization.pk, second_id)
    ready = mark_ready(owner, creation.organization.pk, reservation_id=second_id, revision=revision)
    cancel_reservation(
        owner,
        creation.organization.pk,
        reservation_id=second_id,
        reason="Cancelación desde listo",
    )
    assert (
        read_event(owner, creation.organization.pk, reservation_id=second_id)["preparation"][
            "status"
        ]
        == "cancelled"
    )

    third = _confirmed(owner, creation.organization.pk, days=60, phone="0971234567")
    third_id = UUID(str(third["id"]))
    current = read_event(owner, creation.organization.pk, reservation_id=third_id)
    assign_preparation(
        owner,
        creation.organization.pk,
        reservation_id=third_id,
        revision=current["preparation"]["revision"],
        responsible_membership_id=creation.owner_membership.pk,
    )
    revision = _resolve_all(owner, creation.organization.pk, third_id)
    ready = mark_ready(owner, creation.organization.pk, reservation_id=third_id, revision=revision)
    started = start_event(
        owner,
        creation.organization.pk,
        reservation_id=third_id,
        revision=ready["preparation"]["revision"],
    )
    with pytest.raises(CommercialError, match="ejecución") as caught:
        cancel_reservation(
            owner,
            creation.organization.pk,
            reservation_id=third_id,
            reason="Cancelación tardía",
        )
    assert caught.value.code == "operation_already_started"
    complete_event(
        owner,
        creation.organization.pk,
        reservation_id=third_id,
        revision=started["preparation"]["revision"],
    )
    with pytest.raises(CommercialError) as completed_caught:
        cancel_reservation(
            owner,
            creation.organization.pk,
            reservation_id=third_id,
            reason="Corrección posterior",
        )
    assert completed_caught.value.code == "operation_already_completed"


@pytest.mark.django_db
def test_role_matrix_finance_denied_commercial_read_only_operations_manage() -> None:
    owner = _user("operations-roles-owner@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones roles")
    reservation = _confirmed(owner, creation.organization.pk)
    finance = _user("operations-finance@example.com")
    add_membership(
        organization_id=creation.organization.pk,
        user_id=finance.pk,
        role=Membership.Role.FINANCE,
    )
    commercial = _user("operations-commercial@example.com")
    add_membership(
        organization_id=creation.organization.pk,
        user_id=commercial.pk,
        role=Membership.Role.COMMERCIAL,
    )
    operations = _user("operations-user@example.com")
    operations_membership = add_membership(
        organization_id=creation.organization.pk,
        user_id=operations.pk,
        role=Membership.Role.OPERATIONS,
    )
    with pytest.raises(AuthorizationDenied):
        read_event(finance, creation.organization.pk, reservation_id=reservation["id"])
    commercial_detail = read_event(
        commercial, creation.organization.pk, reservation_id=reservation["id"]
    )
    assigned = assign_preparation(
        operations,
        creation.organization.pk,
        reservation_id=reservation["id"],
        revision=commercial_detail["preparation"]["revision"],
        responsible_membership_id=operations_membership.pk,
    )
    assert assigned["preparation"]["responsible"]["role"] == "operations"


@pytest.mark.django_db
def test_operations_http_detail_csrf_and_cross_tenant_are_backend_enforced() -> None:
    owner = _user("operations-http@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones HTTP")
    reservation = _confirmed(owner, creation.organization.pk)
    foreign_owner = _user("operations-http-foreign@example.com")
    foreign = create_organization(owner_user_id=foreign_owner.pk, name="Operaciones foreign")
    client = Client(enforce_csrf_checks=True)
    login_csrf = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
    login = client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": owner.email, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=login_csrf,
    )
    assert login.status_code == 200
    mutation_csrf = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
    base = f"/api/v1/organizations/{creation.organization.pk}/operations"

    capabilities = client.get(f"{base}/capabilities/")
    assert capabilities.status_code == 200
    assert set(capabilities.json()["capabilities"]) == {
        "operation:read",
        "operation:manage",
        "operation:execute",
    }
    detail = client.get(f"{base}/events/{reservation['id']}/")
    assert detail.status_code == 200
    assert detail.json()["contact"]["phone_e164"] == "+593991234567"
    event_list = client.get(f"{base}/events/")
    assert event_list.status_code == 200
    assert "operational_notes" not in event_list.json()["results"][0]["preparation"]
    invalid_request = client.get(f"{base}/events/?page_size=0")
    assert invalid_request.status_code == 400
    assert invalid_request.json() == {
        "error": {
            "code": "invalid_request",
            "message": "La solicitud no es válida.",
            "fields": {"page_size": ["El valor está por debajo del mínimo permitido."]},
        }
    }
    invalid_body = client.patch(
        f"{base}/events/{reservation['id']}/preparation/",
        data=json.dumps({"revision": "incorrecta"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=mutation_csrf,
    )
    assert invalid_body.status_code == 400
    assert invalid_body.json()["error"] == {
        "code": "invalid_request",
        "message": "La solicitud no es válida.",
        "fields": {
            "revision": ["El valor no es válido."],
            "operational_notes": ["Este campo es obligatorio."],
        },
    }
    missing_csrf = client.patch(
        f"{base}/events/{reservation['id']}/preparation/",
        data=json.dumps({"revision": 1, "operational_notes": "Preparación prioritaria"}),
        content_type="application/json",
    )
    assert missing_csrf.status_code == 403
    csrf_token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
    updated = client.patch(
        f"{base}/events/{reservation['id']}/preparation/",
        data=json.dumps({"revision": 1, "operational_notes": "Preparación prioritaria"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert updated.status_code == 200
    assert updated.json()["preparation"]["revision"] == 2
    assigned = client.post(
        f"{base}/events/{reservation['id']}/assign/",
        data=json.dumps(
            {
                "revision": 2,
                "responsible_membership_id": str(creation.owner_membership.pk),
            }
        ),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert assigned.status_code == 200
    preparation_revision = assigned.json()["preparation"]["revision"]
    for item in assigned.json()["preparation"]["items"]:
        changed = client.patch(
            f"{base}/events/{reservation['id']}/items/{item['id']}/",
            data=json.dumps({"revision": item["revision"], "status": "completed"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        assert changed.status_code == 200
        preparation_revision = changed.json()["preparation_revision"]
    ready = client.post(
        f"{base}/events/{reservation['id']}/ready/",
        data=json.dumps({"revision": preparation_revision}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert ready.status_code == 200
    started = client.post(
        f"{base}/events/{reservation['id']}/start/",
        data=json.dumps({"revision": ready.json()["preparation"]["revision"]}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert started.status_code == 200
    completed = client.post(
        f"{base}/events/{reservation['id']}/complete/",
        data=json.dumps({"revision": started.json()["preparation"]["revision"]}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert completed.status_code == 200
    assert completed.json()["preparation"]["status"] == "completed"
    assert "phone_e164" not in completed.json()["contact"]
    hidden = client.get(
        f"/api/v1/organizations/{foreign.organization.pk}/operations/events/{reservation['id']}/"
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "resource_not_available"


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_postgresql_guardian_rejects_legacy_direct_update_bulk_and_uncoordinated_cancel() -> None:
    owner = _user("operations-guardian@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones guardian")
    organization_id = creation.organization.pk
    reservation = _accepted(owner, organization_id)
    confirmation = {
        "status": Reservation.Status.CONFIRMED,
        "confirmation_kind": Reservation.ConfirmationKind.EXTERNAL_DEPOSIT,
        "recognized_deposit_amount": Decimal("100.00"),
        "deposit_reported_at": timezone.now(),
        "deposit_reference": "Constancia externa",
        "confirmed_at": timezone.now(),
        "confirmed_by_membership_id": creation.owner_membership.pk,
    }

    with (
        pytest.raises(DatabaseError),
        authorized_tenant_scope(owner, organization_id, Capability.RESERVATION_CONFIRM),
    ):
        Reservation.objects.filter(pk=reservation["id"]).update(**confirmation)

    with (
        pytest.raises(DatabaseError),
        authorized_tenant_scope(owner, organization_id, Capability.RESERVATION_CONFIRM),
    ):
        instance = Reservation.objects.get(pk=reservation["id"])
        for field, value in confirmation.items():
            setattr(instance, field, value)
        Reservation.objects.bulk_update([instance], list(confirmation))

    with (
        pytest.raises(DatabaseError),
        authorized_tenant_scope(owner, organization_id, Capability.RESERVATION_CONFIRM),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            UPDATE commercial_reservation
            SET status = 'confirmed', confirmation_kind = 'external_deposit',
                recognized_deposit_amount = 100.00, deposit_reported_at = now(),
                deposit_reference = 'Constancia externa', confirmed_at = now(),
                confirmed_by_membership_id = %s
            WHERE organization_id = %s AND id = %s
            """,
            (creation.owner_membership.pk, organization_id, reservation["id"]),
        )

    confirmed = confirm_reservation(
        owner,
        organization_id,
        reservation_id=reservation["id"],
        kind="external_deposit",
        recognized_amount=Decimal("100.00"),
        reported_at=timezone.now(),
        reference="Constancia externa",
    )
    with (
        pytest.raises(DatabaseError),
        authorized_tenant_scope(owner, organization_id, Capability.RESERVATION_CANCEL),
    ):
        Reservation.objects.filter(pk=confirmed["id"]).update(
            status=Reservation.Status.CANCELLED,
            cancelled_at=timezone.now(),
            cancelled_by_membership_id=creation.owner_membership.pk,
            cancellation_reason="Ruta antigua",
        )

    assert (
        read_event(owner, organization_id, reservation_id=confirmed["id"])["preparation"]["status"]
        == "preparing"
    )


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_operations_rls_tenant_foreign_keys_bulk_and_privileges_are_fail_closed() -> None:
    first_owner = _user("operations-rls-first@example.com")
    first = create_organization(owner_user_id=first_owner.pk, name="Operaciones RLS first")
    second_owner = _user("operations-rls-second@example.com")
    second = create_organization(owner_user_id=second_owner.pk, name="Operaciones RLS second")
    first_reservation = _confirmed(first_owner, first.organization.pk)
    second_reservation = _confirmed(second_owner, second.organization.pk, phone="0987654321")

    assert EventPreparation.objects.count() == 0
    with authorized_tenant_scope(second_owner, second.organization.pk, Capability.OPERATION_READ):
        foreign_preparation = EventPreparation.objects.get(reservation_id=second_reservation["id"])
    foreign_preparation.operational_notes = "Cruce no autorizado"
    with authorized_tenant_scope(first_owner, first.organization.pk, Capability.OPERATION_MANAGE):
        assert (
            EventPreparation.objects.bulk_update([foreign_preparation], ["operational_notes"]) == 0
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            PreparationItem.objects.bulk_create(
                [
                    PreparationItem(
                        organization_id=first.organization.pk,
                        preparation_id=second_reservation["id"],
                        client_request_id=uuid4(),
                        section=PreparationItem.Section.SETUP,
                        position=8,
                        title="Cruce tenant",
                        is_required=False,
                    )
                ]
            )
        assert (
            EventPreparation.objects.get(reservation_id=first_reservation["id"]).organization_id
            == first.organization.pk
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = ANY(%s)
            ORDER BY relname
            """,
            (
                [
                    "operations_eventpreparation",
                    "operations_preparationitem",
                    "operations_preparationtransition",
                ],
            ),
        )
        metadata = cursor.fetchall()
        cursor.execute(
            """
            SELECT has_table_privilege(
                'claridez_app', 'operations_eventpreparation', 'DELETE'
            )
            """
        )
        delete_privilege = cursor.fetchone()
    assert len(metadata) == 3
    assert all(enabled and forced for _, enabled, forced in metadata)
    assert delete_privilege == (False,)
    postcheck = verify_operations_cutover()
    assert postcheck["status"] == "ok"
    assert postcheck["organizations_checked"] == 2
    assert postcheck["reservations_checked"] == 2


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_concurrent_item_edits_have_one_optimistic_winner() -> None:
    owner = _user("operations-concurrent@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones concurrent")
    reservation = _confirmed(owner, creation.organization.pk)
    detail = read_event(owner, creation.organization.pk, reservation_id=reservation["id"])
    item = detail["preparation"]["items"][0]
    start = Event()

    def worker(note: str) -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            start.wait(timeout=5)
            update_item(
                actor,
                creation.organization.pk,
                reservation_id=reservation["id"],
                item_id=item["id"],
                revision=item["revision"],
                values={"notes": note},
            )
            return "ok"
        except OperationsError as caught:
            return caught.code
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, note) for note in ("Primera", "Segunda")]
        start.set()
        results = [future.result(timeout=10) for future in futures]
    assert sorted(results) == ["ok", "stale_revision"]


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_cutover_table_lock_orders_existing_and_new_reservation_writers() -> None:
    owner = _user("operations-cutover-lock@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones cutover lock")
    reservation = _accepted(owner, creation.organization.pk)
    before_updated = Event()
    release_before = Event()
    lock_acquired = Event()
    release_lock = Event()
    after_started = Event()
    after_done = Event()

    def writer_before() -> None:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            with (
                authorized_tenant_scope(actor, creation.organization.pk, Capability.SALES_MANAGE),
                connections["default"].cursor() as cursor,
            ):
                cursor.execute(
                    "UPDATE commercial_reservation SET updated_at = updated_at WHERE id = %s",
                    (reservation["id"],),
                )
                before_updated.set()
                assert release_before.wait(timeout=5)
        finally:
            connections["default"].close()

    def locker() -> None:
        close_old_connections()
        try:
            with transaction.atomic(using="default"), connections["default"].cursor() as cursor:
                cursor.execute("LOCK TABLE commercial_reservation IN SHARE ROW EXCLUSIVE MODE")
                lock_acquired.set()
                assert release_lock.wait(timeout=5)
        finally:
            connections["default"].close()

    def writer_after() -> None:
        close_old_connections()
        try:
            actor = User.objects.get(pk=owner.pk)
            with authorized_tenant_scope(actor, creation.organization.pk, Capability.SALES_MANAGE):
                after_started.set()
                with connections["default"].cursor() as cursor:
                    cursor.execute(
                        "UPDATE commercial_reservation SET updated_at = updated_at WHERE id = %s",
                        (reservation["id"],),
                    )
            after_done.set()
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=3) as executor:
        before_future = executor.submit(writer_before)
        assert before_updated.wait(timeout=5)
        lock_future = executor.submit(locker)
        assert not lock_acquired.wait(timeout=0.2)
        release_before.set()
        before_future.result(timeout=5)
        assert lock_acquired.wait(timeout=5)
        after_future = executor.submit(writer_after)
        assert after_started.wait(timeout=5)
        assert not after_done.wait(timeout=0.2)
        release_lock.set()
        lock_future.result(timeout=5)
        after_future.result(timeout=5)
    assert after_done.is_set()


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_operations_backfill_is_complete_deterministic_and_reversible() -> None:
    owner = _user("operations-backfill@example.com")
    creation = create_organization(owner_user_id=owner.pk, name="Operaciones backfill")
    first = _accepted(owner, creation.organization.pk, days=30)
    confirmed = confirm_reservation(
        owner,
        creation.organization.pk,
        reservation_id=first["id"],
        kind="external_deposit",
        recognized_amount=Decimal("100.00"),
        reported_at=timezone.now(),
        reference="Backfill confirmado",
    )
    second = _accepted(owner, creation.organization.pk, days=60, phone="0981111111")
    second_confirmed = confirm_reservation(
        owner,
        creation.organization.pk,
        reservation_id=second["id"],
        kind="external_deposit",
        recognized_amount=Decimal("100.00"),
        reported_at=timezone.now(),
        reference="Backfill cancelado",
    )
    cancelled = cancel_reservation(
        owner,
        creation.organization.pk,
        reservation_id=second_confirmed["id"],
        reason="Cancelada antes de 5.2",
    )
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("operations", None)])
        executor = MigrationExecutor(connection)
        executor.migrate([("operations", "0002_commercial_operations_guardian")])

        def snapshot() -> tuple[list[tuple[UUID, str, int]], list[UUID]]:
            with authorized_tenant_scope(
                owner, creation.organization.pk, Capability.OPERATION_READ
            ):
                preparations = list(
                    EventPreparation.objects.order_by("reservation_id").values_list(
                        "reservation_id", "status", "revision"
                    )
                )
                item_ids = list(PreparationItem.objects.order_by("id").values_list("id", flat=True))
            return preparations, item_ids

        first_snapshot = snapshot()
        assert first_snapshot[0] == sorted(
            [
                (UUID(str(confirmed["id"])), "preparing", 1),
                (UUID(str(cancelled["id"])), "cancelled", 2),
            ]
        )
        assert len(first_snapshot[1]) == 14

        MigrationExecutor(connection).migrate([("operations", None)])
        MigrationExecutor(connection).migrate(
            [("operations", "0002_commercial_operations_guardian")]
        )
        assert snapshot() == first_snapshot
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
