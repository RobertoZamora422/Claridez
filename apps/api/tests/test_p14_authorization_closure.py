from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.test import Client
from django.utils import timezone

from claridez.application.communications import retry_delivery
from claridez.application.reminders import request_reminder
from claridez.communications.errors import CommunicationsError
from claridez.communications.models import (
    Channel,
    CommunicationIntent,
    CommunicationOutbox,
    LogicalMessage,
    Purpose,
)
from claridez.communications.services import (
    create_template,
    create_template_version,
    internal_preference_action,
    list_deliveries,
    list_preferences,
    list_templates,
    publish_template,
    request_intent,
)
from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied
from claridez.organizations.models import Membership
from claridez.organizations.public import organization_is_active_for_external_entry
from claridez.organizations.services import add_membership
from claridez.organizations.tenant_scope import (
    ExternalTenantAuthorization,
    authorized_tenant_scope,
    external_tenant_scope,
)
from claridez.portal.errors import PortalError
from claridez.portal.models import PortalLocator
from claridez.portal.security import digest, random_token
from claridez.portal.services import read_public_form, rotate_form_locator, submit_public_form
from tests.test_p14 import (
    PASSWORD,
    _organization,
    _portal_session_for_event,
    _published_form,
    _submission,
    _user,
)


def _role_user(creation: Any, *, role: Membership.Role, slug: str) -> User:
    user = _user(f"{slug}@example.com")
    add_membership(
        organization_id=creation.organization.pk,
        user_id=user.pk,
        role=role,
    )
    return user


def _published_template(owner: User, creation: Any, *, name: str, purpose: str) -> UUID:
    created = create_template(
        owner,
        creation.organization.pk,
        name=name,
        channel=Channel.EMAIL,
        purpose=purpose,
        subject_template=name,
        body_template=f"Mensaje {name}",
        variable_names=[],
    )
    version_id = UUID(str(created["versions"][0]["id"]))
    publish_template(owner, creation.organization.pk, version_id=version_id)
    return version_id


def _dead_delivery(
    owner: User,
    creation: Any,
    *,
    person_id: UUID,
    purpose: str,
    aggregate_type: str,
    aggregate_id: UUID,
    source_version: int,
    template_version_id: UUID,
    key: str,
) -> UUID:
    with authorized_tenant_scope(owner, creation.organization.pk, "communication_delivery:read"):
        intent = request_intent(
            creation.organization.pk,
            purpose=purpose,
            channel=Channel.EMAIL,
            person_id=person_id,
            template_version_id=template_version_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            variables={},
            idempotency_key=key,
            source_version=source_version,
        )
        message = LogicalMessage.objects.create(
            organization_id=creation.organization.pk,
            intent=intent,
            template_version_id=template_version_id,
            channel=Channel.EMAIL,
            recipient_fingerprint="a" * 64,
            resolved_variables={},
            template_sha256="b" * 64,
            final_sha256="c" * 64,
            status=LogicalMessage.Status.FAILED,
            failed_at=timezone.now(),
        )
        intent.state = CommunicationIntent.State.TERMINAL
        intent.save(update_fields=["state"])
        outbox = intent.outbox_entry
        outbox.state = CommunicationOutbox.State.CLAIMED
        outbox.claimed_by = "authorization-test"
        outbox.lease_expires_at = timezone.now()
        outbox.attempt_count = 1
        outbox.save(
            update_fields=[
                "state",
                "claimed_by",
                "lease_expires_at",
                "attempt_count",
                "updated_at",
            ]
        )
        outbox.message = message
        outbox.state = CommunicationOutbox.State.DEAD
        outbox.completed_at = timezone.now()
        outbox.save(update_fields=["message", "state", "completed_at", "updated_at"])
        return message.pk


@pytest.mark.django_db
def test_communications_scope_is_conjunctive_for_all_five_profiles() -> None:
    owner, creation = _organization("purpose-scope")
    administrator = _role_user(creation, role=Membership.Role.ADMINISTRATOR, slug="purpose-admin")
    commercial = _role_user(creation, role=Membership.Role.COMMERCIAL, slug="purpose-commercial")
    operations = _role_user(creation, role=Membership.Role.OPERATIONS, slug="purpose-operations")
    finance = _role_user(creation, role=Membership.Role.FINANCE, slug="purpose-finance")
    locator, form_version, _ = _published_form(owner, creation)
    captured = submit_public_form(
        locator,
        idempotency_key="purpose-scope-event",
        data=_submission(form_version),
    )
    event_request_id = UUID(str(captured["event_request_id"]))
    with authorized_tenant_scope(owner, creation.organization.pk, "sales:read"):
        event = form_version.submissions.get(event_request_reference=event_request_id)
        person_id = UUID(str(event.person_reference))

    service_version = _published_template(
        owner, creation, name="Ámbito comercial", purpose=Purpose.SERVICE_UPDATE
    )
    event_version = _published_template(
        owner, creation, name="Ámbito operativo", purpose=Purpose.EVENT_REMINDER
    )
    payment_created = create_template(
        owner,
        creation.organization.pk,
        name="Ámbito financiero",
        channel=Channel.EMAIL,
        purpose=Purpose.PAYMENT_REMINDER,
        subject_template="Cobro",
        body_template="Cobro pendiente",
        variable_names=[],
    )
    payment_version = UUID(str(payment_created["versions"][0]["id"]))

    with pytest.raises(CommunicationsError) as hidden_version:
        create_template_version(
            commercial,
            creation.organization.pk,
            template_id=UUID(str(payment_created["id"])),
            subject_template="Cambio indebido",
            body_template="Cambio indebido",
            variable_names=[],
        )
    assert hidden_version.value.code == "resource_not_available"
    with pytest.raises(CommunicationsError) as hidden_publish:
        publish_template(commercial, creation.organization.pk, version_id=payment_version)
    assert hidden_publish.value.code == "resource_not_available"
    publish_template(owner, creation.organization.pk, version_id=payment_version)

    service_message = _dead_delivery(
        owner,
        creation,
        person_id=person_id,
        purpose=Purpose.SERVICE_UPDATE,
        aggregate_type="event_request",
        aggregate_id=event_request_id,
        source_version=1,
        template_version_id=service_version,
        key="scope-service",
    )
    event_message = _dead_delivery(
        owner,
        creation,
        person_id=person_id,
        purpose=Purpose.EVENT_REMINDER,
        aggregate_type="scheduling_reservation",
        aggregate_id=uuid4(),
        source_version=1,
        template_version_id=event_version,
        key="scope-event",
    )
    payment_message = _dead_delivery(
        owner,
        creation,
        person_id=person_id,
        purpose=Purpose.PAYMENT_REMINDER,
        aggregate_type="receivable_obligation",
        aggregate_id=uuid4(),
        source_version=1,
        template_version_id=payment_version,
        key="scope-payment",
    )

    assert {item["purpose"] for item in list_deliveries(commercial, creation.organization.pk)} == {
        Purpose.SERVICE_UPDATE
    }
    assert {item["purpose"] for item in list_deliveries(operations, creation.organization.pk)} == {
        Purpose.EVENT_REMINDER
    }
    assert {item["purpose"] for item in list_deliveries(finance, creation.organization.pk)} == {
        Purpose.PAYMENT_REMINDER
    }
    assert len(list_deliveries(owner, creation.organization.pk)) == 3
    assert len(list_deliveries(administrator, creation.organization.pk)) == 3

    for actor, message_id in (
        (commercial, payment_message),
        (finance, event_message),
        (operations, service_message),
        (operations, payment_message),
    ):
        with pytest.raises(CommunicationsError) as opaque_retry:
            retry_delivery(
                actor,
                creation.organization.pk,
                message_id=message_id,
                reason="No pertenece al ámbito del perfil.",
            )
        assert opaque_retry.value.code == "resource_not_available"

    retry_delivery(
        owner,
        creation.organization.pk,
        message_id=service_message,
        reason="Procedencia comercial revalidada.",
    )
    administrator_message = _dead_delivery(
        owner,
        creation,
        person_id=person_id,
        purpose=Purpose.SERVICE_UPDATE,
        aggregate_type="event_request",
        aggregate_id=event_request_id,
        source_version=1,
        template_version_id=service_version,
        key="scope-service-admin",
    )
    retry_delivery(
        administrator,
        creation.organization.pk,
        message_id=administrator_message,
        reason="Administrador conserva alcance aprobado.",
    )

    with pytest.raises(AuthorizationDenied):
        request_reminder(
            commercial,
            creation.organization.pk,
            kind="payment",
            source_id=event_request_id,
            channel=Channel.EMAIL,
            template_version_id=payment_version,
            variables={},
            idempotency_key="commercial-payment-denied",
            not_before=timezone.now(),
        )
    with pytest.raises(CommunicationsError):
        request_reminder(
            commercial,
            creation.organization.pk,
            kind="document",
            source_id=event_request_id,
            channel=Channel.EMAIL,
            template_version_id=payment_version,
            variables={},
            idempotency_key="commercial-document-denied",
            not_before=timezone.now(),
        )
    with pytest.raises(AuthorizationDenied):
        request_reminder(
            finance,
            creation.organization.pk,
            kind="event",
            source_id=event_request_id,
            channel=Channel.EMAIL,
            template_version_id=event_version,
            variables={},
            idempotency_key="finance-event-denied",
            not_before=timezone.now(),
        )

    internal_preference_action(
        owner,
        creation.organization.pk,
        person_id=person_id,
        channel=Channel.EMAIL,
        purpose=Purpose.CLIENT_ACTION,
        suppress=True,
        reason="Preferencia comercial de prueba.",
    )
    internal_preference_action(
        owner,
        creation.organization.pk,
        person_id=person_id,
        channel=Channel.EMAIL,
        purpose=Purpose.PAYMENT_REMINDER,
        suppress=True,
        reason="Preferencia financiera de prueba.",
    )
    assert {item["purpose"] for item in list_preferences(finance, creation.organization.pk)} == {
        Purpose.PAYMENT_REMINDER
    }
    with pytest.raises(CommunicationsError):
        internal_preference_action(
            finance,
            creation.organization.pk,
            person_id=person_id,
            channel=Channel.EMAIL,
            purpose=Purpose.CLIENT_ACTION,
            suppress=True,
            reason="Finanzas no administra preferencias comerciales.",
        )
    with pytest.raises(CommunicationsError):
        internal_preference_action(
            commercial,
            creation.organization.pk,
            person_id=person_id,
            channel=Channel.EMAIL,
            purpose=Purpose.PAYMENT_REMINDER,
            suppress=True,
            reason="Comercial no administra preferencias financieras.",
        )

    commercial_template_purposes = {
        item["purpose"] for item in list_templates(commercial, creation.organization.pk)
    }
    assert Purpose.SERVICE_UPDATE in commercial_template_purposes
    assert Purpose.EVENT_REMINDER not in commercial_template_purposes
    assert Purpose.PAYMENT_REMINDER not in commercial_template_purposes


@pytest.mark.django_db
def test_internal_intent_endpoint_derives_provenance_and_rejects_client_authority() -> None:
    owner, creation = _organization("intent-provenance")
    commercial = _role_user(creation, role=Membership.Role.COMMERCIAL, slug="intent-commercial")
    locator, form_version, _ = _published_form(owner, creation)
    captured = submit_public_form(
        locator,
        idempotency_key="intent-provenance-event",
        data=_submission(form_version),
    )
    event_request_id = UUID(str(captured["event_request_id"]))
    with authorized_tenant_scope(owner, creation.organization.pk, "sales:read"):
        person_id = UUID(
            str(
                form_version.submissions.get(
                    event_request_reference=event_request_id
                ).person_reference
            )
        )
    version_id = _published_template(
        owner, creation, name="Intent tipado", purpose=Purpose.SERVICE_UPDATE
    )
    client = Client()
    csrf_token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
    login = client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": commercial.email, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert login.status_code == 200
    url = f"/api/v1/organizations/{creation.organization.pk}/communications/intents/"
    with authorized_tenant_scope(owner, creation.organization.pk, "sales:read"):
        before = CommunicationIntent.objects.count()
    invented = client.post(
        url,
        data=json.dumps(
            {
                "purpose": Purpose.SERVICE_UPDATE,
                "channel": Channel.EMAIL,
                "event_request_id": str(event_request_id),
                "template_version_id": str(version_id),
                "variables": {},
                "idempotency_key": "invented-provenance",
                "person_id": str(person_id),
                "aggregate_type": "invented_domain",
                "aggregate_id": str(event_request_id),
                "source_version": 999,
            }
        ),
        content_type="application/json",
    )
    assert invented.status_code == 400
    with authorized_tenant_scope(owner, creation.organization.pk, "sales:read"):
        assert CommunicationIntent.objects.count() == before

    accepted = client.post(
        url,
        data=json.dumps(
            {
                "purpose": Purpose.SERVICE_UPDATE,
                "channel": Channel.EMAIL,
                "event_request_id": str(event_request_id),
                "template_version_id": str(version_id),
                "variables": {},
                "idempotency_key": "typed-provenance",
            }
        ),
        content_type="application/json",
    )
    assert accepted.status_code == 201
    with authorized_tenant_scope(owner, creation.organization.pk, "sales:read"):
        intent = CommunicationIntent.objects.get(idempotency_key="typed-provenance")
        assert intent.recipient_person_id == person_id
        assert intent.aggregate_type == "event_request"
        assert intent.aggregate_id == event_request_id
        assert intent.source_version == 1

    finance = _role_user(creation, role=Membership.Role.FINANCE, slug="intent-finance")
    finance_client = Client()
    finance_csrf = finance_client.get("/api/v1/auth/csrf/").json()["csrf_token"]
    finance_login = finance_client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"email": finance.email, "password": PASSWORD}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=finance_csrf,
    )
    assert finance_login.status_code == 200
    insufficient_sales_read = finance_client.post(
        url,
        data=json.dumps(
            {
                "purpose": Purpose.SERVICE_UPDATE,
                "channel": Channel.EMAIL,
                "event_request_id": str(event_request_id),
                "template_version_id": str(version_id),
                "variables": {},
                "idempotency_key": "sales-read-is-insufficient",
            }
        ),
        content_type="application/json",
    )
    assert insufficient_sales_read.status_code == 403

    portal_token, _ = _portal_session_for_event(
        owner,
        creation.organization.pk,
        event_request_id,
        scopes=["event:read"],
    )
    external_client = Client()
    external_client.cookies["claridez_portal_session"] = portal_token
    assert (
        external_client.get(
            f"/api/v1/organizations/{creation.organization.pk}/communications/deliveries/"
        ).status_code
        == 401
    )


@pytest.mark.django_db
def test_external_tenant_authorization_requires_a_valid_locator_path() -> None:
    import claridez.organizations.public as organizations_public

    owner, creation = _organization("locator-mint")
    _other_owner, other = _organization("locator-cross")
    locator, version, _ = _published_form(owner, creation)

    assert organization_is_active_for_external_entry(creation.organization.pk)
    assert not hasattr(organizations_public, "authorize_external_entry")
    forged = ExternalTenantAuthorization(
        organization_id=creation.organization.pk,
        purpose="public_form",
        locator_reference=uuid4(),
        _proof=object(),
    )
    with pytest.raises(TenantAccessDenied), external_tenant_scope(forged):
        pass

    assert read_public_form(locator)["version"] == version.version
    with pytest.raises(PortalError):
        read_public_form(locator + "altered")

    crossed_locator = random_token()
    PortalLocator.objects.create(
        token_hmac=digest(crossed_locator, purpose="locator"),
        organization_id=other.organization.pk,
        kind=PortalLocator.Kind.PUBLIC_FORM,
        target_reference=version.form_id,
    )
    with pytest.raises(PortalError):
        read_public_form(crossed_locator)

    rotate_form_locator(owner, creation.organization.pk, form_id=version.form_id)
    with pytest.raises(PortalError):
        read_public_form(locator)
    expired_locator = random_token()
    PortalLocator.objects.create(
        token_hmac=digest(expired_locator, purpose="locator"),
        organization_id=creation.organization.pk,
        kind=PortalLocator.Kind.PUBLIC_FORM,
        target_reference=version.form_id,
        expires_at=timezone.now(),
    )
    with pytest.raises(PortalError):
        read_public_form(expired_locator)


def test_external_authorization_mint_has_one_guarded_production_call_site() -> None:
    source = Path(__file__).parents[1] / "src" / "claridez"
    mint_name = "_mint_external_tenant_authorization"
    proof_name = "_EXTERNAL_PROOF"
    imports: list[Path] = []
    proof_imports: list[Path] = []
    calls: list[tuple[Path, str]] = []
    constructor_calls: list[Path] = []
    for file in source.rglob("*.py"):
        if "migrations" in file.parts:
            continue
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == mint_name for alias in node.names
            ):
                imports.append(file)
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == proof_name for alias in node.names
            ):
                proof_imports.append(file)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == mint_name
            ):
                enclosing = next(
                    (
                        parent
                        for parent in ast.walk(tree)
                        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node in ast.walk(parent)
                    ),
                    None,
                )
                calls.append((file, enclosing.name if enclosing else ""))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ExternalTenantAuthorization"
            ):
                constructor_calls.append(file)
    portal_services = source / "portal" / "services.py"
    tenant_scope = source / "organizations" / "tenant_scope.py"
    assert set(imports) == {portal_services}
    assert proof_imports == []
    assert calls == [(portal_services, "resolve_locator")]
    assert constructor_calls == [tenant_scope]
    assert "authorize_external_entry" not in (source / "organizations" / "public.py").read_text(
        encoding="utf-8"
    )
