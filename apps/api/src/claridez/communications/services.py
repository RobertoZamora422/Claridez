from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import asdict
from datetime import timedelta
from string import Formatter
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from claridez.external_secrets import short_single_use_code
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.people.public import (
    canonical_cluster_ids,
    canonical_person_id,
    contact_for_external_control,
    effective_consent,
)

from .errors import conflict, invalid, unavailable
from .models import (
    Channel,
    CommunicationAuditEvent,
    CommunicationIntent,
    CommunicationOutbox,
    CommunicationPolicy,
    CommunicationPreferenceEvent,
    CommunicationTemplate,
    CommunicationTemplateVersion,
    DeliveryAttempt,
    LogicalMessage,
    ProviderEvent,
    Purpose,
    SenderIdentity,
)
from .providers import DeliveryRequest, DeliveryResult, provider_for


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _validated_template_content(
    subject_template: str, body_template: str, variable_names: list[str]
) -> tuple[list[str], str]:
    names = sorted({str(item).strip() for item in variable_names if str(item).strip()})
    if any(re.fullmatch(r"[a-z][a-z0-9_]{0,79}", name) is None for name in names):
        raise invalid("Las variables de plantilla no son válidas.")
    referenced: set[str] = set()
    try:
        for template in (subject_template, body_template):
            for _, field_name, format_spec, conversion in Formatter().parse(template):
                if field_name is None:
                    continue
                if field_name not in names or format_spec or conversion not in {None, "s"}:
                    raise invalid("La plantilla contiene una interpolación no permitida.")
                referenced.add(field_name)
    except ValueError:
        raise invalid("La sintaxis de la plantilla no es válida.") from None
    if referenced != set(names):
        raise invalid("Las variables declaradas y utilizadas no coinciden.")
    return names, _json_hash(
        {"subject": subject_template, "body": body_template, "variables": names}
    )


def _template_data(row: CommunicationTemplate) -> dict[str, Any]:
    return {
        "id": row.pk,
        "name": row.name,
        "channel": row.channel,
        "purpose": row.purpose,
        "is_active": row.is_active,
        "versions": [
            {
                "id": version.pk,
                "version": version.version,
                "status": version.status,
                "subject_template": version.subject_template,
                "body_template": version.body_template,
                "variable_names": version.variable_names,
                "content_sha256": version.content_sha256,
            }
            for version in row.versions.order_by("version", "id")
        ],
    }


def list_templates(actor: User, organization_id: UUID) -> tuple[dict[str, Any], ...]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_TEMPLATE_READ
    ) as authorization:
        rows = CommunicationTemplate.objects.filter(
            organization_id=authorization.organization_id
        ).prefetch_related("versions")
        return tuple(_template_data(row) for row in rows.order_by("name", "id"))


def create_template(
    actor: User,
    organization_id: UUID,
    *,
    name: str,
    channel: str,
    purpose: str,
    subject_template: str,
    body_template: str,
    variable_names: list[str],
) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_TEMPLATE_MANAGE
    ) as authorization:
        if channel not in Channel.values or purpose not in Purpose.values:
            raise invalid("El canal o propósito no es válido.")
        if purpose == Purpose.MARKETING:
            raise invalid("Marketing permanece deshabilitado en P14 base.")
        allowed_by_role = {
            "commercial": {
                Purpose.CAPTURE_ACKNOWLEDGEMENT,
                Purpose.SERVICE_UPDATE,
                Purpose.CLIENT_ACTION,
            },
            "operations": {
                Purpose.EVENT_REMINDER,
                Purpose.SERVICE_UPDATE,
                Purpose.CLIENT_ACTION,
            },
            "finance": {Purpose.PAYMENT_REMINDER, Purpose.SERVICE_UPDATE},
        }
        if (
            authorization.role in allowed_by_role
            and purpose not in allowed_by_role[authorization.role]
        ):
            raise invalid("El propósito no corresponde al ámbito del perfil.")
        canonical_names, content_sha = _validated_template_content(
            subject_template, body_template, variable_names
        )
        try:
            row = CommunicationTemplate.objects.create(
                organization_id=authorization.organization_id,
                name=name.strip(),
                channel=channel,
                purpose=purpose,
                created_by_membership_id=authorization.membership_id,
            )
            CommunicationTemplateVersion.objects.create(
                organization_id=authorization.organization_id,
                template=row,
                version=1,
                subject_template=subject_template,
                body_template=body_template,
                variable_names=canonical_names,
                content_sha256=content_sha,
            )
        except IntegrityError as error:
            raise conflict("template_conflict", "La plantilla ya existe.") from error
        return _template_data(row)


def publish_template(actor: User, organization_id: UUID, *, version_id: UUID) -> dict[str, Any]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_TEMPLATE_PUBLISH
    ) as authorization:
        try:
            row = (
                CommunicationTemplateVersion.objects.select_for_update()
                .select_related("template")
                .get(organization_id=authorization.organization_id, pk=version_id)
            )
        except CommunicationTemplateVersion.DoesNotExist:
            raise unavailable("La versión de plantilla") from None
        if row.status != CommunicationTemplateVersion.Status.DRAFT:
            raise conflict("immutable_template_version", "La versión ya no puede modificarse.")
        names, content_sha = _validated_template_content(
            row.subject_template, row.body_template, list(row.variable_names)
        )
        if names != row.variable_names or content_sha != row.content_sha256:
            raise conflict(
                "template_integrity_failed",
                "El contenido de la plantilla no coincide con su hash canónico.",
            )
        now = timezone.now()
        row.status = CommunicationTemplateVersion.Status.PUBLISHED
        row.published_at = now
        row.published_by_membership_id = authorization.membership_id
        row.save(update_fields=["status", "published_at", "published_by_membership_id"])
        return _template_data(row.template)


def create_template_version(
    actor: User,
    organization_id: UUID,
    *,
    template_id: UUID,
    subject_template: str,
    body_template: str,
    variable_names: list[str],
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_TEMPLATE_MANAGE
    ) as authorization:
        try:
            template = CommunicationTemplate.objects.select_for_update().get(
                organization_id=authorization.organization_id,
                pk=template_id,
                is_active=True,
            )
        except CommunicationTemplate.DoesNotExist:
            raise unavailable("La plantilla") from None
        if template.versions.filter(status=CommunicationTemplateVersion.Status.DRAFT).exists():
            raise conflict("draft_exists", "La plantilla ya tiene un borrador.")
        next_version = (template.versions.aggregate(value=Max("version"))["value"] or 0) + 1
        names, content_sha = _validated_template_content(
            subject_template, body_template, variable_names
        )
        row = CommunicationTemplateVersion.objects.create(
            organization_id=authorization.organization_id,
            template=template,
            version=next_version,
            subject_template=subject_template,
            body_template=body_template,
            variable_names=names,
            content_sha256=content_sha,
        )
        return {"id": row.pk, "version": row.version, "status": row.status}


def _effective_suppression(
    organization_id: UUID,
    *,
    person_id: UUID,
    channel: str,
    purpose: str,
    fingerprint: str,
) -> str:
    cluster = set(canonical_cluster_ids(organization_id, person_id))
    canonical_person = canonical_person_id(organization_id, person_id)
    rows = CommunicationPreferenceEvent.objects.filter(
        Q(purpose=purpose)
        | Q(
            action__in=[
                CommunicationPreferenceEvent.Action.HARD_BOUNCE,
                CommunicationPreferenceEvent.Action.TECHNICAL_RELEASE,
            ],
            destination_fingerprint=fingerprint,
        ),
        organization_id=organization_id,
        channel=channel,
        person_reference__in=cluster,
    ).order_by("occurred_at", "created_at", "id")
    client_allowed = False
    admin_suppressed = False
    hard_bounced = False
    for row in rows:
        if (
            row.purpose == purpose
            and row.action == CommunicationPreferenceEvent.Action.CLIENT_UNSUBSCRIBE
        ):
            client_allowed = False
        elif (
            row.purpose == purpose
            and row.action == CommunicationPreferenceEvent.Action.CLIENT_ALLOW
            and row.person_reference == canonical_person
        ):
            client_allowed = True
        elif (
            row.purpose == purpose
            and row.action == CommunicationPreferenceEvent.Action.ADMIN_SUPPRESS
        ):
            admin_suppressed = True
        elif (
            row.purpose == purpose
            and row.action == CommunicationPreferenceEvent.Action.ADMIN_RELEASE
        ):
            admin_suppressed = False
        elif (
            row.action == CommunicationPreferenceEvent.Action.HARD_BOUNCE
            and row.destination_fingerprint == fingerprint
        ):
            hard_bounced = True
        elif (
            row.action == CommunicationPreferenceEvent.Action.TECHNICAL_RELEASE
            and row.destination_fingerprint == fingerprint
            and row.evidence_sha256
        ):
            hard_bounced = False
    if (
        not client_allowed
        and rows.filter(
            purpose=purpose,
            action=CommunicationPreferenceEvent.Action.CLIENT_UNSUBSCRIBE,
        ).exists()
    ):
        return "client_unsubscribe"
    if hard_bounced:
        return "hard_bounce"
    if admin_suppressed:
        return "administrative"
    return ""


def append_preference(
    organization_id: UUID,
    *,
    person_id: UUID,
    channel: str,
    purpose: str,
    action: str,
    fingerprint: str = "",
    actor_membership_id: UUID | None = None,
    portal_principal_id: UUID | None = None,
    evidence_sha256: str = "",
    reason: str = "",
) -> CommunicationPreferenceEvent:
    if (
        action not in CommunicationPreferenceEvent.Action.values
        or channel not in Channel.values
        or purpose not in Purpose.values
    ):
        raise invalid("La acción de preferencia no es válida.")
    if action in {
        CommunicationPreferenceEvent.Action.CLIENT_ALLOW,
        CommunicationPreferenceEvent.Action.CLIENT_UNSUBSCRIBE,
    } and (
        portal_principal_id is None
        or actor_membership_id is not None
        or re.fullmatch(r"[0-9a-f]{64}", evidence_sha256) is None
    ):
        raise invalid("La preferencia del cliente exige una acción autenticada del cliente.")
    if action in {
        CommunicationPreferenceEvent.Action.ADMIN_SUPPRESS,
        CommunicationPreferenceEvent.Action.ADMIN_RELEASE,
    } and (actor_membership_id is None or portal_principal_id is not None):
        raise invalid("La acción administrativa exige un actor interno.")
    if action == CommunicationPreferenceEvent.Action.HARD_BOUNCE and (
        len(fingerprint) != 64
        or re.fullmatch(r"[0-9a-f]{64}", evidence_sha256) is None
        or actor_membership_id is not None
        or portal_principal_id is not None
    ):
        raise invalid("El rebote técnico exige un fingerprint válido.")
    if action == CommunicationPreferenceEvent.Action.ADMIN_RELEASE:
        existing = CommunicationPreferenceEvent.objects.filter(
            organization_id=organization_id,
            person_reference__in=canonical_cluster_ids(organization_id, person_id),
            channel=channel,
            purpose=purpose,
            action__in=[
                CommunicationPreferenceEvent.Action.CLIENT_UNSUBSCRIBE,
                CommunicationPreferenceEvent.Action.HARD_BOUNCE,
            ],
        ).exists()
        if existing:
            raise conflict(
                "protected_suppression",
                "Una acción interna no puede restaurar una baja del cliente o un rebote técnico.",
            )
    if action == CommunicationPreferenceEvent.Action.TECHNICAL_RELEASE and (
        len(fingerprint) != 64
        or len(evidence_sha256) != 64
        or actor_membership_id is None
        or portal_principal_id is not None
    ):
        raise invalid("La liberación técnica exige actor y evidencia.")
    cluster = canonical_cluster_ids(organization_id, person_id)
    canonical_person = canonical_person_id(organization_id, person_id)
    return CommunicationPreferenceEvent.objects.create(
        organization_id=organization_id,
        person_reference=canonical_person,
        canonical_set=[str(item) for item in cluster],
        channel=channel,
        purpose=purpose,
        destination_fingerprint=fingerprint,
        action=action,
        actor_membership_id=actor_membership_id,
        portal_principal_reference=portal_principal_id,
        evidence_sha256=evidence_sha256,
        reason=reason[:500],
        occurred_at=timezone.now(),
    )


def _policy_allows(organization_id: UUID, *, purpose: str, channel: str, person_id: UUID) -> bool:
    if purpose == Purpose.PORTAL_AUTHENTICATION:
        return True
    if purpose == Purpose.MARKETING:
        return False
    policy = (
        CommunicationPolicy.objects.filter(
            organization_id=organization_id,
            purpose=purpose,
            channel=channel,
            status=CommunicationPolicy.Status.APPROVED,
        )
        .order_by("-version")
        .first()
    )
    if policy is None:
        return False
    if channel == Channel.WHATSAPP or policy.requires_consent:
        consent_channel = "whatsapp" if channel == Channel.WHATSAPP else "email"
        return (
            effective_consent(
                organization_id, person_id=person_id, purpose=purpose, channel=consent_channel
            )
            == "granted"
        )
    return True


def request_intent(
    organization_id: UUID,
    *,
    purpose: str,
    channel: str,
    person_id: UUID,
    template_version_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
    variables: dict[str, object],
    idempotency_key: str,
    requested_by_membership_id: UUID | None = None,
    source_version: int = 1,
    causal_key: str = "",
    causal_sequence: int | None = None,
    not_before: Any = None,
) -> CommunicationIntent:
    if purpose not in Purpose.values or channel not in Channel.values:
        raise invalid("El propósito o canal no es válido.")
    if (
        source_version < 1
        or not idempotency_key.strip()
        or causal_key != causal_key.strip()
        or bool(causal_key) != (causal_sequence is not None)
    ):
        raise invalid("La identidad causal de la intención no es válida.")
    if purpose == Purpose.MARKETING:
        raise invalid("Marketing permanece deshabilitado en P14 base.")
    if purpose == Purpose.PORTAL_AUTHENTICATION:
        try:
            challenge_reference = UUID(str(variables["challenge_reference"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise invalid("La autenticación solo admite una referencia de challenge.") from None
        if (
            set(variables) != {"challenge_reference"}
            or aggregate_type != "portal_challenge"
            or challenge_reference != aggregate_id
        ):
            raise invalid("La autenticación solo admite una referencia de challenge.")
    try:
        template = CommunicationTemplateVersion.objects.select_related("template").get(
            organization_id=organization_id,
            pk=template_version_id,
            status=CommunicationTemplateVersion.Status.PUBLISHED,
            template__purpose=purpose,
            template__channel=channel,
            template__is_active=True,
        )
    except CommunicationTemplateVersion.DoesNotExist:
        raise unavailable("La plantilla publicada") from None
    expected_variables = (
        {"challenge_reference"}
        if purpose == Purpose.PORTAL_AUTHENTICATION
        else set(template.variable_names)
    )
    if set(variables) != expected_variables:
        raise invalid("Las variables no coinciden con la versión publicada.")
    canonical = canonical_person_id(organization_id, person_id)
    payload = {
        "purpose": purpose,
        "channel": channel,
        "person": str(canonical),
        "template": str(template.pk),
        "aggregate": [aggregate_type, str(aggregate_id), source_version],
        "variables": variables,
        "causal_key": causal_key,
        "causal_sequence": causal_sequence,
        "not_before": not_before,
    }
    try:
        with transaction.atomic():
            intent = CommunicationIntent.objects.create(
                organization_id=organization_id,
                purpose=purpose,
                channel=channel,
                recipient_person_id=canonical,
                template_version=template,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                variables=variables,
                payload_sha256=_json_hash(payload),
                idempotency_key=idempotency_key,
                source_version=source_version,
                causal_key=causal_key,
                causal_sequence=causal_sequence,
                not_before=not_before or timezone.now(),
                requested_by_membership_id=requested_by_membership_id,
            )
            CommunicationOutbox.objects.create(
                organization_id=organization_id,
                intent=intent,
                next_attempt_at=intent.not_before,
            )
            return intent
    except IntegrityError:
        existing = CommunicationIntent.objects.filter(
            organization_id=organization_id, idempotency_key=idempotency_key
        ).first()
        if existing and existing.payload_sha256 == _json_hash(payload):
            return existing
        raise conflict(
            "idempotency_conflict", "La clave ya fue usada con otra solicitud."
        ) from None


def request_intent_internal(
    actor: User, organization_id: UUID, **values: object
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_INTENT_REQUEST
    ) as authorization:
        purpose = str(values.get("purpose", ""))
        source_capabilities: dict[str, Capability] = {
            Purpose.SERVICE_UPDATE: Capability.SALES_READ,
            Purpose.CLIENT_ACTION: Capability.SALES_READ,
        }
        source_capability = source_capabilities.get(purpose)
        if source_capability is None:
            raise invalid("El propósito no admite solicitud interna.")
        authorization.require(source_capability)
        intent = request_intent(
            authorization.organization_id,
            requested_by_membership_id=authorization.membership_id,
            **values,  # type: ignore[arg-type]
        )
        return {"id": intent.pk, "state": intent.state, "created_at": intent.created_at}


@transaction.atomic
def cancel_intent(
    organization_id: UUID,
    *,
    intent_id: UUID,
    source_version: int,
    expected_purpose: str,
    reason: str,
    actor_membership_id: UUID | None = None,
) -> bool:
    """Cancela trabajo aún no entregado por decisión del dominio propietario."""
    try:
        row = (
            CommunicationIntent.objects.select_for_update(of=("self",))
            .select_related("outbox_entry", "message")
            .get(organization_id=organization_id, pk=intent_id)
        )
    except CommunicationIntent.DoesNotExist:
        raise unavailable("La intención") from None
    if row.source_version != source_version:
        raise conflict("stale_intent", "La intención cambió; vuelve a cargarla.")
    if row.purpose != expected_purpose:
        raise unavailable("La intención")
    if row.state == CommunicationIntent.State.CANCELLED:
        return True
    outbox = row.outbox_entry
    if outbox.state in {CommunicationOutbox.State.SUCCEEDED, CommunicationOutbox.State.DEAD}:
        return False
    row.state = CommunicationIntent.State.CANCELLED
    row.save(update_fields=["state"])
    outbox.state = CommunicationOutbox.State.CANCELLED
    outbox.completed_at = timezone.now()
    outbox.lease_expires_at = None
    outbox.claimed_by = ""
    outbox.last_error_category = "obsolete_by_source"
    outbox.last_error_detail = reason[:500]
    outbox.save(
        update_fields=[
            "state",
            "completed_at",
            "lease_expires_at",
            "claimed_by",
            "last_error_category",
            "last_error_detail",
            "updated_at",
        ]
    )
    if hasattr(row, "message") and row.message.status == LogicalMessage.Status.QUEUED:
        row.message.status = LogicalMessage.Status.CANCELLED
        row.message.save(update_fields=["status"])
    CommunicationAuditEvent.objects.create(
        organization_id=organization_id,
        kind="intent_cancelled_by_source",
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        actor_membership_id=actor_membership_id,
        detail={"intent": str(row.pk), "reason_sha256": _text_hash(reason)},
        occurred_at=timezone.now(),
    )
    return True


def published_template_for_purpose(
    organization_id: UUID, *, purpose: str, channel: str
) -> UUID | None:
    row = (
        CommunicationTemplateVersion.objects.filter(
            organization_id=organization_id,
            template__purpose=purpose,
            template__channel=channel,
            template__is_active=True,
            status=CommunicationTemplateVersion.Status.PUBLISHED,
        )
        .order_by("-published_at", "-created_at", "-id")
        .first()
    )
    return row.pk if row else None


def template_version_is_published_for(
    organization_id: UUID, *, version_id: UUID, purpose: str
) -> bool:
    return CommunicationTemplateVersion.objects.filter(
        organization_id=organization_id,
        pk=version_id,
        status=CommunicationTemplateVersion.Status.PUBLISHED,
        template__purpose=purpose,
        template__is_active=True,
    ).exists()


def published_template_channel_if_compatible(
    organization_id: UUID,
    *,
    version_id: UUID,
    purpose: str,
    variable_names: set[str],
) -> str | None:
    row = (
        CommunicationTemplateVersion.objects.select_related("template")
        .filter(
            organization_id=organization_id,
            pk=version_id,
            status=CommunicationTemplateVersion.Status.PUBLISHED,
            template__purpose=purpose,
            template__is_active=True,
        )
        .first()
    )
    if row is None or set(row.variable_names) != variable_names:
        return None
    return row.template.channel


def claim_next(organization_id: UUID, *, worker_id: str) -> UUID | None:
    now = timezone.now()
    lease = now + timedelta(seconds=settings.COMMUNICATIONS_WORKER_LEASE_SECONDS)
    with transaction.atomic():
        row = (
            CommunicationOutbox.objects.select_for_update(skip_locked=True)
            .filter(
                organization_id=organization_id,
                state__in=[CommunicationOutbox.State.PENDING, CommunicationOutbox.State.RETRY],
                next_attempt_at__lte=now,
            )
            .order_by("next_attempt_at", "created_at", "id")
            .first()
        )
        while row is None:
            row = (
                CommunicationOutbox.objects.select_for_update(skip_locked=True)
                .filter(
                    organization_id=organization_id,
                    state=CommunicationOutbox.State.CLAIMED,
                    lease_expires_at__lte=now,
                )
                .order_by("lease_expires_at", "created_at", "id")
                .first()
            )
            if row is None:
                return None
            if row.attempt_count >= row.max_attempts:
                _terminal(row, "attempt_limit_exhausted_after_lease")
                row = None
        row.state = CommunicationOutbox.State.CLAIMED
        row.claimed_by = worker_id[:120]
        row.lease_expires_at = lease
        row.attempt_count += 1
        row.save(
            update_fields=["state", "claimed_by", "lease_expires_at", "attempt_count", "updated_at"]
        )
        return row.pk


def prepare_delivery(organization_id: UUID, outbox_id: UUID) -> DeliveryRequest | None:
    row = (
        CommunicationOutbox.objects.select_for_update(of=("self",))
        .select_related(
            "intent", "intent__template_version", "intent__template_version__template", "message"
        )
        .get(organization_id=organization_id, pk=outbox_id)
    )
    if row.state != CommunicationOutbox.State.CLAIMED:
        return None
    intent = row.intent
    if intent.state in {CommunicationIntent.State.CANCELLED, CommunicationIntent.State.SUPERSEDED}:
        row.state = CommunicationOutbox.State.CANCELLED
        row.completed_at = timezone.now()
        row.save(update_fields=["state", "completed_at", "updated_at"])
        return None
    if (
        CommunicationIntent.objects.filter(
            organization_id=organization_id,
            aggregate_type=intent.aggregate_type,
            aggregate_id=intent.aggregate_id,
            purpose=intent.purpose,
            channel=intent.channel,
            source_version__gt=intent.source_version,
        )
        .exclude(state=CommunicationIntent.State.CANCELLED)
        .exists()
    ):
        intent.state = CommunicationIntent.State.SUPERSEDED
        intent.save(update_fields=["state"])
        row.state = CommunicationOutbox.State.CANCELLED
        row.completed_at = timezone.now()
        row.save(update_fields=["state", "completed_at", "updated_at"])
        return None
    if (
        intent.causal_key
        and intent.causal_sequence is not None
        and CommunicationIntent.objects.filter(
            organization_id=organization_id,
            causal_key=intent.causal_key,
            causal_sequence__lt=intent.causal_sequence,
            outbox_entry__state__in=[
                CommunicationOutbox.State.PENDING,
                CommunicationOutbox.State.CLAIMED,
                CommunicationOutbox.State.RETRY,
            ],
        ).exists()
    ):
        row.state = CommunicationOutbox.State.RETRY
        row.next_attempt_at = timezone.now() + timedelta(seconds=5)
        row.lease_expires_at = None
        row.claimed_by = ""
        row.save(
            update_fields=[
                "state",
                "next_attempt_at",
                "lease_expires_at",
                "claimed_by",
                "updated_at",
            ]
        )
        return None
    contact = contact_for_external_control(
        organization_id, person_id=intent.recipient_person_id, channel=intent.channel
    )
    if contact is None:
        _terminal(row, "recipient_unavailable")
        return None
    fingerprint = _text_hash(contact.value)
    template = intent.template_version
    render_variables = dict(intent.variables)
    challenge_reference = render_variables.pop("challenge_reference", None)
    if intent.purpose == Purpose.PORTAL_AUTHENTICATION and challenge_reference:
        render_variables["code"] = short_single_use_code(UUID(str(challenge_reference)))
    missing = set(template.variable_names) - set(render_variables)
    if missing:
        _terminal(row, "template_variables_missing")
        return None
    subject = template.subject_template.format_map(render_variables)
    body = template.body_template.format_map(render_variables)
    suppression = _effective_suppression(
        organization_id,
        person_id=contact.canonical_person_id,
        channel=intent.channel,
        purpose=intent.purpose,
        fingerprint=fingerprint,
    )
    policy_allowed = _policy_allows(
        organization_id,
        purpose=intent.purpose,
        channel=intent.channel,
        person_id=contact.canonical_person_id,
    )
    if suppression or not policy_allowed:
        message, _ = LogicalMessage.objects.get_or_create(
            organization_id=organization_id,
            intent=intent,
            defaults={
                "template_version": intent.template_version,
                "channel": intent.channel,
                "recipient_fingerprint": fingerprint,
                "resolved_variables": intent.variables,
                "template_sha256": template.content_sha256,
                "final_sha256": _text_hash(f"{subject}\n{body}"),
                "status": LogicalMessage.Status.SUPPRESSED,
            },
        )
        row.message = message
        row.state = CommunicationOutbox.State.SUCCEEDED
        row.completed_at = timezone.now()
        row.last_error_category = (
            f"suppressed_{suppression}" if suppression else "policy_not_approved"
        )
        intent.state = CommunicationIntent.State.MATERIALIZED
        intent.save(update_fields=["state"])
        row.save(
            update_fields=[
                "message",
                "state",
                "completed_at",
                "last_error_category",
                "updated_at",
            ]
        )
        return None
    message, created = LogicalMessage.objects.get_or_create(
        organization_id=organization_id,
        intent=intent,
        defaults={
            "template_version": template,
            "channel": intent.channel,
            "recipient_fingerprint": fingerprint,
            "resolved_variables": intent.variables,
            "template_sha256": template.content_sha256,
            "final_sha256": _text_hash(f"{subject}\n{body}"),
        },
    )
    if not created and (
        message.template_version_id != template.pk
        or message.channel != intent.channel
        or message.recipient_fingerprint != fingerprint
        or message.resolved_variables != intent.variables
        or message.template_sha256 != template.content_sha256
        or message.final_sha256 != _text_hash(f"{subject}\n{body}")
    ):
        _terminal(row, "materialized_message_mismatch")
        return None
    if template.first_used_at is None:
        template.first_used_at = timezone.now()
        template.save(update_fields=["first_used_at"])
    if intent.state == CommunicationIntent.State.PENDING:
        intent.state = CommunicationIntent.State.MATERIALIZED
        intent.save(update_fields=["state"])
    row.message = message
    row.save(update_fields=["message", "updated_at"])
    provider_name = provider_for(intent.channel).name
    sender = SenderIdentity.objects.filter(
        organization_id=organization_id,
        channel=intent.channel,
        provider=provider_name,
        is_active=True,
    ).first()
    if sender is None and provider_name != "deterministic":
        _terminal(row, "sender_unavailable")
        message.status = LogicalMessage.Status.FAILED
        message.failed_at = timezone.now()
        message.save(update_fields=["status", "failed_at"])
        return None
    sender_value = (
        f"{sender.display_name} <{sender.sender_reference}>"
        if sender and sender.display_name
        else sender.sender_reference
        if sender
        else settings.DEFAULT_FROM_EMAIL
    )
    DeliveryAttempt.objects.get_or_create(
        organization_id=organization_id,
        message=message,
        attempt=row.attempt_count,
        defaults={
            "outbox": row,
            "provider": provider_name,
            "provider_idempotency_key": str(message.pk),
            "outcome": "started",
            "started_at": timezone.now(),
            "finished_at": None,
        },
    )
    return DeliveryRequest(
        channel=intent.channel,
        recipient=contact.value,
        subject=subject,
        body=body,
        sender=sender_value,
        idempotency_key=str(message.pk),
    )


def _terminal(row: CommunicationOutbox, category: str) -> None:
    row.state = CommunicationOutbox.State.DEAD
    row.last_error_category = category
    row.completed_at = timezone.now()
    row.intent.state = CommunicationIntent.State.TERMINAL
    row.intent.save(update_fields=["state"])
    row.save(update_fields=["state", "last_error_category", "completed_at", "updated_at"])


def complete_delivery(organization_id: UUID, outbox_id: UUID, result: DeliveryResult) -> None:
    now = timezone.now()
    row = (
        CommunicationOutbox.objects.select_for_update(of=("self",))
        .select_related("message", "intent")
        .get(organization_id=organization_id, pk=outbox_id)
    )
    if row.state != CommunicationOutbox.State.CLAIMED or row.message is None:
        return
    attempt, created = DeliveryAttempt.objects.get_or_create(
        organization_id=organization_id,
        message=row.message,
        attempt=row.attempt_count,
        defaults={
            "outbox": row,
            "provider": result.provider,
            "provider_idempotency_key": str(row.message_id),
            "provider_message_id": result.external_id,
            "outcome": "accepted" if result.accepted else "failed",
            "error_category": result.error_category,
            "response_code": result.response_code,
            "retry_after_seconds": result.retry_after_seconds,
            "started_at": now,
            "finished_at": now,
        },
    )
    if not created:
        attempt.provider = result.provider
        attempt.provider_idempotency_key = str(row.message_id)
        attempt.provider_message_id = result.external_id
        attempt.outcome = "accepted" if result.accepted else "failed"
        attempt.error_category = result.error_category
        attempt.response_code = result.response_code
        attempt.retry_after_seconds = result.retry_after_seconds
        attempt.finished_at = now
        attempt.save(
            update_fields=[
                "provider",
                "provider_idempotency_key",
                "provider_message_id",
                "outcome",
                "error_category",
                "response_code",
                "retry_after_seconds",
                "finished_at",
            ]
        )
    if result.accepted:
        row.state = CommunicationOutbox.State.SUCCEEDED
        row.completed_at = now
        row.message.status = LogicalMessage.Status.PROVIDER_ACCEPTED
        row.message.provider = result.provider
        row.message.provider_message_id = result.external_id
        row.message.accepted_at = now
        row.message.save(update_fields=["status", "provider", "provider_message_id", "accepted_at"])
        if (
            row.intent.purpose == Purpose.CAPTURE_ACKNOWLEDGEMENT
            and row.intent.aggregate_type == "event_request"
        ):
            from claridez.crm.public import record_communication_interaction

            record_communication_interaction(
                organization_id,
                person_id=row.intent.recipient_person_id,
                event_request_id=row.intent.aggregate_id,
                channel=row.message.channel,
                purpose=row.intent.purpose,
                occurred_at=now,
                logical_message_reference=row.message.pk,
            )
    elif result.terminal or row.attempt_count >= row.max_attempts:
        _terminal(row, result.error_category or "terminal_provider_failure")
        row.message.status = LogicalMessage.Status.FAILED
        row.message.failed_at = now
        row.message.save(update_fields=["status", "failed_at"])
        return
    else:
        delay = result.retry_after_seconds or min(3600, 30 * (2 ** (row.attempt_count - 1)))
        delay += random.SystemRandom().randint(0, min(30, delay // 4))
        row.state = CommunicationOutbox.State.RETRY
        row.next_attempt_at = now + timedelta(seconds=delay)
        row.last_error_category = result.error_category
    row.lease_expires_at = None
    row.claimed_by = ""
    row.save()


def process_one(organization_id: UUID, *, worker_id: str) -> bool:
    from claridez.organizations.tenant_scope import infrastructure_tenant_scope

    with infrastructure_tenant_scope(organization_id, purpose="communications_worker"):
        outbox_id = claim_next(organization_id, worker_id=worker_id)
    if outbox_id is None:
        return False
    with infrastructure_tenant_scope(organization_id, purpose="communications_worker"):
        request = prepare_delivery(organization_id, outbox_id)
    if request is None:
        return True
    result = provider_for(request.channel).send(request)
    with infrastructure_tenant_scope(organization_id, purpose="communications_worker"):
        complete_delivery(organization_id, outbox_id, result)
    return True


def list_deliveries(actor: User, organization_id: UUID) -> tuple[dict[str, object], ...]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_DELIVERY_READ
    ) as authorization:
        rows = CommunicationOutbox.objects.select_related("intent", "message").filter(
            organization_id=authorization.organization_id
        )
        return tuple(
            {
                "id": row.message_id or row.pk,
                "outbox_id": row.pk,
                "message_id": row.message_id,
                "purpose": row.intent.purpose,
                "channel": row.intent.channel,
                "status": row.message.status if row.message else row.state,
                "outbox_state": row.state,
                "recipient_fingerprint": (row.message.recipient_fingerprint if row.message else ""),
                "provider": row.message.provider if row.message else "",
                "attempt_count": row.attempt_count,
                "max_attempts": row.max_attempts,
                "last_error_category": row.last_error_category,
                "next_attempt_at": row.next_attempt_at,
                "created_at": row.created_at,
            }
            for row in rows.order_by("-created_at", "-id")[:200]
        )


def list_preferences(actor: User, organization_id: UUID) -> tuple[dict[str, object], ...]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_PREFERENCE_READ
    ) as authorization:
        rows = tuple(
            CommunicationPreferenceEvent.objects.filter(
                organization_id=authorization.organization_id
            ).order_by("occurred_at", "created_at", "id")
        )
        current: dict[tuple[UUID, str, str, str], dict[str, object]] = {}
        for row in rows:
            key = (
                row.person_reference,
                row.channel,
                row.purpose,
                row.destination_fingerprint,
            )
            current[key] = {
                "person_reference": row.person_reference,
                "channel": row.channel,
                "purpose": row.purpose,
                "destination_fingerprint": row.destination_fingerprint,
                "effective_suppression": _effective_suppression(
                    authorization.organization_id,
                    person_id=row.person_reference,
                    channel=row.channel,
                    purpose=row.purpose,
                    fingerprint=row.destination_fingerprint,
                ),
                "last_action": row.action,
                "occurred_at": row.occurred_at,
            }
        return tuple(
            current[key] for key in sorted(current, key=lambda value: tuple(map(str, value)))
        )


def configure_policy(
    actor: User,
    organization_id: UUID,
    *,
    purpose: str,
    channel: str,
    requires_consent: bool,
    allow_unsubscribe: bool,
    rationale: str,
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.BUSINESS_CONFIGURATION_MANAGE
    ) as authorization:
        if purpose not in Purpose.values or channel not in Channel.values:
            raise invalid("El propósito o canal no es válido.")
        if purpose == Purpose.MARKETING:
            raise invalid("Marketing permanece deshabilitado en P14 base.")
        latest = (
            CommunicationPolicy.objects.filter(
                organization_id=authorization.organization_id,
                purpose=purpose,
                channel=channel,
            )
            .order_by("-version")
            .first()
        )
        row = CommunicationPolicy.objects.create(
            organization_id=authorization.organization_id,
            purpose=purpose,
            channel=channel,
            status=CommunicationPolicy.Status.APPROVED,
            version=(latest.version + 1 if latest else 1),
            requires_consent=requires_consent or channel == Channel.WHATSAPP,
            allow_unsubscribe=allow_unsubscribe,
            rationale=rationale[:500],
            approved_by_membership_id=authorization.membership_id,
            approved_at=timezone.now(),
        )
        if latest and latest.status == CommunicationPolicy.Status.APPROVED:
            latest.status = CommunicationPolicy.Status.DISABLED
            latest.save(update_fields=["status"])
        return {
            "id": row.pk,
            "purpose": row.purpose,
            "channel": row.channel,
            "version": row.version,
            "status": row.status,
        }


def configure_sender(
    actor: User,
    organization_id: UUID,
    *,
    channel: str,
    provider: str,
    ownership: str,
    sender_reference: str,
    display_name: str,
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.BUSINESS_CONFIGURATION_MANAGE
    ) as authorization:
        if channel not in Channel.values or ownership not in SenderIdentity.Ownership.values:
            raise invalid("La identidad remitente no es válida.")
        normalized_provider = provider.strip()
        normalized_reference = sender_reference.strip()
        normalized_display_name = display_name.strip()
        if (
            not normalized_provider
            or not normalized_reference
            or not normalized_display_name
            or any(
                character in value
                for value in (normalized_reference, normalized_display_name)
                for character in ("\r", "\n")
            )
        ):
            raise invalid("La identidad remitente no es válida.")
        if channel == Channel.WHATSAPP and ownership != SenderIdentity.Ownership.ORGANIZATION:
            raise invalid("WhatsApp productivo exige identidad propia de la organización.")
        row = SenderIdentity.objects.create(
            organization_id=authorization.organization_id,
            channel=channel,
            provider=normalized_provider,
            ownership=ownership,
            sender_reference=normalized_reference,
            display_name=normalized_display_name,
        )
        return {"id": row.pk, "channel": row.channel, "provider": row.provider}


def sender_identity_for_webhook(
    organization_id: UUID, sender_identity_id: UUID
) -> tuple[str, str] | None:
    row = SenderIdentity.objects.filter(
        organization_id=organization_id, pk=sender_identity_id, is_active=True
    ).first()
    if row is None:
        return None
    return row.provider, str(row.pk)


def internal_preference_action(
    actor: User,
    organization_id: UUID,
    *,
    person_id: UUID,
    channel: str,
    purpose: str,
    suppress: bool,
    reason: str,
) -> None:
    capability = (
        Capability.COMMUNICATION_PREFERENCE_SUPPRESS
        if suppress
        else Capability.COMMUNICATION_PREFERENCE_RESTORE
    )
    with authorized_tenant_scope(actor, organization_id, capability) as authorization:
        append_preference(
            authorization.organization_id,
            person_id=person_id,
            channel=channel,
            purpose=purpose,
            action=(
                CommunicationPreferenceEvent.Action.ADMIN_SUPPRESS
                if suppress
                else CommunicationPreferenceEvent.Action.ADMIN_RELEASE
            ),
            actor_membership_id=authorization.membership_id,
            reason=reason,
        )


def manual_retry(actor: User, organization_id: UUID, *, message_id: UUID, reason: str) -> None:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise invalid("El motivo del reintento es obligatorio.")
    with authorized_tenant_scope(
        actor, organization_id, Capability.COMMUNICATION_DELIVERY_RETRY
    ) as authorization:
        try:
            row = (
                CommunicationOutbox.objects.select_for_update(of=("self",))
                .select_related("intent", "message")
                .get(organization_id=authorization.organization_id, message_id=message_id)
            )
        except CommunicationOutbox.DoesNotExist:
            raise unavailable("La entrega") from None
        if row.state not in {CommunicationOutbox.State.DEAD, CommunicationOutbox.State.RETRY}:
            raise conflict("invalid_retry", "La entrega no admite reintento.")
        if row.intent.state == CommunicationIntent.State.TERMINAL:
            row.intent.state = CommunicationIntent.State.PENDING
            row.intent.save(update_fields=["state"])
        row.state = CommunicationOutbox.State.RETRY
        row.next_attempt_at = timezone.now()
        row.completed_at = None
        row.save(update_fields=["state", "next_attempt_at", "completed_at", "updated_at"])
        CommunicationAuditEvent.objects.create(
            organization_id=authorization.organization_id,
            kind="manual_retry",
            aggregate_type="logical_message",
            aggregate_id=message_id,
            actor_membership_id=authorization.membership_id,
            detail={"reason_sha256": _text_hash(normalized_reason)},
            occurred_at=timezone.now(),
        )


def reconcile_provider_event(
    organization_id: UUID,
    *,
    provider: str,
    account: str,
    event_id: str,
    event_type: str,
    external_message_id: str,
    occurred_at: Any,
    signature_timestamp: Any,
    payload_sha256: str,
) -> ProviderEvent:
    message = LogicalMessage.objects.filter(
        organization_id=organization_id,
        provider=provider,
        provider_message_id=external_message_id,
    ).first()
    event, created = ProviderEvent.objects.get_or_create(
        organization_id=organization_id,
        provider=provider,
        provider_account=account,
        provider_event_id=event_id,
        defaults={
            "event_type": event_type,
            "external_message_id": external_message_id,
            "message": message,
            "occurred_at": occurred_at,
            "received_at": timezone.now(),
            "signature_timestamp": signature_timestamp,
            "payload_sha256": payload_sha256,
        },
    )
    if not created:
        if (
            event.event_type != event_type
            or event.external_message_id != external_message_id
            or event.occurred_at != occurred_at
            or event.signature_timestamp != signature_timestamp
            or event.payload_sha256 != payload_sha256
        ):
            raise conflict(
                "provider_event_conflict",
                "El identificador del evento ya fue usado con otro contenido.",
            )
        return event
    latest_transport_result = (
        max(
            (value for value in (message.delivered_at, message.failed_at) if value is not None),
            default=None,
        )
        if message is not None
        else None
    )
    if message is None:
        event.state = "ignored"
    elif event_type in {"delivered", "email.delivered"} and (
        latest_transport_result is None or occurred_at >= latest_transport_result
    ):
        message.status = LogicalMessage.Status.DELIVERED
        message.delivered_at = occurred_at
        message.save(update_fields=["status", "delivered_at"])
        event.state = "applied"
    elif event_type in {"bounced", "hard_bounce", "email.bounced"} and (
        latest_transport_result is None or occurred_at >= latest_transport_result
    ):
        message.status = LogicalMessage.Status.BOUNCED
        message.failed_at = occurred_at
        message.save(update_fields=["status", "failed_at"])
        append_preference(
            organization_id,
            person_id=message.intent.recipient_person_id,
            channel=message.channel,
            purpose=message.intent.purpose,
            action=CommunicationPreferenceEvent.Action.HARD_BOUNCE,
            fingerprint=message.recipient_fingerprint,
            evidence_sha256=event.payload_sha256,
            reason="provider_hard_bounce",
        )
        event.state = "applied"
    else:
        event.state = "ignored"
    event.save(update_fields=["state"])
    return event


def delivery_result_data(result: DeliveryResult) -> dict[str, object]:
    return asdict(result)
