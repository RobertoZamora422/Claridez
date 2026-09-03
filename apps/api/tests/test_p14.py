from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from claridez.application.communications import retry_delivery
from claridez.application.reminders import cancel_reminder, request_reminder
from claridez.catalog.services import create_event_type
from claridez.commercial.errors import CommercialError
from claridez.commercial.models import EventRequest, QuotationVersion
from claridez.commercial.services import (
    confirm_reservation,
    create_quotation,
    create_quotation_version,
    issue_quotation_version,
    replace_quotation_draft,
)
from claridez.communications.errors import CommunicationsError
from claridez.communications.models import (
    Channel,
    CommunicationIntent,
    CommunicationOutbox,
    CommunicationPreferenceEvent,
    CommunicationTemplate,
    CommunicationTemplateVersion,
    DeliveryAttempt,
    LogicalMessage,
    ProviderEvent,
    Purpose,
)
from claridez.communications.providers import DeliveryResult
from claridez.communications.services import (
    _effective_suppression,
    append_preference,
    claim_next,
    complete_delivery,
    configure_policy,
    configure_sender,
    create_template,
    create_template_version,
    internal_preference_action,
    prepare_delivery,
    publish_template,
    reconcile_provider_event,
    request_intent,
)
from claridez.crm.models import Interaction
from claridez.documents.acceptance import MANIFESTATION_TEXT, MANIFESTATION_VERSION
from claridez.documents.config import document_settings
from claridez.documents.jobs import work_once
from claridez.documents.models import AcceptanceEvidence, GeneratedArtifact
from claridez.documents.public import DocumentsPortError
from claridez.documents.rendering import RenderedPDF
from claridez.documents.services import (
    create_instrument,
    create_record,
    issue_instrument,
    publish_template_version,
)
from claridez.documents.services import (
    create_template as create_document_template,
)
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.models import Membership, Space
from claridez.organizations.services import create_organization
from claridez.organizations.tenant_scope import (
    authorized_tenant_scope,
    infrastructure_tenant_scope,
)
from claridez.people import services as people_services
from claridez.people.errors import PeopleError
from claridez.people.models import ConsentEvent, Person, PersonRevision
from claridez.portal.errors import PortalError
from claridez.portal.models import (
    PortalChallenge,
    PortalGrant,
    PortalLocator,
    PortalPrincipal,
    PortalSession,
    PublicFormSubmission,
    PublicFormVersion,
)
from claridez.portal.security import (
    consume_rate_limit,
    digest,
    random_token,
    verify_antiabuse,
)
from claridez.portal.services import (
    _resolve_public_interval,
    accept_document_for_grant,
    create_form,
    create_form_version,
    create_webhook_locator_internal,
    download_document_for_grant,
    portal_documents_for_grant,
    portal_event,
    portal_events,
    publish_form,
    read_public_form,
    retire_form,
    revoke_session,
    rotate_form_locator,
    start_challenge,
    submit_public_form,
    verify_challenge,
)
from claridez.receivables.models import ReceivableObligation, ReceivedPayment
from claridez.receivables.services import (
    apply_payment_authorized,
    issue_receipt_authorized,
    record_payment_authorized,
)
from claridez.scheduling.services import cancel_reservation, reschedule_reservation
from tests.document_fixtures import build_document_case

PASSWORD = "p14-tests-very-secure-42!"


def _user(email: str) -> User:
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        status=User.Status.ACTIVE,
        email_verified_at=timezone.now(),
    )


def _organization(prefix: str) -> tuple[User, Any]:
    owner = _user(f"{prefix}@example.com")
    return owner, create_organization(owner_user_id=owner.pk, name=f"Organización {prefix}")


def _configuration(owner: User, creation: Any) -> dict[str, Any]:
    organization_id = creation.organization.pk
    event_type = create_event_type(owner, organization_id, name="Celebración")
    with authorized_tenant_scope(owner, organization_id, Capability.VENUE_READ):
        space = Space.objects.select_related("venue").get(
            organization_id=organization_id, is_primary=True
        )
    consent_text = "Acepto recibir actualizaciones de servicio sobre esta solicitud."
    return {
        "name": "Captación principal",
        "title": "Cuéntanos sobre tu evento",
        "introduction": "El equipo comercial revisará la solicitud.",
        "field_schema": {
            "required": [
                "full_name",
                "phone",
                "event_type_id",
                "space_id",
                "starts_at_local",
                "duration_minutes",
                "estimated_guests",
                "general_need",
            ],
            "optional": ["email", "notes"],
            "labels": {},
        },
        "event_type_options": [{"id": event_type["id"], "revision": event_type["revision"]}],
        "location_options": [
            {
                "space_id": space.pk,
                "space_revision": space.revision,
                "venue_revision": space.venue.revision,
            }
        ],
        "duration_options_minutes": [60, 120],
        "timezone_name": "America/Guayaquil",
        "responsible_membership_id": creation.owner_membership.pk,
        "origin": "website",
        "origin_detail": "Formulario público P14",
        "attribution": {"source": "public_form"},
        "consent_presentation": [
            {
                "purpose": "service_update",
                "channel": "email",
                "text": consent_text,
                "text_sha256": hashlib.sha256(consent_text.encode()).hexdigest(),
                "version": "service-v1",
                "required": False,
            }
        ],
        "portal_scopes": [
            "event:read",
            "quotation:read",
            "schedule:read",
            "documents:read",
            "documents:download",
            "documents:accept",
            "receivables:read",
            "preferences:manage",
        ],
        "acknowledgement_template_version_id": None,
    }


def _published_form(owner: User, creation: Any) -> tuple[str, PublicFormVersion, dict[str, Any]]:
    configuration = _configuration(owner, creation)
    created = create_form(owner, creation.organization.pk, **configuration)
    publish_form(owner, creation.organization.pk, version_id=UUID(str(created["version_id"])))
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        version = PublicFormVersion.objects.get(pk=UUID(str(created["version_id"])))
    return (
        str(created["locator"]),
        version,
        configuration,
    )


def _submission(version: PublicFormVersion, *, phone: str = "0991234567") -> dict[str, object]:
    starts_at = timezone.now().astimezone(ZoneInfo("America/Guayaquil")).replace(
        second=0, microsecond=0
    ) + timedelta(days=20)
    return {
        "full_name": "Cliente Portal",
        "phone": phone,
        "email": "cliente.portal@example.com",
        "event_type_id": version.event_type_options[0]["id"],
        "space_id": version.location_options[0]["space_id"],
        "starts_at_local": starts_at.strftime("%Y-%m-%dT%H:%M"),
        "duration_minutes": 60,
        "estimated_guests": 80,
        "general_need": "Una celebración familiar clara y bien coordinada.",
        "notes": "Acceso principal.",
        "consents": {"service_update:email": True},
        "attribution": {"campaign": "test"},
    }


def _portal_session_for_event(
    owner: User,
    organization_id: UUID,
    event_request_id: UUID,
    *,
    scopes: list[str],
    absolute_days: int = 1,
) -> tuple[str, PortalGrant]:
    token = random_token()
    now = timezone.now()
    with authorized_tenant_scope(owner, organization_id, Capability.SALES_READ):
        event_request = EventRequest.objects.select_related("person").get(pk=event_request_id)
        principal, _ = PortalPrincipal.objects.get_or_create(
            organization_id=organization_id,
            person_reference=event_request.person_id,
            state=PortalPrincipal.State.ACTIVE,
            defaults={"canonical_set": [str(event_request.person_id)]},
        )
        grant, _ = PortalGrant.objects.get_or_create(
            organization_id=organization_id,
            principal=principal,
            event_request_reference=event_request_id,
            state=PortalGrant.State.ACTIVE,
            defaults={
                "person_reference": event_request.person_id,
                "scopes": scopes,
                "provenance": "public_capture",
            },
        )
        session = PortalSession.objects.create(
            organization_id=organization_id,
            principal=principal,
            token_hmac=digest(token, purpose="session"),
            contact_fingerprint=digest(event_request.person.email, purpose="contact"),
            contact_revision=event_request.person.revision,
            idle_expires_at=now + timedelta(days=absolute_days),
            absolute_expires_at=now + timedelta(days=absolute_days),
            last_seen_at=now,
        )
        PortalLocator.objects.create(
            token_hmac=digest(token, purpose="locator"),
            organization_id=organization_id,
            kind=PortalLocator.Kind.SESSION,
            target_reference=session.pk,
        )
    return token, grant


def test_public_interval_uses_published_timezone_and_rejects_ambiguous_wall_time() -> None:
    ecuador = PublicFormVersion(timezone_name="America/Guayaquil", duration_options_minutes=[60])
    starts_at, ends_at = _resolve_public_interval(
        ecuador,
        starts_at_local="2026-10-15T18:30",
        duration_minutes=60,
    )
    assert starts_at.isoformat() == "2026-10-15T18:30:00-05:00"
    assert (ends_at.astimezone(UTC) - starts_at.astimezone(UTC)) == timedelta(hours=1)

    new_york = PublicFormVersion(timezone_name="America/New_York", duration_options_minutes=[60])
    with pytest.raises(PortalError, match="ambigua"):
        _resolve_public_interval(
            new_york,
            starts_at_local="2026-11-01T01:30",
            duration_minutes=60,
        )


@pytest.mark.django_db
def test_p14_capabilities_are_atomic_and_role_scoped() -> None:
    owner = capabilities_for_role(Membership.Role.OWNER)
    administrator = capabilities_for_role(Membership.Role.ADMINISTRATOR)
    commercial = capabilities_for_role(Membership.Role.COMMERCIAL)
    operations = capabilities_for_role(Membership.Role.OPERATIONS)
    finance = capabilities_for_role(Membership.Role.FINANCE)

    assert Capability.PUBLIC_FORM_PUBLISH in owner & administrator & commercial
    assert Capability.PUBLIC_FORM_READ not in operations | finance
    assert Capability.PORTAL_GRANT_ISSUE in owner & administrator & commercial
    assert Capability.PORTAL_GRANT_READ not in operations | finance
    assert Capability.COMMUNICATION_INTENT_REQUEST in owner & administrator & commercial
    assert Capability.COMMUNICATION_INTENT_REQUEST in operations & finance
    assert Capability.COMMUNICATION_PREFERENCE_RESTORE in owner & administrator
    assert Capability.COMMUNICATION_PREFERENCE_RESTORE not in commercial | operations | finance


@pytest.mark.django_db
def test_public_capture_preserves_form_version_people_consent_and_event_request() -> None:
    owner, creation = _organization("capture")
    locator, version, _ = _published_form(owner, creation)
    payload = _submission(version)

    assert read_public_form(locator)["version"] == 1
    result = submit_public_form(locator, idempotency_key="capture-1", data=payload)
    replay = submit_public_form(locator, idempotency_key="capture-1", data=payload)

    assert replay == result
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        submission = PublicFormSubmission.objects.get(pk=UUID(str(result["submission_id"])))
        person = Person.objects.get(pk=UUID(str(submission.person_reference)))
        request = EventRequest.objects.get(pk=UUID(str(submission.event_request_reference)))
        consent = ConsentEvent.objects.get(pk=UUID(submission.consent_event_references[0]))
        revision = PersonRevision.objects.get(person=person, revision=1)
        grant = PortalGrant.objects.get(event_request_reference=request.pk)
        assert submission.form_version_id == version.pk
        assert submission.availability_observed is True
        assert request.person_id == person.pk
        assert request.responsible_membership_id == creation.owner_membership.pk
        assert request.event_timezone == "America/Guayaquil"
        assert consent.recorder_kind == ConsentEvent.RecorderKind.EXTERNAL_SUBJECT
        assert consent.recorded_by_membership_id is None
        assert consent.external_submission_reference == f"portal-submission:{submission.pk}"
        assert revision.actor_kind == PersonRevision.ActorKind.EXTERNAL_SUBJECT
        assert revision.changed_by_id is None
        assert grant.person_reference == person.pk
        assert grant.event_request_reference == request.pk

    changed = dict(payload)
    changed["estimated_guests"] = 81
    with pytest.raises(PortalError, match="clave"):
        submit_public_form(locator, idempotency_key="capture-1", data=changed)


@pytest.mark.django_db
def test_optional_consent_absence_does_not_fabricate_revocation_and_non_boolean_fails() -> None:
    owner, creation = _organization("capture-consent-absence")
    locator, version, _ = _published_form(owner, creation)
    without_decision = _submission(version)
    without_decision["consents"] = {}
    captured = submit_public_form(
        locator,
        idempotency_key="optional-consent-absent",
        data=without_decision,
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        submission = PublicFormSubmission.objects.get(pk=UUID(str(captured["submission_id"])))
        assert submission.consent_event_references == []
        assert submission.person_reference is not None
        assert not ConsentEvent.objects.filter(
            person_id=submission.person_reference,
            purpose=Purpose.SERVICE_UPDATE,
        ).exists()

    malformed = _submission(version, phone="0991234511")
    malformed["email"] = "consent-invalid@example.com"
    malformed["starts_at_local"] = (
        datetime.fromisoformat(str(malformed["starts_at_local"])) + timedelta(days=3)
    ).strftime("%Y-%m-%dT%H:%M")
    malformed["consents"] = {"service_update:email": "false"}
    with pytest.raises(PortalError) as invalid_consent:
        submit_public_form(
            locator,
            idempotency_key="non-boolean-consent",
            data=malformed,
        )
    assert invalid_consent.value.code == "invalid_request"


@pytest.mark.django_db
def test_capture_is_not_blocked_by_unavailability_and_responsible_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, creation = _organization("availability")
    locator, version, _ = _published_form(owner, creation)

    class Unavailable:
        available = False

    def unavailable_projection(*args: object, **kwargs: object) -> Unavailable:
        del args, kwargs
        return Unavailable()

    monkeypatch.setattr(
        "claridez.portal.services.public_interval_availability", unavailable_projection
    )
    result = submit_public_form(locator, idempotency_key="busy-slot", data=_submission(version))
    assert result["availability"] is False
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        assert EventRequest.objects.filter(pk=UUID(str(result["event_request_id"]))).exists()

    creation.owner_membership.status = Membership.Status.SUSPENDED
    creation.owner_membership.suspended_at = timezone.now()
    creation.owner_membership.save(update_fields=["status", "suspended_at", "updated_at"])
    with pytest.raises(CommercialError) as caught:
        submit_public_form(
            locator,
            idempotency_key="invalid-responsible",
            data=_submission(version, phone="0991234568"),
        )
    assert caught.value.code == "resource_not_available"


@pytest.mark.django_db
def test_public_capture_rejects_cross_person_contact_conflicts_without_partial_history() -> None:
    owner, creation = _organization("capture-contact-conflict")
    locator, version, _ = _published_form(owner, creation)
    first_data = _submission(version)
    submit_public_form(locator, idempotency_key="contact-first", data=first_data)
    second_data = _submission(version, phone="0991234590")
    second_data["email"] = "segundo.contacto@example.com"
    second_data["starts_at_local"] = (
        datetime.fromisoformat(str(second_data["starts_at_local"])) + timedelta(days=1)
    ).strftime("%Y-%m-%dT%H:%M")
    submit_public_form(locator, idempotency_key="contact-second", data=second_data)
    conflicting = dict(first_data)
    conflicting["email"] = "segundo.contacto@example.com"
    conflicting["starts_at_local"] = (
        datetime.fromisoformat(str(conflicting["starts_at_local"])) + timedelta(days=2)
    ).strftime("%Y-%m-%dT%H:%M")
    with pytest.raises(PeopleError) as error:
        submit_public_form(locator, idempotency_key="contact-conflict", data=conflicting)
    assert error.value.code == "contact_identity_conflict"
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        assert Person.objects.count() == 2
        assert PublicFormSubmission.objects.count() == 2


@pytest.mark.django_db
def test_form_and_template_versions_are_replaced_without_rewriting_history() -> None:
    owner, creation = _organization("versions")
    locator, version, configuration = _published_form(owner, creation)
    replacement = dict(configuration)
    replacement["title"] = "Nueva presentación"
    replacement.pop("name")
    next_version = create_form_version(
        owner, creation.organization.pk, form_id=version.form_id, **replacement
    )
    publish_form(owner, creation.organization.pk, version_id=UUID(str(next_version["id"])))
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        version.refresh_from_db()
        assert version.status == PublicFormVersion.Status.RETIRED
    assert read_public_form(locator)["title"] == "Nueva presentación"

    template = create_template(
        owner,
        creation.organization.pk,
        name="Acceso Portal",
        channel=Channel.EMAIL,
        purpose=Purpose.PORTAL_AUTHENTICATION,
        subject_template="Tu acceso",
        body_template="Código: {code}",
        variable_names=["code"],
    )
    template_version_id = template["versions"][0]["id"]
    publish_template(owner, creation.organization.pk, version_id=template_version_id)
    replacement_template = create_template_version(
        owner,
        creation.organization.pk,
        template_id=UUID(str(template["id"])),
        subject_template="Tu nuevo acceso",
        body_template="Nuevo código: {code}",
        variable_names=["code"],
    )
    publish_template(
        owner,
        creation.organization.pk,
        version_id=UUID(str(replacement_template["id"])),
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        published = CommunicationTemplateVersion.objects.get(pk=template_version_id)
        assert len(published.content_sha256) == 64
        assert published.status == CommunicationTemplateVersion.Status.PUBLISHED
        assert (
            CommunicationTemplateVersion.objects.filter(
                template_id=template["id"], status=CommunicationTemplateVersion.Status.PUBLISHED
            ).count()
            == 2
        )


@pytest.mark.django_db
def test_outbox_is_idempotent_reclaimable_and_records_provider_results() -> None:
    owner, creation = _organization("outbox")
    locator, version, _ = _published_form(owner, creation)
    capture = submit_public_form(
        locator, idempotency_key="outbox-person", data=_submission(version)
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        event_request = EventRequest.objects.select_related("person").get(
            pk=UUID(str(capture["event_request_id"]))
        )
        person = event_request.person
    template = create_template(
        owner,
        creation.organization.pk,
        name="Actualización de servicio",
        channel=Channel.EMAIL,
        purpose=Purpose.SERVICE_UPDATE,
        subject_template="Actualización",
        body_template="Solicitud {event_request_id}",
        variable_names=["event_request_id"],
    )
    version_id = template["versions"][0]["id"]
    publish_template(owner, creation.organization.pk, version_id=version_id)
    configure_policy(
        owner,
        creation.organization.pk,
        purpose=Purpose.SERVICE_UPDATE,
        channel=Channel.EMAIL,
        requires_consent=True,
        allow_unsubscribe=True,
        rationale="Política de prueba aprobada.",
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        first = request_intent(
            creation.organization.pk,
            purpose=Purpose.SERVICE_UPDATE,
            channel=Channel.EMAIL,
            person_id=person.pk,
            template_version_id=version_id,
            aggregate_type="event_request",
            aggregate_id=event_request.pk,
            variables={"event_request_id": str(event_request.pk)},
            idempotency_key="service-once",
            source_version=event_request.revision,
        )
        assert (
            request_intent(
                creation.organization.pk,
                purpose=Purpose.SERVICE_UPDATE,
                channel=Channel.EMAIL,
                person_id=person.pk,
                template_version_id=version_id,
                aggregate_type="event_request",
                aggregate_id=event_request.pk,
                variables={"event_request_id": str(event_request.pk)},
                idempotency_key="service-once",
                source_version=event_request.revision,
            ).pk
            == first.pk
        )

    with infrastructure_tenant_scope(creation.organization.pk, purpose="communications_worker"):
        outbox_id = claim_next(creation.organization.pk, worker_id="worker-a")
        assert outbox_id is not None
        first_request = prepare_delivery(creation.organization.pk, outbox_id)
    assert first_request is not None and "Solicitud" in first_request.body
    with infrastructure_tenant_scope(creation.organization.pk, purpose="communications_worker"):
        assert claim_next(creation.organization.pk, worker_id="worker-b") is None
        CommunicationOutbox.objects.filter(pk=outbox_id).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert claim_next(creation.organization.pk, worker_id="worker-b") == outbox_id
        request = prepare_delivery(creation.organization.pk, outbox_id)
    assert request is not None and "Solicitud" in request.body
    with infrastructure_tenant_scope(creation.organization.pk, purpose="communications_worker"):
        complete_delivery(
            creation.organization.pk,
            outbox_id,
            DeliveryResult(False, "deterministic", "", error_category="provider_unavailable"),
        )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        outbox = CommunicationOutbox.objects.get(pk=outbox_id)
        assert outbox.state == CommunicationOutbox.State.RETRY
        attempts = tuple(DeliveryAttempt.objects.filter(outbox=outbox).order_by("attempt"))
        assert len(attempts) == 2
        assert attempts[0].outcome == "started"
        assert attempts[0].finished_at is None
        assert attempts[1].outcome == "failed"
        outbox.next_attempt_at = timezone.now()
        outbox.save(update_fields=["next_attempt_at", "updated_at"])
    with infrastructure_tenant_scope(creation.organization.pk, purpose="communications_worker"):
        assert claim_next(creation.organization.pk, worker_id="worker-terminal") == outbox.pk
        assert prepare_delivery(creation.organization.pk, outbox.pk) is not None
        complete_delivery(
            creation.organization.pk,
            outbox.pk,
            DeliveryResult(False, "deterministic", "", error_category="rejected", terminal=True),
        )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        outbox.refresh_from_db()
        assert outbox.state == CommunicationOutbox.State.DEAD
        assert outbox.message_id is not None
    retry_delivery(
        owner,
        creation.organization.pk,
        message_id=outbox.message_id,
        reason="Reintento autorizado después de revisar el fallo terminal.",
    )
    with infrastructure_tenant_scope(creation.organization.pk, purpose="communications_worker"):
        assert claim_next(creation.organization.pk, worker_id="worker-manual") == outbox.pk
        assert prepare_delivery(creation.organization.pk, outbox.pk) is not None
        complete_delivery(
            creation.organization.pk,
            outbox.pk,
            DeliveryResult(True, "deterministic", "provider-after-manual-retry"),
        )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        outbox.refresh_from_db()
        assert outbox.state == CommunicationOutbox.State.SUCCEEDED
        assert outbox.intent.state == CommunicationIntent.State.MATERIALIZED


@pytest.mark.django_db
def test_preferences_and_provider_events_are_conservative() -> None:
    owner, creation = _organization("preferences")
    locator, version, _ = _published_form(owner, creation)
    capture = submit_public_form(
        locator, idempotency_key="preference-person", data=_submission(version)
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        person = EventRequest.objects.get(pk=UUID(str(capture["event_request_id"]))).person
        principal_id = PortalPrincipal.objects.get(person_reference=person.pk).pk
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        append_preference(
            creation.organization.pk,
            person_id=person.pk,
            channel=Channel.EMAIL,
            purpose=Purpose.SERVICE_UPDATE,
            action=CommunicationPreferenceEvent.Action.CLIENT_UNSUBSCRIBE,
            portal_principal_id=principal_id,
            evidence_sha256="3" * 64,
        )
    with pytest.raises(CommunicationsError) as protected:
        internal_preference_action(
            owner,
            creation.organization.pk,
            person_id=person.pk,
            channel=Channel.EMAIL,
            purpose=Purpose.SERVICE_UPDATE,
            suppress=False,
            reason="No debe borrar la decisión del cliente",
        )
    assert protected.value.code == "protected_suppression"

    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        template = CommunicationTemplate.objects.create(
            organization_id=creation.organization.pk,
            name="Evento técnico",
            channel=Channel.EMAIL,
            purpose=Purpose.PORTAL_AUTHENTICATION,
            created_by_membership_id=creation.owner_membership.pk,
        )
        template_version = CommunicationTemplateVersion.objects.create(
            organization_id=creation.organization.pk,
            template=template,
            version=1,
            status=CommunicationTemplateVersion.Status.PUBLISHED,
            body_template="Código {code}",
            variable_names=["code"],
            content_sha256="a" * 64,
        )
        intent = CommunicationIntent.objects.create(
            organization_id=creation.organization.pk,
            purpose=Purpose.PORTAL_AUTHENTICATION,
            channel=Channel.EMAIL,
            recipient_person_id=person.pk,
            template_version=template_version,
            aggregate_type="portal_challenge",
            aggregate_id=uuid4(),
            variables={},
            payload_sha256="b" * 64,
            idempotency_key="provider-event",
            not_before=timezone.now(),
        )
        message = LogicalMessage.objects.create(
            organization_id=creation.organization.pk,
            intent=intent,
            template_version=template_version,
            channel=Channel.EMAIL,
            recipient_fingerprint="c" * 64,
            resolved_variables={},
            template_sha256="a" * 64,
            final_sha256="d" * 64,
            provider="deterministic",
            provider_message_id="message-1",
        )
    occurred_at = timezone.now()
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        delivered = reconcile_provider_event(
            creation.organization.pk,
            provider="deterministic",
            account="account-1",
            event_id="event-delivered",
            event_type="delivered",
            external_message_id="message-1",
            occurred_at=occurred_at,
            signature_timestamp=occurred_at,
            payload_sha256="e" * 64,
        )
        duplicate = reconcile_provider_event(
            creation.organization.pk,
            provider="deterministic",
            account="account-1",
            event_id="event-delivered",
            event_type="delivered",
            external_message_id="message-1",
            occurred_at=occurred_at,
            signature_timestamp=occurred_at,
            payload_sha256="e" * 64,
        )
        assert duplicate.pk == delivered.pk
        with pytest.raises(CommunicationsError) as collision:
            reconcile_provider_event(
                creation.organization.pk,
                provider="deterministic",
                account="account-1",
                event_id="event-delivered",
                event_type="hard_bounce",
                external_message_id="message-1",
                occurred_at=occurred_at,
                signature_timestamp=occurred_at,
                payload_sha256="9" * 64,
            )
        assert collision.value.code == "provider_event_conflict"
        reconcile_provider_event(
            creation.organization.pk,
            provider="deterministic",
            account="account-1",
            event_id="event-old-bounce",
            event_type="hard_bounce",
            external_message_id="message-1",
            occurred_at=occurred_at - timedelta(minutes=1),
            signature_timestamp=occurred_at,
            payload_sha256="f" * 64,
        )
        reconcile_provider_event(
            creation.organization.pk,
            provider="deterministic",
            account="account-1",
            event_id="event-new-bounce",
            event_type="hard_bounce",
            external_message_id="message-1",
            occurred_at=occurred_at + timedelta(minutes=2),
            signature_timestamp=occurred_at,
            payload_sha256="1" * 64,
        )
        stale_delivery = reconcile_provider_event(
            creation.organization.pk,
            provider="deterministic",
            account="account-1",
            event_id="event-stale-delivery",
            event_type="delivered",
            external_message_id="message-1",
            occurred_at=occurred_at + timedelta(minutes=1),
            signature_timestamp=occurred_at,
            payload_sha256="2" * 64,
        )
        assert stale_delivery.state == "ignored"
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        message.refresh_from_db()
        assert message.status == LogicalMessage.Status.BOUNCED
        assert ProviderEvent.objects.filter(message=message).count() == 4
        assert (
            _effective_suppression(
                creation.organization.pk,
                person_id=person.pk,
                channel=Channel.EMAIL,
                purpose=Purpose.CLIENT_ACTION,
                fingerprint=message.recipient_fingerprint,
            )
            == "hard_bounce"
        )

    source_data = people_services.create_person(
        owner,
        creation.organization.pk,
        full_name="Alias que luego será fusionado",
        phone="0998765432",
        email="alias-preferences@example.com",
        origin="referral",
        origin_detail="Prueba de merge conservador",
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        source = Person.objects.get(pk=source_data["id"])
        source_principal = PortalPrincipal.objects.create(
            organization_id=creation.organization.pk,
            person_reference=source.pk,
            canonical_set=[str(source.pk)],
        )
        append_preference(
            creation.organization.pk,
            person_id=source.pk,
            channel=Channel.EMAIL,
            purpose=Purpose.SERVICE_UPDATE,
            action=CommunicationPreferenceEvent.Action.CLIENT_ALLOW,
            portal_principal_id=source_principal.pk,
            evidence_sha256="4" * 64,
        )
    people_services.merge_people(
        owner,
        creation.organization.pk,
        source_person_id=source.pk,
        target_person_id=person.pk,
        source_revision=source.revision,
        target_revision=person.revision,
        reason="Fusión que no debe convertir una baja previa en permiso.",
        idempotency_key=uuid4(),
    )
    service_template = create_template(
        owner,
        creation.organization.pk,
        name="Actualización de servicio conservadora",
        channel=Channel.EMAIL,
        purpose=Purpose.SERVICE_UPDATE,
        subject_template="Actualización",
        body_template="Hola {name}",
        variable_names=["name"],
    )
    service_version_id = service_template["versions"][0]["id"]
    publish_template(owner, creation.organization.pk, version_id=service_version_id)
    configure_policy(
        owner,
        creation.organization.pk,
        purpose=Purpose.SERVICE_UPDATE,
        channel=Channel.EMAIL,
        requires_consent=True,
        allow_unsubscribe=True,
        rationale="Política sintética para verificar una supresión conservadora.",
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        request_intent(
            creation.organization.pk,
            purpose=Purpose.SERVICE_UPDATE,
            channel=Channel.EMAIL,
            person_id=source.pk,
            template_version_id=service_version_id,
            aggregate_type="event_request",
            aggregate_id=UUID(str(capture["event_request_id"])),
            variables={"name": person.full_name},
            idempotency_key="merged-preference-remains-suppressed",
        )
    with infrastructure_tenant_scope(creation.organization.pk, purpose="communications_worker"):
        suppressed_outbox_id = claim_next(
            creation.organization.pk, worker_id="merge-preference-worker"
        )
        assert suppressed_outbox_id is not None
        assert prepare_delivery(creation.organization.pk, suppressed_outbox_id) is None
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        suppressed = CommunicationOutbox.objects.get(pk=suppressed_outbox_id)
        assert suppressed.message is not None
        assert suppressed.message.status == LogicalMessage.Status.SUPPRESSED


@pytest.mark.django_db
def test_approved_capture_acknowledgement_creates_only_semantic_crm_interaction() -> None:
    owner, creation = _organization("crm-semantic")
    locator, version, _ = _published_form(owner, creation)
    capture = submit_public_form(
        locator, idempotency_key="crm-semantic-person", data=_submission(version)
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        event_request = EventRequest.objects.select_related("person").get(
            pk=UUID(str(capture["event_request_id"]))
        )
    template = create_template(
        owner,
        creation.organization.pk,
        name="Acuse de captación",
        channel=Channel.EMAIL,
        purpose=Purpose.CAPTURE_ACKNOWLEDGEMENT,
        subject_template="Recibimos tu solicitud",
        body_template="Hola {name}, recibimos tu solicitud.",
        variable_names=["name"],
    )
    version_id = template["versions"][0]["id"]
    publish_template(owner, creation.organization.pk, version_id=version_id)
    configure_policy(
        owner,
        creation.organization.pk,
        purpose=Purpose.CAPTURE_ACKNOWLEDGEMENT,
        channel=Channel.EMAIL,
        requires_consent=False,
        allow_unsubscribe=False,
        rationale="Política técnica sintética aprobada para la prueba.",
    )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        intent = request_intent(
            creation.organization.pk,
            purpose=Purpose.CAPTURE_ACKNOWLEDGEMENT,
            channel=Channel.EMAIL,
            person_id=event_request.person_id,
            template_version_id=version_id,
            aggregate_type="event_request",
            aggregate_id=event_request.pk,
            variables={"name": event_request.person.full_name},
            idempotency_key="crm-semantic-once",
        )
    with infrastructure_tenant_scope(creation.organization.pk, purpose="communications_worker"):
        outbox_id = claim_next(creation.organization.pk, worker_id="crm-worker")
        assert outbox_id is not None
        request = prepare_delivery(creation.organization.pk, outbox_id)
        assert request is not None
        complete_delivery(
            creation.organization.pk,
            outbox_id,
            DeliveryResult(True, "deterministic", "crm-provider-message", response_code="202"),
        )
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        message = LogicalMessage.objects.get(intent=intent)
        interaction = Interaction.objects.get(communication_reference=message.pk)
        assert interaction.person_id == event_request.person_id
        assert interaction.event_request_id == event_request.pk
        assert interaction.recorder_kind == Interaction.RecorderKind.COMMUNICATIONS
        assert interaction.responsible_membership_id is None
        assert interaction.recorded_by_membership_id is None
        assert interaction.communication_purpose == Purpose.CAPTURE_ACKNOWLEDGEMENT
        assert interaction.summary == "Acuse de recepción de la solicitud emitido."
        assert "provider" not in interaction.summary.lower()


@pytest.mark.django_db
@override_settings(COMMUNICATIONS_PROVIDER="deterministic")
def test_portal_challenge_session_expiry_revocation_and_multiple_grants() -> None:
    owner, creation = _organization("session")
    locator, version, _ = _published_form(owner, creation)
    first = submit_public_form(locator, idempotency_key="event-one", data=_submission(version))
    second_data = _submission(version)
    second_data["starts_at_local"] = (
        datetime.fromisoformat(str(second_data["starts_at_local"])) + timedelta(days=1)
    ).strftime("%Y-%m-%dT%H:%M")
    second = submit_public_form(locator, idempotency_key="event-two", data=second_data)
    assert first["event_request_id"] != second["event_request_id"]
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        assert PortalGrant.objects.count() == 2
    template = create_template(
        owner,
        creation.organization.pk,
        name="Magic link",
        channel=Channel.EMAIL,
        purpose=Purpose.PORTAL_AUTHENTICATION,
        subject_template="Acceso",
        body_template="Tu código es {code}",
        variable_names=["code"],
    )
    publish_template(owner, creation.organization.pk, version_id=template["versions"][0]["id"])
    rejected_challenge, _ = start_challenge(
        locator, channel=Channel.EMAIL, contact_value="cliente.portal@example.com"
    )
    rejected_locator = str(rejected_challenge).rsplit(".", 1)[0]
    for _attempt in range(5):
        with pytest.raises(PortalError):
            verify_challenge(f"{rejected_locator}.not-the-code")
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        rejected_reference = PortalLocator.objects.get(
            token_hmac=digest(rejected_locator, purpose="locator")
        ).target_reference
        rejected = PortalChallenge.objects.get(pk=rejected_reference)
        assert rejected.attempt_count == rejected.max_attempts
        assert rejected.revoked_at is not None
    challenge, intent_id = start_challenge(
        locator, channel=Channel.EMAIL, contact_value="cliente.portal@example.com"
    )
    assert challenge is not None and intent_id is not None
    token, session = verify_challenge(challenge)
    assert len(portal_events(token)) == 2
    expired_session_id = session.pk
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        session.idle_expires_at = timezone.now()
        session.save(update_fields=["idle_expires_at"])
    with pytest.raises(PortalError) as expired:
        portal_events(token)
    assert expired.value.code == "session_expired"
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        assert PortalSession.objects.get(pk=expired_session_id).revoked_at is not None

    challenge, _ = start_challenge(
        locator,
        channel=Channel.EMAIL,
        contact_value="cliente.portal@example.com",
        kind=PortalChallenge.Kind.RECOVERY,
    )
    token, _ = verify_challenge(str(challenge))
    revoke_session(token)
    with pytest.raises(PortalError):
        portal_events(token)
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        assert PortalChallenge.objects.filter(consumed_at__isnull=False).count() == 2
        assert PortalChallenge.objects.filter(
            kind=PortalChallenge.Kind.RECOVERY, consumed_at__isnull=False
        ).exists()
        assert PortalSession.objects.filter(revoked_at__isnull=False).exists()


@pytest.mark.django_db
@override_settings(COMMUNICATIONS_PROVIDER="deterministic")
def test_portal_proposal_projection_is_read_only_minimized_and_derives_expiration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, creation = _organization("portal-quotations")
    locator, form_version, _ = _published_form(owner, creation)
    captured = submit_public_form(
        locator,
        idempotency_key="quotation-event",
        data=_submission(form_version),
    )
    event_request_id = UUID(str(captured["event_request_id"]))
    quotation = create_quotation(
        owner,
        creation.organization.pk,
        request_id=event_request_id,
        valid_until=timezone.now() + timedelta(days=3),
    )
    quotation_id = UUID(str(quotation["id"]))
    draft = quotation["versions"][0]
    replace_quotation_draft(
        owner,
        creation.organization.pk,
        quotation_id=quotation_id,
        version=1,
        revision=draft["revision"],
        valid_until=timezone.now() + timedelta(days=3),
        notes="Nota interna que el Portal no debe exponer.",
        lines=[
            {
                "description": "Servicio visible",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("250.00"),
                "discount_amount": Decimal("0.00"),
            }
        ],
    )
    issue_quotation_version(owner, creation.organization.pk, quotation_id=quotation_id, version=1)
    token, grant = _portal_session_for_event(
        owner,
        creation.organization.pk,
        event_request_id,
        scopes=["event:read", "quotation:read"],
        absolute_days=30,
    )
    issued = portal_event(token, grant_id=grant.pk)["quotations"]
    assert isinstance(issued, list)
    assert issued[0]["status"] == QuotationVersion.Status.ISSUED
    assert issued[0]["is_expired"] is False
    assert "notes" not in issued[0]

    quotation = create_quotation_version(
        owner,
        creation.organization.pk,
        quotation_id=quotation_id,
        valid_until=timezone.now() + timedelta(days=4),
    )
    second_draft = next(item for item in quotation["versions"] if item["version"] == 2)
    replace_quotation_draft(
        owner,
        creation.organization.pk,
        quotation_id=quotation_id,
        version=2,
        revision=second_draft["revision"],
        valid_until=timezone.now() + timedelta(days=4),
        notes="Segunda nota interna.",
        lines=[
            {
                "description": "Servicio visible revisado",
                "unit_label": "evento",
                "quantity": Decimal("1.000"),
                "unit_price": Decimal("275.00"),
                "discount_amount": Decimal("0.00"),
            }
        ],
    )
    issue_quotation_version(owner, creation.organization.pk, quotation_id=quotation_id, version=2)
    superseded = portal_event(token, grant_id=grant.pk)["quotations"]
    assert isinstance(superseded, list)
    assert [item["status"] for item in superseded] == [
        QuotationVersion.Status.SUPERSEDED,
        QuotationVersion.Status.ISSUED,
    ]
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.SALES_READ):
        second = QuotationVersion.objects.get(quotation_id=quotation_id, version=2)
        future = second.valid_until + timedelta(seconds=1)
        portal_session = PortalSession.objects.get(token_hmac=digest(token, purpose="session"))
        portal_session.idle_expires_at = future + timedelta(minutes=1)
        portal_session.save(update_fields=["idle_expires_at"])
    with monkeypatch.context() as context:
        context.setattr(timezone, "now", lambda: future)
        expired = portal_event(token, grant_id=grant.pk)["quotations"]
        assert isinstance(expired, list)
        assert expired[1]["status"] == QuotationVersion.Status.ISSUED
        assert expired[1]["is_expired"] is True
        assert "expired" not in QuotationVersion.Status.values

        with authorized_tenant_scope(owner, creation.organization.pk, Capability.SALES_MANAGE):
            QuotationVersion.objects.filter(quotation_id=quotation_id, version=2).update(
                status=QuotationVersion.Status.WITHDRAWN
            )
        withdrawn = portal_event(token, grant_id=grant.pk)["quotations"]
        assert isinstance(withdrawn, list)
        assert withdrawn[1]["withdrawn"] is True
        assert withdrawn[1]["lines"] == ()
        assert withdrawn[1]["total"] is None
        assert withdrawn[1]["currency"] is None
        assert withdrawn[1]["event_type"] is None
        assert withdrawn[1]["starts_at"] is None


@pytest.mark.django_db
def test_portal_schedule_tracks_rescheduling_and_cancellation_without_private_timing_data() -> None:
    case = build_document_case("p14-portal-schedule")
    event_request_id = UUID(str(case.quotation["event_request_id"]))
    token, grant = _portal_session_for_event(
        case.owner,
        case.organization_id,
        event_request_id,
        scopes=["event:read", "schedule:read"],
    )
    initial = portal_event(token, grant_id=grant.pk)["schedule"]
    assert isinstance(initial, dict)
    assert initial["status"] == "pending_confirmation"
    assert set(initial) == {
        "root_reservation_id",
        "starts_at",
        "ends_at",
        "timezone_name",
        "venue_name",
        "space_name",
        "status",
    }
    local_start = timezone.localtime(case.reservation["starts_at"]) + timedelta(days=2)
    local_end = timezone.localtime(case.reservation["ends_at"]) + timedelta(days=2)
    changed = reschedule_reservation(
        case.owner,
        case.organization_id,
        reservation_id=UUID(str(case.reservation["id"])),
        revision=int(case.reservation["revision"]),
        idempotency_key=uuid4(),
        space_id=UUID(str(case.reservation["space_id"])),
        starts_at_local=local_start.replace(tzinfo=None),
        ends_at_local=local_end.replace(tzinfo=None),
        timezone_name="America/Guayaquil",
        reason="Cambio solicitado antes de confirmar.",
        commercial_terms_unchanged=True,
    )
    after_change = portal_event(token, grant_id=grant.pk)["schedule"]
    assert isinstance(after_change, dict)
    assert after_change["root_reservation_id"] == initial["root_reservation_id"]
    assert after_change["starts_at"] == changed["reservation"]["starts_at"]
    with authorized_tenant_scope(case.owner, case.organization_id, Capability.PUBLIC_FORM_READ):
        grant.refresh_from_db()
        assert grant.root_reservation_reference == UUID(str(case.reservation["root_id"]))

    cancel_reservation(
        case.owner,
        case.organization_id,
        reservation_id=UUID(str(changed["reservation"]["id"])),
        reason="El cliente canceló la solicitud antes de confirmar.",
    )
    cancelled = portal_event(token, grant_id=grant.pk)["schedule"]
    assert isinstance(cancelled, dict)
    assert cancelled["status"] == "cancelled"


@pytest.mark.django_db
def test_portal_receivables_is_a_minimized_projection_of_the_p10_ledger() -> None:
    case = build_document_case("p14-portal-receivables")
    event_request_id = UUID(str(case.quotation["event_request_id"]))
    confirm_reservation(
        case.owner,
        case.organization_id,
        reservation_id=UUID(str(case.reservation["id"])),
        kind="waiver",
        waiver_reason="Confirmación sin anticipo para probar la proyección.",
    )
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.RECEIVABLES_READ
    ) as authorization:
        obligation = ReceivableObligation.objects.get(event_request_id=event_request_id)
        payment = record_payment_authorized(
            authorization,
            counterparty_person_id=obligation.counterparty_person_id,
            root_reservation_id=obligation.root_reservation_id,
            amount_value=Decimal("200.00"),
            currency_value="USD",
            reported_at=timezone.now(),
            method=ReceivedPayment.Method.BANK_TRANSFER,
            reference="TRX-P14-SYNTHETIC",
            observation="Pago externo declarado por un actor autorizado.",
            provenance=ReceivedPayment.Provenance.MANUAL,
            evidence_level=ReceivedPayment.EvidenceLevel.INTERNAL_REPORT,
            idempotency_key=uuid4(),
        )
        apply_payment_authorized(
            authorization,
            payment_id=payment.pk,
            obligation_id=obligation.pk,
            amount_value=Decimal("200.00"),
            idempotency_key=uuid4(),
        )
        receipt = issue_receipt_authorized(
            authorization, payment_id=payment.pk, idempotency_key=uuid4()
        )
    token, grant = _portal_session_for_event(
        case.owner,
        case.organization_id,
        event_request_id,
        scopes=["event:read", "receivables:read"],
    )
    projection = portal_event(token, grant_id=grant.pk)["receivables"]
    assert isinstance(projection, dict)
    assert projection["original_total"] == Decimal("1190.00")
    assert projection["balance"] == Decimal("990.00")
    assert projection["derived_status"] == "partial"
    assert projection["payments"] == (
        {
            "id": payment.pk,
            "amount": Decimal("200.00"),
            "currency": "USD",
            "reported_at": payment.reported_at,
            "method": ReceivedPayment.Method.BANK_TRANSFER,
        },
    )
    assert projection["receipts"][0]["visible_number"] == receipt.visible_number
    assert "reference" not in projection["payments"][0]
    assert "snapshot" not in projection["receipts"][0]


@pytest.mark.django_db
@override_settings(COMMUNICATIONS_PROVIDER="deterministic")
def test_portal_session_revalidates_contact_and_merge_collision_never_unions_scopes() -> None:
    owner, creation = _organization("session-revalidation")
    locator, version, _ = _published_form(owner, creation)
    first = submit_public_form(locator, idempotency_key="principal-one", data=_submission(version))
    template = create_template(
        owner,
        creation.organization.pk,
        name="Control de contacto",
        channel=Channel.EMAIL,
        purpose=Purpose.PORTAL_AUTHENTICATION,
        subject_template="Acceso",
        body_template="Código {code}",
        variable_names=["code"],
    )
    publish_template(owner, creation.organization.pk, version_id=template["versions"][0]["id"])
    challenge, _ = start_challenge(
        locator, channel=Channel.EMAIL, contact_value="cliente.portal@example.com"
    )
    first_token, _ = verify_challenge(str(challenge))
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        first_person = EventRequest.objects.get(pk=UUID(str(first["event_request_id"]))).person
    people_services.update_person(
        owner,
        creation.organization.pk,
        person_id=first_person.pk,
        revision=first_person.revision,
        changes={"email": "contacto.actualizado@example.com"},
    )
    with pytest.raises(PortalError) as contact_changed:
        portal_events(first_token)
    assert contact_changed.value.code == "contact_changed"

    second_data = _submission(version, phone="0991234578")
    second_data["email"] = "segunda.identidad@example.com"
    second_data["starts_at_local"] = (
        datetime.fromisoformat(str(second_data["starts_at_local"])) + timedelta(days=2)
    ).strftime("%Y-%m-%dT%H:%M")
    second = submit_public_form(locator, idempotency_key="principal-two", data=second_data)
    second_challenge, _ = start_challenge(
        locator, channel=Channel.EMAIL, contact_value="segunda.identidad@example.com"
    )
    second_token, _ = verify_challenge(str(second_challenge))
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        first_person.refresh_from_db()
        second_person = EventRequest.objects.get(pk=UUID(str(second["event_request_id"]))).person
    people_services.merge_people(
        owner,
        creation.organization.pk,
        source_person_id=second_person.pk,
        target_person_id=first_person.pk,
        source_revision=second_person.revision,
        target_revision=first_person.revision,
        reason="Duplicidad confirmada sin unión automática de privilegios.",
        idempotency_key=uuid4(),
    )
    with pytest.raises(PortalError) as collision:
        portal_events(second_token)
    assert collision.value.code == "principal_merge_collision"
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        assert set(PortalPrincipal.objects.values_list("state", flat=True)) == {
            PortalPrincipal.State.COLLISION
        }
        assert not PortalSession.objects.filter(revoked_at__isnull=True).exists()


@pytest.mark.django_db
@override_settings(
    COMMUNICATIONS_PROVIDER="deterministic",
    COMMUNICATIONS_WEBHOOK_SECRET="deterministic-webhook-test-secret",
)
def test_webhook_rejects_forgery_and_replay_and_deduplicates_valid_events() -> None:
    owner, creation = _organization("webhook-deterministic")
    sender = configure_sender(
        owner,
        creation.organization.pk,
        channel=Channel.EMAIL,
        provider="deterministic",
        ownership="claridez",
        sender_reference="notificaciones@example.test",
        display_name="Organización de prueba",
    )
    locator = create_webhook_locator_internal(
        owner,
        creation.organization.pk,
        sender_identity_id=UUID(str(sender["id"])),
    )["locator"]
    client = Client()
    payload = {
        "type": "delivered",
        "created_at": timezone.now().isoformat(),
        "message_id": "unknown-message",
    }
    now = int(timezone.now().timestamp())
    url = f"/api/v1/webhooks/communications/{locator}/"
    body = json.dumps(payload).encode()
    forged = client.post(
        url,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_WEBHOOK_ID="event-forged",
        HTTP_X_WEBHOOK_TIMESTAMP=str(now),
        HTTP_X_WEBHOOK_SIGNATURE="invalid",
    )
    assert forged.status_code == 400
    replay = client.post(
        url,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_WEBHOOK_ID="event-replay",
        HTTP_X_WEBHOOK_TIMESTAMP=str(now - 301),
        HTTP_X_WEBHOOK_SIGNATURE="test-valid",
    )
    assert replay.status_code == 400
    for _ in range(2):
        signature = hmac.new(
            b"deterministic-webhook-test-secret",
            f"event-once.{now}.".encode() + body,
            hashlib.sha256,
        ).hexdigest()
        accepted = client.post(
            url,
            data=body,
            content_type="application/json",
            HTTP_X_WEBHOOK_ID="event-once",
            HTTP_X_WEBHOOK_TIMESTAMP=str(now),
            HTTP_X_WEBHOOK_SIGNATURE=signature,
        )
        assert accepted.status_code == 202
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        assert ProviderEvent.objects.filter(provider_event_id="event-once").count() == 1


@pytest.mark.django_db
@override_settings(
    COMMUNICATIONS_PROVIDER="resend",
    COMMUNICATIONS_WEBHOOK_SECRET="whsec_dGVzdC1yZXNlbmQtd2ViaG9vay1zZWNyZXQtMzItYnl0ZXMhIQ==",
)
def test_resend_webhook_uses_svix_signature_and_provider_payload() -> None:
    owner, creation = _organization("webhook-resend")
    sender = configure_sender(
        owner,
        creation.organization.pk,
        channel=Channel.EMAIL,
        provider="resend",
        ownership="claridez",
        sender_reference="notificaciones@transactional.example.test",
        display_name="Organización de prueba",
    )
    locator = create_webhook_locator_internal(
        owner,
        creation.organization.pk,
        sender_identity_id=UUID(str(sender["id"])),
    )["locator"]
    event_id = "msg_resend_event_1"
    timestamp = str(int(timezone.now().timestamp()))
    payload = json.dumps(
        {
            "type": "email.delivered",
            "created_at": timezone.now().isoformat(),
            "data": {"email_id": "resend-email-id"},
        },
        separators=(",", ":"),
    ).encode()
    secret = base64.b64decode("dGVzdC1yZXNlbmQtd2ViaG9vay1zZWNyZXQtMzItYnl0ZXMhIQ==")
    signed = f"{event_id}.{timestamp}.".encode() + payload
    signature = base64.b64encode(hmac.new(secret, signed, hashlib.sha256).digest()).decode()
    response = Client().post(
        f"/api/v1/webhooks/communications/{locator}/",
        data=payload,
        content_type="application/json",
        HTTP_SVIX_ID=event_id,
        HTTP_SVIX_TIMESTAMP=timestamp,
        HTTP_SVIX_SIGNATURE=f"v1,{signature}",
    )
    assert response.status_code == 202
    with authorized_tenant_scope(owner, creation.organization.pk, Capability.PUBLIC_FORM_READ):
        event = ProviderEvent.objects.get(provider_event_id=event_id)
        assert event.event_type == "email.delivered"
        assert event.external_message_id == "resend-email-id"


@pytest.mark.django_db
def test_portal_uses_documents_typed_port_for_read_download_and_acceptance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    monkeypatch.setenv("CLARIDEZ_DOCUMENT_STORAGE_ROOT", str(tmp_path / "private"))
    monkeypatch.setenv(
        "CLARIDEZ_DOCUMENT_TOKEN_HMAC_KEY",
        "p14-portal-document-test-hmac-key-with-adequate-length",
    )
    document_settings.cache_clear()
    request.addfinalizer(document_settings.cache_clear)
    case = build_document_case("p14-portal-documents")
    template = create_document_template(
        case.owner,
        case.organization_id,
        name="Contrato para Portal",
        title="Contrato para Portal",
        body_html=(
            "<h1>{{ organization.name }}</h1>"
            "<p>{{ counterparty.full_name }}</p>"
            "{{ quotation.lines_table }}"
            "<p>{{ quotation.currency }} {{ quotation.total }}</p>"
        ),
        variable_schema={
            "version": "claridez-vars-v1",
            "variables": [
                {"name": "organization.name", "required": True},
                {"name": "counterparty.full_name", "required": True},
                {"name": "quotation.lines_table", "required": True},
                {"name": "quotation.currency", "required": True},
                {"name": "quotation.total", "required": True},
            ],
        },
    )
    template_version_id = UUID(str(template["versions"][0]["id"]))
    publish_template_version(case.owner, case.organization_id, version_id=template_version_id)
    record = create_record(
        case.owner,
        case.organization_id,
        root_reservation_id=UUID(str(case.reservation["root_id"])),
    )
    instrument = create_instrument(
        case.owner,
        case.organization_id,
        record_id=UUID(str(record["id"])),
        instrument_type="main_contract",
        title="Contrato principal",
    )
    content = b"%PDF-1.7\n% portal typed port artifact\n"
    content_sha = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        "claridez.documents.jobs.render_pdf",
        lambda _html: RenderedPDF(
            content,
            content_sha,
            len(content),
            "WeasyPrint",
            "69.0",
            "claridez-render-weasyprint-69.0-debian12-v1",
        ),
    )
    issued = issue_instrument(
        case.owner,
        case.organization_id,
        instrument_id=UUID(str(instrument["id"])),
        template_version_id=template_version_id,
        idempotency_key=uuid4(),
        correlation_id="p14-portal-document",
    )
    assert work_once(case.organization_id, worker_id="p14-documents-worker")
    assert work_once(case.organization_id, worker_id="p14-documents-worker")

    event_request_id = UUID(str(case.quotation["event_request_id"]))
    token = random_token()
    now = timezone.now()
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        event_request = EventRequest.objects.select_related("person").get(pk=event_request_id)
        artifact = GeneratedArtifact.objects.get(issued_version_id=issued["id"])
        principal = PortalPrincipal.objects.create(
            organization_id=case.organization_id,
            person_reference=event_request.person_id,
            canonical_set=[str(event_request.person_id)],
        )
        grant = PortalGrant.objects.create(
            organization_id=case.organization_id,
            principal=principal,
            person_reference=event_request.person_id,
            event_request_reference=event_request_id,
            root_reservation_reference=UUID(str(case.reservation["root_id"])),
            scopes=["event:read", "documents:read", "documents:download", "documents:accept"],
            provenance="public_capture",
        )
        session = PortalSession.objects.create(
            organization_id=case.organization_id,
            principal=principal,
            token_hmac=digest(token, purpose="session"),
            contact_fingerprint=digest(event_request.person.email, purpose="contact"),
            contact_revision=event_request.person.revision,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
            last_seen_at=now,
        )
        PortalLocator.objects.create(
            token_hmac=digest(token, purpose="locator"),
            organization_id=case.organization_id,
            kind=PortalLocator.Kind.SESSION,
            target_reference=session.pk,
        )

    documents = portal_documents_for_grant(token, grant_id=grant.pk)
    assert len(documents) == 1
    assert documents[0]["artifact_sha256"] == content_sha
    downloaded, media_type, _ = download_document_for_grant(
        token,
        grant_id=grant.pk,
        issued_version_id=UUID(str(issued["id"])),
        artifact_id=artifact.pk,
        expected_sha256=content_sha,
    )
    assert downloaded == content
    assert media_type == "application/pdf"
    reminder_template = create_template(
        case.owner,
        case.organization_id,
        name="Recordatorio documental coordinado",
        channel=Channel.EMAIL,
        purpose=Purpose.DOCUMENT_REMINDER,
        subject_template="Documento pendiente",
        body_template="Revisa {event_name}",
        variable_names=["event_name"],
    )
    publish_template(
        case.owner,
        case.organization_id,
        version_id=reminder_template["versions"][0]["id"],
    )
    reminder = request_reminder(
        case.owner,
        case.organization_id,
        kind="document",
        source_id=UUID(str(issued["id"])),
        channel=Channel.EMAIL,
        template_version_id=reminder_template["versions"][0]["id"],
        variables={"event_name": event_request.event_type},
        idempotency_key="document-reminder-coordinated",
        not_before=timezone.now() + timedelta(hours=1),
    )
    assert cancel_reminder(
        case.owner,
        case.organization_id,
        kind="document",
        intent_id=UUID(str(reminder["id"])),
        source_version=int(str(reminder["source_version"])),
        reason="El dominio documental sustituyó el recordatorio.",
    )
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.COMMUNICATION_DELIVERY_READ
    ):
        assert (
            CommunicationOutbox.objects.get(intent_id=UUID(str(reminder["id"]))).state
            == "cancelled"
        )
    idempotency_key = uuid4()
    accepted = accept_document_for_grant(
        token,
        grant_id=grant.pk,
        issued_version_id=UUID(str(issued["id"])),
        artifact_id=artifact.pk,
        expected_sha256=content_sha,
        manifestation_text=MANIFESTATION_TEXT,
        manifestation_version=MANIFESTATION_VERSION,
        idempotency_key=idempotency_key,
        request_id="portal-request",
        correlation_id="portal-correlation",
        ip_address=None,
        user_agent=None,
    )
    repeated = accept_document_for_grant(
        token,
        grant_id=grant.pk,
        issued_version_id=UUID(str(issued["id"])),
        artifact_id=artifact.pk,
        expected_sha256=content_sha,
        manifestation_text=MANIFESTATION_TEXT,
        manifestation_version=MANIFESTATION_VERSION,
        idempotency_key=idempotency_key,
        request_id="portal-request-replay",
        correlation_id="portal-correlation",
        ip_address=None,
        user_agent=None,
    )
    repeated_with_another_key = accept_document_for_grant(
        token,
        grant_id=grant.pk,
        issued_version_id=UUID(str(issued["id"])),
        artifact_id=artifact.pk,
        expected_sha256=content_sha,
        manifestation_text=MANIFESTATION_TEXT,
        manifestation_version=MANIFESTATION_VERSION,
        idempotency_key=uuid4(),
        request_id="portal-request-second-key",
        correlation_id="portal-correlation",
        ip_address=None,
        user_agent=None,
    )
    assert repeated == accepted
    assert repeated_with_another_key == accepted
    with authorized_tenant_scope(
        case.owner, case.organization_id, Capability.CONTRACTUAL_RECORD_READ
    ):
        evidence = AcceptanceEvidence.objects.get(pk=accepted)
        assert evidence.provenance == AcceptanceEvidence.Provenance.PORTAL_SESSION
        assert evidence.challenge_id is None
        assert evidence.portal_grant_reference == grant.pk
        assert AcceptanceEvidence.objects.count() == 1
    with pytest.raises(DocumentsPortError) as no_longer_pending:
        request_reminder(
            case.owner,
            case.organization_id,
            kind="document",
            source_id=UUID(str(issued["id"])),
            channel=Channel.EMAIL,
            template_version_id=reminder_template["versions"][0]["id"],
            variables={"event_name": event_request.event_type},
            idempotency_key="document-reminder-after-acceptance",
            not_before=timezone.now() + timedelta(hours=1),
        )
    assert no_longer_pending.value.code == "reminder_not_applicable"


@pytest.mark.django_db
def test_public_locator_is_opaque_tenant_bound_rotatable_and_revocable() -> None:
    owner, creation = _organization("locator-a")
    other_owner, other = _organization("locator-b")
    locator, version, _ = _published_form(owner, creation)
    other_locator, _, _ = _published_form(other_owner, other)
    assert creation.organization.pk.hex not in locator
    assert (
        read_public_form(locator)["organization"] != read_public_form(other_locator)["organization"]
    )
    with pytest.raises(PortalError):
        read_public_form(locator + "altered")
    rotated = rotate_form_locator(
        owner,
        creation.organization.pk,
        form_id=version.form_id,
    )["locator"]
    with pytest.raises(PortalError):
        read_public_form(locator)
    assert read_public_form(rotated)["title"] == version.title
    retire_form(owner, creation.organization.pk, form_id=version.form_id)
    with pytest.raises(PortalError):
        read_public_form(rotated)


@pytest.mark.django_db
def test_public_http_surface_enforces_csrf_origin_antiabuse_and_safe_headers() -> None:
    owner, creation = _organization("public-http")
    locator, version, _ = _published_form(owner, creation)
    client = Client(enforce_csrf_checks=True)
    url = f"/api/v1/public/forms/{locator}/"
    public_form = client.get(url, REMOTE_ADDR="192.0.2.50")
    assert public_form.status_code == 200
    assert public_form["Cache-Control"] == "private, no-store"
    assert public_form["Referrer-Policy"] == "no-referrer"
    csrf_token = public_form.cookies["csrftoken"].value
    payload = {
        **_submission(version),
        "idempotency_key": "public-http-once",
        "antiabuse_token": f"test-pass:{uuid4()}",
        "antiabuse_hostname": "testserver",
    }
    missing_csrf = client.post(
        url,
        data=json.dumps(payload, default=str),
        content_type="application/json",
        REMOTE_ADDR="192.0.2.50",
    )
    assert missing_csrf.status_code == 403
    invalid_origin = client.post(
        url,
        data=json.dumps(payload, default=str),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_ORIGIN="https://evil.example",
        REMOTE_ADDR="192.0.2.50",
    )
    assert invalid_origin.status_code == 403
    missing_verify_csrf = client.post(
        "/api/v1/portal/auth/verify/",
        data=json.dumps({"challenge": "opaque-locator.123456"}),
        content_type="application/json",
        REMOTE_ADDR="192.0.2.50",
    )
    assert missing_verify_csrf.status_code == 403
    invalid_verify_origin = client.post(
        "/api/v1/portal/auth/verify/",
        data=json.dumps({"challenge": "opaque-locator.123456"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_ORIGIN="https://evil.example",
        REMOTE_ADDR="192.0.2.50",
    )
    assert invalid_verify_origin.status_code == 403
    invalid_hostname = client.post(
        url,
        data=json.dumps(
            {
                **payload,
                "antiabuse_token": f"test-pass:{uuid4()}",
                "antiabuse_hostname": "evil.example",
            },
            default=str,
        ),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_ORIGIN="http://testserver",
        REMOTE_ADDR="192.0.2.50",
    )
    assert invalid_hostname.status_code == 400
    accepted = client.post(
        url,
        data=json.dumps(payload, default=str),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_ORIGIN="http://testserver",
        REMOTE_ADDR="192.0.2.50",
    )
    assert accepted.status_code == 201
    assert accepted["Cache-Control"] == "private, no-store"
    assert accepted["Referrer-Policy"] == "no-referrer"


@pytest.mark.django_db
def test_public_antiabuse_tokens_are_single_use_and_rate_limit_fails_closed() -> None:
    token = f"test-pass:{uuid4()}"
    verify_antiabuse(
        token,
        action="public_form_submit",
        hostname="testserver",
        remote_ip="192.0.2.51",
    )
    with pytest.raises(PortalError) as replay:
        verify_antiabuse(
            token,
            action="public_form_submit",
            hostname="testserver",
            remote_ip="192.0.2.51",
        )
    assert replay.value.code == "antiabuse_replay"
    key = f"rate-test:{uuid4()}"
    consume_rate_limit(action="test", key=key, limit=2, window_seconds=60)
    consume_rate_limit(action="test", key=key, limit=2, window_seconds=60)
    with pytest.raises(PortalError) as limited:
        consume_rate_limit(action="test", key=key, limit=2, window_seconds=60)
    assert limited.value.code == "rate_limited"


def test_p14_import_boundaries_keep_ports_acyclic_and_p9_private() -> None:
    source = Path(__file__).parents[1] / "src" / "claridez"
    forbidden_portal = {
        "claridez.people.models",
        "claridez.commercial.models",
        "claridez.documents.models",
        "claridez.scheduling.models",
        "claridez.receivables.models",
        "claridez.operations.models",
        "claridez.operations.advanced_models",
    }
    for file in (source / "portal").rglob("*.py"):
        if "migrations" in file.parts:
            continue
        tree = ast.parse(file.read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not (imported & forbidden_portal), file
        text = file.read_text(encoding="utf-8")
        for private_name in (
            "ExternalAccessGrant",
            "ExternalDocumentSession",
            "AcceptanceChallenge",
            "ExternalTokenLocator",
            "ExternalRateLimitBucket",
            "DocumentJob",
        ):
            assert private_name not in text, (file, private_name)

    for file in (source / "communications").rglob("*.py"):
        if "migrations" in file.parts:
            continue
        text = file.read_text(encoding="utf-8")
        for forbidden_dependency in (
            "claridez.commercial",
            "claridez.documents",
            "claridez.operations",
            "claridez.portal",
            "claridez.receivables",
            "claridez.scheduling",
        ):
            assert forbidden_dependency not in text, (file, forbidden_dependency)
    assert "claridez.portal" not in (source / "operations" / "public.py").read_text(
        encoding="utf-8"
    )
