from __future__ import annotations

import ast
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError, transaction
from django.test import Client
from django.utils import timezone

from claridez.catalog.services import create_event_type, list_event_types
from claridez.commercial.errors import CommercialError
from claridez.commercial.models import EventRequestHistory
from claridez.commercial.services import create_event_request
from claridez.crm.errors import CrmError
from claridez.crm.models import FollowUpTask, Interaction
from claridez.crm.services import (
    create_task,
    crm_capabilities,
    list_interactions,
    list_opportunities,
    person_overview,
    record_interaction,
    update_task,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.configuration_services import list_venues
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.models import Membership
from claridez.organizations.services import add_membership, create_organization
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.people import services as people_services
from claridez.people.errors import PeopleError
from claridez.people.models import ConsentEvent, PersonContactAlias, PersonMerge

PASSWORD = "p7-crm-validation-password-42!"


def _absolute_imports(package: Path) -> set[str]:
    imports: set[str] = set()
    for module in package.rglob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.add(node.module)
    return imports


def test_p7_module_dependencies_are_acyclic_and_use_people_public_port() -> None:
    packages = Path(__file__).resolve().parents[1] / "src" / "claridez"
    people_imports = _absolute_imports(packages / "people")
    commercial_imports = _absolute_imports(packages / "commercial")
    crm_imports = _absolute_imports(packages / "crm")

    assert not any(
        name.startswith(("claridez.commercial", "claridez.crm")) for name in people_imports
    )
    assert not any(name.startswith("claridez.crm") for name in commercial_imports)
    assert not any(
        name.startswith("claridez.people.services") for name in commercial_imports | crm_imports
    )


def _user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _owner(slug: str) -> tuple[User, Any]:
    owner = _user(f"{slug}@example.com")
    return owner, create_organization(owner_user_id=owner.pk, name=f"Organización {slug}")


def _person(
    actor: User,
    organization_id: UUID,
    *,
    phone: str,
    name: str,
    email: str | None = None,
) -> dict[str, Any]:
    return people_services.create_person(
        actor,
        organization_id,
        full_name=name,
        phone=phone,
        email=email,
        origin="referral",
        origin_detail="Prueba sintética P7",
    )


def _request(
    actor: User,
    organization_id: UUID,
    person_id: UUID | str,
    *,
    days: int,
) -> dict[str, Any]:
    event_type = next(
        (row for row in list_event_types(actor, organization_id) if row["name"] == "Boda"),
        None,
    )
    if event_type is None:
        event_type = create_event_type(actor, organization_id, name="Boda")
    space_id = list_venues(actor, organization_id)[0]["spaces"][0]["id"]
    starts_at = timezone.now() + timedelta(days=days)
    return create_event_request(
        actor,
        organization_id,
        person_id=person_id,
        event_type_id=event_type["id"],
        space_id=space_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=5),
        estimated_guests=80,
        general_need="Celebración completa",
        notes="",
        origin="referral",
        origin_detail="Seguimiento P7",
    )


@pytest.mark.django_db
def test_crm_capabilities_are_explicit_and_sales_read_does_not_grant_crm() -> None:
    owner, creation = _owner("p7-capabilities")
    organization_id = creation.organization.pk
    commercial = _user("p7-commercial@example.com")
    operations = _user("p7-operations@example.com")
    administrator = _user("p7-administrator@example.com")
    add_membership(
        organization_id=organization_id, user_id=commercial.pk, role=Membership.Role.COMMERCIAL
    )
    add_membership(
        organization_id=organization_id, user_id=operations.pk, role=Membership.Role.OPERATIONS
    )
    add_membership(
        organization_id=organization_id,
        user_id=administrator.pk,
        role=Membership.Role.ADMINISTRATOR,
    )
    person = _person(
        owner,
        organization_id,
        phone="0991000001",
        name="Interesada P7",
        email="interesada@example.com",
    )
    _request(owner, organization_id, person["id"], days=20)

    assert len(list_opportunities(commercial, organization_id)) == 1
    with pytest.raises(AuthorizationDenied):
        list_opportunities(operations, organization_id)
    with pytest.raises(AuthorizationDenied):
        list_interactions(operations, organization_id)

    commercial_capabilities = set(crm_capabilities(commercial, organization_id))
    assert {
        Capability.SALES_READ.value,
        Capability.PERSON_READ.value,
        Capability.INTERACTION_READ.value,
        Capability.INTERACTION_RECORD.value,
        Capability.TASK_MANAGE.value,
        Capability.CONSENT_READ.value,
        Capability.CONSENT_MANAGE.value,
    } <= commercial_capabilities
    assert Capability.PERSON_MERGE.value not in commercial_capabilities
    assert Capability.PERSON_MERGE in capabilities_for_role(Membership.Role.OWNER)
    assert Capability.PERSON_MERGE in capabilities_for_role(Membership.Role.ADMINISTRATOR)
    assert Capability.PERSON_READ not in capabilities_for_role(Membership.Role.OPERATIONS)


@pytest.mark.django_db
def test_logical_merge_resolves_aliases_history_and_conservative_consent() -> None:
    owner, creation = _owner("p7-merge")
    organization_id = creation.organization.pk
    source = _person(
        owner,
        organization_id,
        phone="0991000002",
        name="Duplicada histórica",
        email="duplicada@example.com",
    )
    source = people_services.update_person(
        owner,
        organization_id,
        person_id=source["id"],
        revision=source["revision"],
        changes={"phone": "0991000003"},
    )
    target = _person(
        owner,
        organization_id,
        phone="0991000004",
        name="Persona canónica",
        email="canonica@example.com",
    )
    source_request = _request(owner, organization_id, source["id"], days=25)
    _request(owner, organization_id, target["id"], days=26)
    original_interaction = record_interaction(
        owner,
        organization_id,
        person_id=source["id"],
        event_request_id=source_request["id"],
        channel="phone_call",
        direction="outbound",
        occurred_at=timezone.now(),
        summary="Se confirmó únicamente la preferencia de horario.",
    )
    create_task(
        owner,
        organization_id,
        person_id=source["id"],
        event_request_id=source_request["id"],
        title="Confirmar número de invitados",
        due_at=timezone.now() + timedelta(days=1),
        next_contact_at=timezone.now() + timedelta(hours=4),
    )
    people_services.record_consent(
        owner,
        organization_id,
        person_id=source["id"],
        purpose="seguimiento_comercial",
        channel="whatsapp",
        event_type="grant",
        decision="granted",
        source="registro_manual",
        occurred_at=timezone.now() - timedelta(days=2),
        evidence_reference="Formulario sintético 001",
    )
    people_services.record_consent(
        owner,
        organization_id,
        person_id=target["id"],
        purpose="seguimiento_comercial",
        channel="whatsapp",
        event_type="revoke",
        decision="revoked",
        source="registro_manual",
        occurred_at=timezone.now() - timedelta(days=1),
        evidence_reference="Solicitud sintética 002",
    )

    key = uuid4()
    merged = people_services.merge_people(
        owner,
        organization_id,
        source_person_id=source["id"],
        target_person_id=target["id"],
        source_revision=source["revision"],
        target_revision=target["revision"],
        reason="Registros duplicados confirmados por el responsable.",
        idempotency_key=key,
    )
    repeated = people_services.merge_people(
        owner,
        organization_id,
        source_person_id=source["id"],
        target_person_id=target["id"],
        source_revision=source["revision"],
        target_revision=target["revision"],
        reason="Registros duplicados confirmados por el responsable.",
        idempotency_key=key,
    )
    assert repeated["id"] == merged["id"]
    with authorized_tenant_scope(owner, organization_id, Capability.PERSON_READ):
        assert PersonMerge.objects.count() == 1

    resolved = people_services.read_person(owner, organization_id, person_id=source["id"])
    assert resolved["canonical_id"] == target["id"]
    assert resolved["requested_id"] == source["id"]
    assert set(resolved["merged_person_ids"]) == {source["id"], target["id"]}
    assert {(alias["kind"], alias["value"]) for alias in resolved["aliases"]} >= {
        ("phone", "+593991000002"),
        ("phone", "+593991000003"),
        ("email", "duplicada@example.com"),
    }
    assert [
        row["id"] for row in people_services.list_people(owner, organization_id, query="0991000002")
    ] == [target["id"]]

    interactions = list_interactions(owner, organization_id, person_id=target["id"])
    assert [row["id"] for row in interactions] == [original_interaction["id"]]
    consents = people_services.list_consents(owner, organization_id, person_id=source["id"])
    assert len(consents["events"]) == 2
    assert consents["effective"] == (
        {
            "purpose": "seguimiento_comercial",
            "channel": "whatsapp",
            "decision": "revoked",
            "event_id": consents["events"][1]["id"],
            "occurred_at": consents["events"][1]["occurred_at"],
        },
    )
    overview = person_overview(owner, organization_id, person_id=source["id"])
    assert len(overview["opportunities"]) == 2
    assert len(overview["tasks"]) == 1

    with pytest.raises(CommercialError) as merged_write:
        _request(owner, organization_id, source["id"], days=30)
    assert merged_write.value.code == "person_merged"
    with pytest.raises(PeopleError) as merged_update:
        people_services.update_person(
            owner,
            organization_id,
            person_id=source["id"],
            revision=source["revision"],
            changes={"full_name": "No se puede cambiar"},
        )
    assert merged_update.value.code == "person_merged"
    with pytest.raises(PeopleError) as cycle:
        people_services.merge_people(
            owner,
            organization_id,
            source_person_id=target["id"],
            target_person_id=source["id"],
            source_revision=target["revision"],
            target_revision=source["revision"],
            reason="Intento de ciclo.",
            idempotency_key=uuid4(),
        )
    assert cycle.value.code == "target_not_canonical"


@pytest.mark.django_db
def test_interactions_are_corrected_append_only_and_tasks_keep_history() -> None:
    owner, creation = _owner("p7-follow-up")
    organization_id = creation.organization.pk
    person = _person(
        owner,
        organization_id,
        phone="0991000005",
        name="Seguimiento P7",
    )
    event_request = _request(owner, organization_id, person["id"], days=35)
    original = record_interaction(
        owner,
        organization_id,
        person_id=person["id"],
        event_request_id=event_request["id"],
        channel="whatsapp",
        direction="inbound",
        occurred_at=timezone.now(),
        summary="Indicó disponibilidad durante la tarde.",
    )
    correction = record_interaction(
        owner,
        organization_id,
        person_id=person["id"],
        event_request_id=event_request["id"],
        channel="whatsapp",
        direction="inbound",
        occurred_at=timezone.now(),
        summary="Corrección: indicó disponibilidad durante la mañana.",
        correction_of_id=original["id"],
    )
    assert correction["correction_of_id"] == original["id"]
    with (
        authorized_tenant_scope(owner, organization_id, Capability.INTERACTION_RECORD),
        pytest.raises(DatabaseError),
        transaction.atomic(),
    ):
        Interaction.objects.filter(pk=original["id"]).update(summary="Texto sustituido")

    task = create_task(
        owner,
        organization_id,
        person_id=person["id"],
        event_request_id=event_request["id"],
        title="Llamar para confirmar horario",
        due_at=timezone.now() + timedelta(days=2),
        next_contact_at=timezone.now() + timedelta(days=1),
    )
    assert [row["kind"] for row in task["history"]] == ["created"]
    completed = update_task(
        owner,
        organization_id,
        task_id=task["id"],
        revision=task["revision"],
        changes={"status": "completed"},
    )
    assert completed["status"] == FollowUpTask.Status.COMPLETED
    assert [row["kind"] for row in completed["history"]] == ["created", "completed"]
    with pytest.raises(CrmError) as stale:
        update_task(
            owner,
            organization_id,
            task_id=task["id"],
            revision=task["revision"],
            changes={"title": "Cambio obsoleto"},
        )
    assert stale.value.code == "stale_revision"
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        history = list(
            EventRequestHistory.objects.filter(event_request_id=event_request["id"])
            .order_by("created_at")
            .values_list("kind", "provenance", "actor_membership_id")
        )
    assert history == [("created", "database", creation.owner_membership.pk)]


@pytest.mark.django_db
def test_merge_http_requires_session_csrf_admin_capabilities_and_current_revisions() -> None:
    owner, creation = _owner("p7-http")
    organization_id = creation.organization.pk
    administrator = _user("p7-http-administrator@example.com")
    add_membership(
        organization_id=organization_id,
        user_id=administrator.pk,
        role=Membership.Role.ADMINISTRATOR,
    )
    source = _person(
        owner,
        organization_id,
        phone="0991000006",
        name="Origen HTTP",
    )
    target = _person(
        owner,
        organization_id,
        phone="0991000007",
        name="Destino HTTP",
    )
    path = f"/api/v1/organizations/{organization_id}/people/merge/"
    payload = {
        "source_person_id": str(source["id"]),
        "target_person_id": str(target["id"]),
        "source_revision": source["revision"],
        "target_revision": target["revision"],
        "reason": "Duplicación confirmada por administración.",
        "idempotency_key": str(uuid4()),
    }
    anonymous = Client(enforce_csrf_checks=True)
    anonymous_response = anonymous.post(
        path, data=json.dumps(payload), content_type="application/json"
    )
    assert anonymous_response.status_code == 403
    anonymous_token = str(anonymous.get("/api/v1/auth/csrf/").json()["csrf_token"])
    unauthenticated = anonymous.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=anonymous_token,
    )
    assert unauthenticated.status_code == 401

    client = Client(enforce_csrf_checks=True)
    login_token = str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])
    login = client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": administrator.email, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=login_token,
    )
    assert login.status_code == 200
    missing_csrf = client.post(path, data=json.dumps(payload), content_type="application/json")
    assert missing_csrf.status_code == 403
    token = str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])
    response = client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200
    assert response.json()["canonical_person_id"] == str(target["id"])

    repeated = client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == response.json()["id"]

    with authorized_tenant_scope(owner, organization_id, Capability.PERSON_READ):
        assert PersonContactAlias.objects.filter(source_person_id=source["id"]).count() == 1
        assert ConsentEvent.objects.count() == 0
