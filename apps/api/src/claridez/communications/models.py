from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, db_index=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Channel(models.TextChoices):
    EMAIL = "email", "Correo"
    WHATSAPP = "whatsapp", "WhatsApp"


class Purpose(models.TextChoices):
    PORTAL_AUTHENTICATION = "portal_authentication", "Autenticación Portal"
    CAPTURE_ACKNOWLEDGEMENT = "capture_acknowledgement", "Acuse de captación"
    SERVICE_UPDATE = "service_update", "Actualización de servicio"
    EVENT_REMINDER = "event_reminder", "Recordatorio de evento"
    PAYMENT_REMINDER = "payment_reminder", "Recordatorio de cobro"
    DOCUMENT_REMINDER = "document_reminder", "Recordatorio documental"
    CLIENT_ACTION = "client_action", "Acción del cliente"
    MARKETING = "marketing", "Marketing"


class CommunicationTemplate(TenantModel):  # noqa: DJ008
    name = models.CharField(max_length=120)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    is_active = models.BooleanField(default=True)
    created_by_membership_id = models.UUIDField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="communications_template_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "name", "channel", "purpose"],
                name="communications_template_logical_uq",
            ),
        ]


class CommunicationTemplateVersion(TenantModel):  # noqa: DJ008
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PUBLISHED = "published", "Publicada"
        RETIRED = "retired", "Retirada"

    template = models.ForeignKey(
        CommunicationTemplate, on_delete=models.PROTECT, related_name="versions"
    )
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    subject_template = models.CharField(max_length=240, blank=True)
    body_template = models.TextField()
    variable_names = models.JSONField(default=list)
    content_sha256 = models.CharField(max_length=64)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by_membership_id = models.UUIDField(null=True, blank=True)
    first_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="communications_templateversion_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "template", "version"],
                name="communications_templateversion_number_uq",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="communications_templateversion_positive"
            ),
        ]


class CommunicationPolicy(TenantModel):  # noqa: DJ008
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        APPROVED = "approved", "Aprobada"
        DISABLED = "disabled", "Deshabilitada"

    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1)
    requires_consent = models.BooleanField(default=False)
    allow_unsubscribe = models.BooleanField(default=False)
    rationale = models.CharField(max_length=500, blank=True)
    approved_by_membership_id = models.UUIDField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "purpose", "channel", "version"],
                name="communications_policy_version_uq",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="communications_policy_version_positive"
            ),
        ]


class SenderIdentity(TenantModel):  # noqa: DJ008
    class Ownership(models.TextChoices):
        CLARIDEZ = "claridez", "Claridez"
        ORGANIZATION = "organization", "Organización"

    channel = models.CharField(max_length=16, choices=Channel.choices)
    provider = models.CharField(max_length=32)
    ownership = models.CharField(max_length=16, choices=Ownership.choices)
    sender_reference = models.CharField(max_length=240)
    display_name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "channel", "provider", "sender_reference"],
                name="communications_sender_identity_uq",
            )
        ]


class CommunicationPreferenceEvent(TenantModel):  # noqa: DJ008
    class Action(models.TextChoices):
        CLIENT_ALLOW = "client_allow", "Permiso explícito del cliente"
        CLIENT_UNSUBSCRIBE = "client_unsubscribe", "Baja del cliente"
        ADMIN_SUPPRESS = "admin_suppress", "Supresión administrativa"
        ADMIN_RELEASE = "admin_release", "Liberación administrativa"
        HARD_BOUNCE = "hard_bounce", "Rebote permanente"
        TECHNICAL_RELEASE = "technical_release", "Liberación técnica probada"

    person_reference = models.UUIDField()
    canonical_set = models.JSONField(default=list)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    destination_fingerprint = models.CharField(max_length=64, blank=True)
    action = models.CharField(max_length=24, choices=Action.choices)
    actor_membership_id = models.UUIDField(null=True, blank=True)
    portal_principal_reference = models.UUIDField(null=True, blank=True)
    evidence_sha256 = models.CharField(max_length=64, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="communications_preferenceevent_org_id_uq"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        action__in=["client_allow", "client_unsubscribe"],
                        portal_principal_reference__isnull=False,
                        actor_membership_id__isnull=True,
                        evidence_sha256__regex=r"^[0-9a-f]{64}$",
                    )
                    | Q(
                        action__in=["admin_suppress", "admin_release"],
                        portal_principal_reference__isnull=True,
                        actor_membership_id__isnull=False,
                    )
                    | Q(
                        action="hard_bounce",
                        portal_principal_reference__isnull=True,
                        actor_membership_id__isnull=True,
                        destination_fingerprint__regex=r"^[0-9a-f]{64}$",
                        evidence_sha256__regex=r"^[0-9a-f]{64}$",
                    )
                    | Q(
                        action="technical_release",
                        portal_principal_reference__isnull=True,
                        actor_membership_id__isnull=False,
                        destination_fingerprint__regex=r"^[0-9a-f]{64}$",
                        evidence_sha256__regex=r"^[0-9a-f]{64}$",
                    )
                ),
                name="communications_preference_actor_valid",
            ),
        ]


class CommunicationIntent(TenantModel):  # noqa: DJ008
    class State(models.TextChoices):
        PENDING = "pending", "Pendiente"
        MATERIALIZED = "materialized", "Materializada"
        CANCELLED = "cancelled", "Cancelada"
        SUPERSEDED = "superseded", "Obsoleta"
        TERMINAL = "terminal", "Terminal"

    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    recipient_person_id = models.UUIDField()
    template_version = models.ForeignKey(
        CommunicationTemplateVersion, on_delete=models.PROTECT, related_name="intents"
    )
    aggregate_type = models.CharField(max_length=48)
    aggregate_id = models.UUIDField()
    variables = models.JSONField(default=dict)
    payload_sha256 = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=160)
    source_version = models.PositiveIntegerField(default=1)
    causal_key = models.CharField(max_length=160, blank=True)
    causal_sequence = models.PositiveBigIntegerField(null=True, blank=True)
    not_before = models.DateTimeField()
    requested_by_membership_id = models.UUIDField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="communications_intent_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="communications_intent_idempotency_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "causal_key", "causal_sequence"],
                condition=~Q(causal_key="") & Q(causal_sequence__isnull=False),
                name="communications_intent_causal_sequence_uq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(causal_key="", causal_sequence__isnull=True)
                    | (~Q(causal_key="") & Q(causal_sequence__isnull=False))
                ),
                name="communications_intent_causal_pair_valid",
            ),
        ]


class LogicalMessage(TenantModel):  # noqa: DJ008
    class Status(models.TextChoices):
        QUEUED = "queued", "En cola"
        PROVIDER_ACCEPTED = "provider_accepted", "Aceptada por proveedor"
        DELIVERED = "delivered", "Entregada"
        BOUNCED = "bounced", "Rebotada"
        FAILED = "failed", "Fallida"
        SUPPRESSED = "suppressed", "Suprimida"
        CANCELLED = "cancelled", "Cancelada"

    intent = models.OneToOneField(
        CommunicationIntent, on_delete=models.PROTECT, related_name="message"
    )
    template_version = models.ForeignKey(
        CommunicationTemplateVersion, on_delete=models.PROTECT, related_name="messages"
    )
    channel = models.CharField(max_length=16, choices=Channel.choices)
    recipient_fingerprint = models.CharField(max_length=64)
    resolved_variables = models.JSONField(default=dict)
    template_sha256 = models.CharField(max_length=64)
    final_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    provider = models.CharField(max_length=32, blank=True)
    provider_message_id = models.CharField(max_length=240, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="communications_message_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "provider", "provider_message_id"],
                condition=~Q(provider_message_id=""),
                name="communications_message_provider_id_uq",
            ),
        ]


class CommunicationOutbox(TenantModel):  # noqa: DJ008
    class State(models.TextChoices):
        PENDING = "pending", "Pendiente"
        CLAIMED = "claimed", "Reclamada"
        RETRY = "retry", "Reintento"
        SUCCEEDED = "succeeded", "Completada"
        DEAD = "dead", "Fallo terminal"
        CANCELLED = "cancelled", "Cancelada"

    intent = models.OneToOneField(
        CommunicationIntent, on_delete=models.PROTECT, related_name="outbox_entry"
    )
    message = models.OneToOneField(
        LogicalMessage,
        on_delete=models.PROTECT,
        related_name="outbox_entry",
        null=True,
        blank=True,
    )
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING)
    next_attempt_at = models.DateTimeField()
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.CharField(max_length=120, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=8)
    last_error_category = models.CharField(max_length=48, blank=True)
    last_error_detail = models.CharField(max_length=500, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["organization", "state", "next_attempt_at", "created_at", "id"],
                name="comm_outbox_claim_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="communications_outbox_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1), name="communications_outbox_attempts_positive"
            ),
        ]


class DeliveryAttempt(TenantModel):  # noqa: DJ008
    message = models.ForeignKey(LogicalMessage, on_delete=models.PROTECT, related_name="attempts")
    outbox = models.ForeignKey(
        CommunicationOutbox, on_delete=models.PROTECT, related_name="attempts"
    )
    attempt = models.PositiveSmallIntegerField()
    provider = models.CharField(max_length=32)
    provider_idempotency_key = models.CharField(max_length=200)
    provider_message_id = models.CharField(max_length=240, blank=True)
    outcome = models.CharField(max_length=24)
    error_category = models.CharField(max_length=48, blank=True)
    response_code = models.CharField(max_length=32, blank=True)
    retry_after_seconds = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "message", "attempt"],
                name="communications_attempt_number_uq",
            )
        ]


class ProviderEvent(TenantModel):  # noqa: DJ008
    provider = models.CharField(max_length=32)
    provider_account = models.CharField(max_length=120)
    provider_event_id = models.CharField(max_length=240)
    event_type = models.CharField(max_length=80)
    external_message_id = models.CharField(max_length=240, blank=True)
    message = models.ForeignKey(
        LogicalMessage, on_delete=models.PROTECT, null=True, blank=True, related_name="events"
    )
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField()
    signature_timestamp = models.DateTimeField()
    payload_sha256 = models.CharField(max_length=64)
    state = models.CharField(max_length=16, default="recorded")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider", "provider_account", "provider_event_id"],
                name="communications_provider_event_uq",
            )
        ]


class CommunicationAuditEvent(TenantModel):  # noqa: DJ008
    kind = models.CharField(max_length=48)
    aggregate_type = models.CharField(max_length=48)
    aggregate_id = models.UUIDField()
    actor_membership_id = models.UUIDField(null=True, blank=True)
    detail = models.JSONField(default=dict)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "created_at", "id"]
