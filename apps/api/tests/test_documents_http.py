from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.test import Client
from django.utils import timezone

from claridez.documents.acceptance import MANIFESTATION_VERSION
from claridez.documents.jobs import work_once
from claridez.documents.rendering import RenderedPDF
from claridez.documents.services import (
    create_external_grant,
    create_instrument,
    create_record,
    create_template,
    issue_instrument,
    publish_template_version,
)
from claridez.identity.models import User
from claridez.organizations.models import Membership
from claridez.organizations.services import add_membership, create_organization
from tests.document_fixtures import PASSWORD, build_document_case

pytestmark = pytest.mark.django_db

BODY = "<h1>{{ organization.name }}</h1><p>{{ counterparty.full_name }}</p>"
SCHEMA = {
    "version": "claridez-vars-v1",
    "variables": [
        {"name": "organization.name", "required": True},
        {"name": "counterparty.full_name", "required": True},
    ],
}


def _csrf(client: Client) -> str:
    return str(client.get("/api/v1/auth/csrf/").json()["csrf_token"])


def _post(client: Client, path: str, payload: dict[str, Any], token: str) -> Any:
    return client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )


def _login(client: Client, email: str, password: str = PASSWORD) -> str:
    response = _post(
        client,
        "/api/v1/auth/login/",
        {"email": email, "password": password},
        _csrf(client),
    )
    assert response.status_code == 200
    return _csrf(client)


def test_document_api_requires_session_csrf_capability_and_tenant_scope() -> None:
    case = build_document_case("documents-http")
    foreign = create_organization(
        owner_user_id=User.objects.create_user(
            email=f"foreign-{uuid4()}@example.test",
            password=PASSWORD,
            status=User.Status.ACTIVE,
            email_verified_at=timezone.now(),
        ).pk,
        name="Foreign documents",
        slug=f"foreign-documents-{uuid4().hex}",
    )
    base = f"/api/v1/organizations/{case.organization_id}/documents"
    anonymous = Client(enforce_csrf_checks=True)
    assert anonymous.get(f"{base}/capabilities/").status_code == 401

    client = Client(enforce_csrf_checks=True)
    token = _login(client, case.owner.email)
    capabilities = client.get(f"{base}/capabilities/")
    assert capabilities.status_code == 200
    assert "contractual_instrument:issue" in capabilities.json()["capabilities"]

    missing_csrf = client.post(
        f"{base}/templates/",
        data=json.dumps(
            {
                "name": "Contrato HTTP",
                "title": "Contrato HTTP",
                "body_html": BODY,
                "variable_schema": SCHEMA,
            }
        ),
        content_type="application/json",
    )
    assert missing_csrf.status_code == 403
    created = _post(
        client,
        f"{base}/templates/",
        {
            "name": "Contrato HTTP",
            "title": "Contrato HTTP",
            "body_html": BODY,
            "variable_schema": SCHEMA,
        },
        token,
    )
    assert created.status_code == 201
    assert created.json()["versions"][0]["status"] == "draft"

    root_id = case.reservation["root_id"]
    empty = client.get(f"{base}/records/?root_reservation_id={root_id}")
    assert empty.status_code == 200
    assert empty.json()["status"] == "no_contract_issued"
    foreign_query = client.get(
        f"/api/v1/organizations/{foreign.organization.pk}/documents/records/"
        f"?root_reservation_id={root_id}"
    )
    assert foreign_query.status_code == 404


def test_finance_is_deny_by_default_for_documents() -> None:
    case = build_document_case("documents-finance")
    finance = User.objects.create_user(
        email=f"finance-{uuid4()}@example.test",
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )
    add_membership(
        organization_id=case.organization_id,
        user_id=finance.pk,
        role=Membership.Role.FINANCE,
    )
    client = Client(enforce_csrf_checks=True)
    _login(client, finance.email)
    base = f"/api/v1/organizations/{case.organization_id}/documents"
    capabilities = client.get(f"{base}/capabilities/")
    assert capabilities.status_code == 200
    assert capabilities.json()["capabilities"] == []
    assert client.get(f"{base}/templates/").status_code == 403


def test_external_invalid_tokens_are_opaque_rate_limited_and_not_cached() -> None:
    client = Client()
    response = client.post(
        "/api/v1/external/documents/exchange/",
        data=json.dumps({"token": "x" * 64}),
        content_type="application/json",
        REMOTE_ADDR="192.0.2.10",
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["X-Content-Type-Options"] == "nosniff"
    for _ in range(19):
        client.post(
            "/api/v1/external/documents/exchange/",
            data=json.dumps({"token": "x" * 64}),
            content_type="application/json",
            REMOTE_ADDR="192.0.2.10",
        )
    limited = client.post(
        "/api/v1/external/documents/exchange/",
        data=json.dumps({"token": "x" * 64}),
        content_type="application/json",
        REMOTE_ADDR="192.0.2.10",
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"


def test_external_http_flow_reads_downloads_accepts_and_blocks_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = build_document_case("documents-external-http")
    template = create_template(
        case.owner,
        case.organization_id,
        name="Contrato externo HTTP",
        title="Contrato externo HTTP",
        body_html=BODY,
        variable_schema=SCHEMA,
    )
    template_version_id = UUID(template["versions"][0]["id"])
    publish_template_version(case.owner, case.organization_id, version_id=template_version_id)
    record = create_record(
        case.owner,
        case.organization_id,
        root_reservation_id=UUID(str(case.reservation["root_id"])),
    )
    instrument = create_instrument(
        case.owner,
        case.organization_id,
        record_id=UUID(record["id"]),
        instrument_type="main_contract",
        title="Contrato principal",
    )
    content = b"%PDF-1.7\n% external HTTP artifact\n"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        "claridez.documents.jobs.render_pdf",
        lambda _html: RenderedPDF(
            content,
            digest,
            len(content),
            "WeasyPrint",
            "69.0",
            "claridez-render-weasyprint-69.0-debian12-v1",
        ),
    )
    issued = issue_instrument(
        case.owner,
        case.organization_id,
        instrument_id=UUID(instrument["id"]),
        template_version_id=template_version_id,
        idempotency_key=uuid4(),
        correlation_id="external-http",
    )
    assert work_once(case.organization_id, worker_id="external-http-worker")
    assert work_once(case.organization_id, worker_id="external-http-worker")
    grant = create_external_grant(
        case.owner,
        case.organization_id,
        issued_version_id=UUID(issued["id"]),
        purpose="accept",
        expires_at=timezone.now() + timedelta(hours=1),
    )

    client = Client()
    exchanged = client.post(
        "/api/v1/external/documents/exchange/",
        data=json.dumps({"token": grant["token"]}),
        content_type="application/json",
        REMOTE_ADDR="192.0.2.20",
        HTTP_X_REQUEST_ID="external-http-exchange",
    )
    assert exchanged.status_code == 200
    assert exchanged.json() == {"status": "session_created"}
    assert exchanged.cookies["claridez_document_session"]["httponly"] is True
    assert exchanged.cookies["claridez_document_session"]["samesite"] == "Strict"

    document = client.get(
        "/api/v1/external/documents/session/",
        REMOTE_ADDR="192.0.2.20",
        HTTP_X_REQUEST_ID="external-http-read",
    )
    assert document.status_code == 200
    assert document.json()["artifact"]["sha256"] == digest
    assert document.json()["permissions"] == {"read": True, "download": True, "accept": True}
    artifact = client.get(
        "/api/v1/external/documents/artifact/",
        REMOTE_ADDR="192.0.2.20",
        HTTP_X_REQUEST_ID="external-http-download",
    )
    assert artifact.status_code == 200
    assert artifact.content == content
    assert artifact["Cache-Control"] == "no-store"
    assert artifact["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'self'"

    challenge = client.post(
        "/api/v1/external/documents/challenge/",
        REMOTE_ADDR="192.0.2.20",
        HTTP_X_REQUEST_ID="external-http-challenge",
    )
    assert challenge.status_code == 201
    payload = {
        "challenge_token": challenge.json()["challenge_token"],
        "manifestation_version": MANIFESTATION_VERSION,
        "affirmative": True,
        "asserted_name": "MarÃ­a Contraparte",
        "timezone": "America/Guayaquil",
    }
    accepted = client.post(
        "/api/v1/external/documents/accept/",
        data=json.dumps(payload),
        content_type="application/json",
        REMOTE_ADDR="192.0.2.20",
        HTTP_X_REQUEST_ID="external-http-accept",
        HTTP_X_CORRELATION_ID="external-http",
    )
    assert accepted.status_code == 201
    assert accepted.json()["artifact_sha256"] == digest
    replay = client.post(
        "/api/v1/external/documents/accept/",
        data=json.dumps(payload),
        content_type="application/json",
        REMOTE_ADDR="192.0.2.20",
    )
    assert replay.status_code == 409

    read_grant = create_external_grant(
        case.owner,
        case.organization_id,
        issued_version_id=UUID(issued["id"]),
        purpose="read",
        expires_at=timezone.now() + timedelta(hours=1),
    )
    read_client = Client()
    assert (
        read_client.post(
            "/api/v1/external/documents/exchange/",
            data=json.dumps({"token": read_grant["token"]}),
            content_type="application/json",
        ).status_code
        == 200
    )
    read_document = read_client.get("/api/v1/external/documents/session/")
    assert read_document.json()["permissions"] == {
        "read": True,
        "download": False,
        "accept": False,
    }
    assert read_client.get("/api/v1/external/documents/artifact/").content == content
    assert replay.json()["error"]["code"] == "invalid_or_consumed_challenge"


def test_inactive_membership_and_unknown_document_ids_fail_closed() -> None:
    case = build_document_case("documents-inactive")
    client = Client(enforce_csrf_checks=True)
    _login(client, case.owner.email)
    base = f"/api/v1/organizations/{case.organization_id}/documents"
    unknown = client.get(f"{base}/artifacts/{uuid4()}/download/")
    assert unknown.status_code == 404
    Membership.objects.filter(organization_id=case.organization_id, user=case.owner).update(
        status=Membership.Status.SUSPENDED, suspended_at=timezone.now()
    )
    assert client.get(f"{base}/capabilities/").status_code == 404


def test_issue_requires_uuid_idempotency_header() -> None:
    case = build_document_case("documents-idempotency")
    client = Client(enforce_csrf_checks=True)
    token = _login(client, case.owner.email)
    base = f"/api/v1/organizations/{case.organization_id}/documents"
    record = _post(
        client,
        f"{base}/records/",
        {"root_reservation_id": str(case.reservation["root_id"])},
        token,
    ).json()
    instrument = _post(
        client,
        f"{base}/records/{record['id']}/instruments/",
        {"instrument_type": "main_contract", "title": "Contrato"},
        token,
    ).json()
    response = _post(
        client,
        f"{base}/instruments/{instrument['id']}/issue/",
        {"template_version_id": str(UUID(int=0))},
        token,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_idempotency_key"
