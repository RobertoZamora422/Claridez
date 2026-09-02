from __future__ import annotations

import uuid

from django.db import models
from django.db.models import F, Q


class PortalLocator(models.Model):  # noqa: DJ008
    """Índice técnico global; no contiene datos funcionales del formulario o cliente."""

    class Kind(models.TextChoices):
        PUBLIC_FORM = "public_form", "Formulario publicado"
        CHALLENGE = "challenge", "Challenge"
        RECOVERY = "recovery", "Recuperación"
        SESSION = "session", "Sesión Portal"
        COMMUNICATIONS_WEBHOOK = "communications_webhook", "Webhook de comunicaciones"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hmac = models.CharField(max_length=64, unique=True)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    target_reference = models.UUIDField()
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["token_hmac", "kind"], name="portal_locator_lookup_idx")]


class PortalRateLimitBucket(models.Model):  # noqa: DJ008
    key_hmac = models.CharField(max_length=64)
    action = models.CharField(max_length=32)
    window_started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)
    blocked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["key_hmac", "action", "window_started_at"],
                name="portal_rate_bucket_uq",
            )
        ]


class AntiAbuseTokenUse(models.Model):  # noqa: DJ008
    token_hmac = models.CharField(max_length=64, unique=True)
    action = models.CharField(max_length=32)
    hostname = models.CharField(max_length=240)
    used_at = models.DateTimeField(auto_now_add=True)


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, db_index=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class PublicForm(TenantModel):  # noqa: DJ008
    class Status(models.TextChoices):
        ACTIVE = "active", "Activa"
        RETIRED = "retired", "Retirada"

    name = models.CharField(max_length=120)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    created_by_membership_id = models.UUIDField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="portal_publicform_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "name"], name="portal_publicform_name_uq"
            ),
        ]


class PublicFormVersion(TenantModel):  # noqa: DJ008
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PUBLISHED = "published", "Publicada"
        RETIRED = "retired", "Retirada"

    form = models.ForeignKey(PublicForm, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    title = models.CharField(max_length=160)
    introduction = models.CharField(max_length=500, blank=True)
    field_schema = models.JSONField(default=dict)
    event_type_options = models.JSONField(default=list)
    location_options = models.JSONField(default=list)
    duration_options_minutes = models.JSONField(default=list)
    timezone_name = models.CharField(max_length=64)
    responsible_membership_id = models.UUIDField()
    origin = models.CharField(max_length=24)
    origin_detail = models.CharField(max_length=160, blank=True)
    attribution = models.JSONField(default=dict)
    consent_presentation = models.JSONField(default=list)
    portal_scopes = models.JSONField(default=list)
    acknowledgement_template_version_id = models.UUIDField(null=True, blank=True)
    configuration_sha256 = models.CharField(max_length=64)
    created_by_membership_id = models.UUIDField()
    published_by_membership_id = models.UUIDField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="portal_formversion_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "form", "version"], name="portal_formversion_number_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "form"],
                condition=Q(status="published"),
                name="portal_formversion_one_published_uq",
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="portal_formversion_positive"),
        ]


class PublicFormSubmission(TenantModel):  # noqa: DJ008
    class State(models.TextChoices):
        PROCESSING = "processing", "Procesando"
        COMPLETED = "completed", "Completada"
        REJECTED = "rejected", "Rechazada"

    form_version = models.ForeignKey(
        PublicFormVersion, on_delete=models.PROTECT, related_name="submissions"
    )
    idempotency_key_hmac = models.CharField(max_length=64)
    payload_sha256 = models.CharField(max_length=64)
    evidence_sha256 = models.CharField(max_length=64)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PROCESSING)
    person_reference = models.UUIDField(null=True, blank=True)
    event_request_reference = models.UUIDField(null=True, blank=True)
    consent_event_references = models.JSONField(default=list)
    availability_observed = models.BooleanField(null=True, blank=True)
    attribution_sha256 = models.CharField(max_length=64)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="portal_submission_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "form_version", "idempotency_key_hmac"],
                name="portal_submission_idempotency_uq",
            ),
        ]


class PortalPrincipal(TenantModel):  # noqa: DJ008
    class State(models.TextChoices):
        ACTIVE = "active", "Activo"
        COLLISION = "collision", "Colisión pendiente"
        DISABLED = "disabled", "Deshabilitado"

    person_reference = models.UUIDField()
    canonical_set = models.JSONField(default=list)
    state = models.CharField(max_length=12, choices=State.choices, default=State.ACTIVE)
    revision = models.PositiveIntegerField(default=1)
    reconciled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="portal_principal_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "person_reference"],
                condition=Q(state="active"),
                name="portal_principal_active_person_uq",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="portal_principal_revision_positive"
            ),
        ]


class PortalChallenge(TenantModel):  # noqa: DJ008
    class Kind(models.TextChoices):
        AUTHENTICATION = "authentication", "Autenticación"
        ENROLLMENT = "enrollment", "Enrolamiento"
        RECOVERY = "recovery", "Recuperación"

    principal = models.ForeignKey(
        PortalPrincipal, on_delete=models.PROTECT, related_name="challenges"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    channel = models.CharField(max_length=16)
    contact_fingerprint = models.CharField(max_length=64)
    contact_revision = models.PositiveIntegerField()
    code_hmac = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="portal_challenge_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__lte=F("max_attempts")),
                name="portal_challenge_attempt_limit",
            ),
            models.CheckConstraint(
                condition=~Q(consumed_at__isnull=False, revoked_at__isnull=False),
                name="portal_challenge_one_terminal_state",
            ),
        ]


class PortalSession(TenantModel):  # noqa: DJ008
    principal = models.ForeignKey(
        PortalPrincipal, on_delete=models.PROTECT, related_name="sessions"
    )
    token_hmac = models.CharField(max_length=64, unique=True)
    contact_fingerprint = models.CharField(max_length=64)
    contact_revision = models.PositiveIntegerField()
    idle_expires_at = models.DateTimeField()
    absolute_expires_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    rotation = models.PositiveIntegerField(default=1)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="portal_session_org_id_uq"),
            models.CheckConstraint(
                condition=Q(rotation__gte=1), name="portal_session_rotation_positive"
            ),
            models.CheckConstraint(
                condition=Q(last_seen_at__lte=F("idle_expires_at"))
                & Q(idle_expires_at__lte=F("absolute_expires_at")),
                name="portal_session_expiry_order",
            ),
        ]


class PortalGrant(TenantModel):  # noqa: DJ008
    class State(models.TextChoices):
        ACTIVE = "active", "Activo"
        REVOKED = "revoked", "Revocado"

    principal = models.ForeignKey(PortalPrincipal, on_delete=models.PROTECT, related_name="grants")
    person_reference = models.UUIDField()
    event_request_reference = models.UUIDField()
    root_reservation_reference = models.UUIDField(null=True, blank=True)
    scopes = models.JSONField(default=list)
    state = models.CharField(max_length=12, choices=State.choices, default=State.ACTIVE)
    revision = models.PositiveIntegerField(default=1)
    issued_by_membership_id = models.UUIDField(null=True, blank=True)
    provenance = models.CharField(max_length=32)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by_membership_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="portal_grant_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "principal", "event_request_reference"],
                condition=Q(state="active"),
                name="portal_grant_active_request_uq",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="portal_grant_revision_positive"
            ),
            models.CheckConstraint(
                condition=(
                    Q(provenance="public_capture", issued_by_membership_id__isnull=True)
                    | Q(provenance="internal_issue", issued_by_membership_id__isnull=False)
                ),
                name="portal_grant_provenance_actor_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        state="active",
                        revoked_at__isnull=True,
                        revoked_by_membership_id__isnull=True,
                    )
                    | Q(
                        state="revoked",
                        revoked_at__isnull=False,
                        revoked_by_membership_id__isnull=False,
                    )
                ),
                name="portal_grant_state_evidence_valid",
            ),
        ]


class PortalAuditEvent(TenantModel):  # noqa: DJ008
    kind = models.CharField(max_length=48)
    principal_reference = models.UUIDField(null=True, blank=True)
    grant_reference = models.UUIDField(null=True, blank=True)
    actor_membership_id = models.UUIDField(null=True, blank=True)
    result = models.CharField(max_length=24)
    detail = models.JSONField(default=dict)
    request_fingerprint = models.CharField(max_length=64, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "created_at", "id"]
