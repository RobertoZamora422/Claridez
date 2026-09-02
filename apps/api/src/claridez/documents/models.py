# ruff: noqa: DJ008
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

    def __str__(self) -> str:
        return f"{self._meta.label_lower}:{self.pk}"


class DocumentTemplate(TenantModel):
    class Kind(models.TextChoices):
        CONTRACTUAL = "contractual", "Contractual"

    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=24, choices=Kind.choices, default=Kind.CONTRACTUAL)
    is_active = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_template_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "name"], name="documents_template_org_name_uq"
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="documents_template_revision_positive"
            ),
        ]


class DocumentTemplateVersion(TenantModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PUBLISHED = "published", "Publicada"
        INACTIVE = "inactive", "Inactiva"

    template = models.ForeignKey(
        DocumentTemplate, on_delete=models.PROTECT, related_name="versions", db_index=False
    )
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    title = models.CharField(max_length=200)
    body_html = models.TextField()
    variable_schema = models.JSONField(default=dict)
    variable_language_version = models.CharField(max_length=24, default="claridez-vars-v1")
    source_sha256 = models.CharField(max_length=64)
    assets_manifest = models.JSONField(default=dict)
    assets_sha256 = models.CharField(max_length=64)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="published_document_template_versions",
        null=True,
        blank=True,
        db_index=False,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_templateversion_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "template", "version"],
                name="documents_templateversion_org_version_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "template"],
                condition=Q(status="draft"),
                name="documents_templateversion_one_draft_uq",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="documents_templateversion_version_positive"
            ),
        ]


class TemplateEvent(TenantModel):
    class Kind(models.TextChoices):
        PUBLISHED = "published", "Publicación"
        INACTIVATED = "inactivated", "Inactivación"
        REACTIVATED = "reactivated", "Reactivación"

    template = models.ForeignKey(DocumentTemplate, on_delete=models.PROTECT, db_index=False)
    template_version = models.ForeignKey(
        DocumentTemplateVersion, on_delete=models.PROTECT, null=True, blank=True, db_index=False
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    actor_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, db_index=False
    )
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_templateevent_org_id_uq"
            )
        ]


class ContractualRecord(TenantModel):
    root_reservation_id = models.UUIDField()
    created_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="created_contractual_records",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_record_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "root_reservation_id"],
                name="documents_record_org_root_uq",
            ),
        ]


class ContractualInstrument(TenantModel):
    class Type(models.TextChoices):
        MAIN_CONTRACT = "main_contract", "Contrato principal"
        ADDENDUM = "addendum", "Adenda"
        TERMINATION = "termination", "Terminación"
        ANNEX = "annex", "Anexo"
        OTHER = "other", "Otro aprobado"

    class Status(models.TextChoices):
        OPEN = "open", "Abierto"
        CLOSED = "closed", "Cerrado"

    record = models.ForeignKey(
        ContractualRecord, on_delete=models.PROTECT, related_name="instruments", db_index=False
    )
    instrument_type = models.CharField(max_length=24, choices=Type.choices)
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    created_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="created_contractual_instruments",
    )
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_instrument_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="documents_instrument_revision_positive"
            ),
        ]


class IssuedInstrumentVersion(TenantModel):
    class State(models.TextChoices):
        PENDING_RENDER = "pending_render", "Pendiente de render"
        RENDERING = "rendering", "Renderizando"
        ISSUED = "issued", "Emitida"
        RENDER_FAILED = "render_failed", "Render fallido"

    instrument = models.ForeignKey(
        ContractualInstrument, on_delete=models.PROTECT, related_name="issued_versions"
    )
    version = models.PositiveIntegerField()
    current_reservation_id = models.UUIDField()
    quotation_version_id = models.UUIDField()
    template_version = models.ForeignKey(
        DocumentTemplateVersion, on_delete=models.PROTECT, db_index=False
    )
    snapshot = models.JSONField()
    snapshot_schema_version = models.CharField(max_length=32)
    snapshot_sha256 = models.CharField(max_length=64)
    resolved_variables = models.JSONField()
    provenance = models.JSONField()
    materiality_policy_version = models.CharField(max_length=32)
    renderer_name = models.CharField(max_length=64)
    renderer_version = models.CharField(max_length=32)
    render_environment = models.CharField(max_length=128)
    assets_sha256 = models.CharField(max_length=64)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING_RENDER)
    idempotency_key = models.UUIDField()
    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="issued_contractual_versions",
    )

    class Meta:
        ordering = ["version", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_issuedversion_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "instrument", "version"],
                name="documents_issuedversion_org_version_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="documents_issuedversion_idempotency_uq",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="documents_issuedversion_version_positive"
            ),
        ]


class GeneratedArtifact(TenantModel):
    class State(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        INTEGRITY_FAILED = "integrity_failed", "Integridad fallida"

    issued_version = models.ForeignKey(
        IssuedInstrumentVersion, on_delete=models.PROTECT, related_name="artifacts"
    )
    sequence = models.PositiveIntegerField(default=1)
    is_emitted_original = models.BooleanField(default=True)
    storage_key = models.CharField(max_length=240, unique=True)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    media_type = models.CharField(max_length=80, default="application/pdf")
    provenance = models.JSONField()
    renderer_name = models.CharField(max_length=64)
    renderer_version = models.CharField(max_length=32)
    render_environment = models.CharField(max_length=128)
    state = models.CharField(max_length=20, choices=State.choices, default=State.AVAILABLE)
    stored_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_artifact_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__gt=0), name="documents_artifact_size_positive"
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1), name="documents_artifact_sequence_positive"
            ),
            models.UniqueConstraint(
                fields=["organization", "issued_version", "sequence"],
                name="documents_artifact_org_version_sequence_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "issued_version"],
                condition=Q(is_emitted_original=True),
                name="documents_artifact_one_original_uq",
            ),
        ]


class ArtifactIntegrityEvent(TenantModel):
    class Result(models.TextChoices):
        VERIFIED = "verified", "Verificado"
        MISMATCH = "mismatch", "No coincide"
        MISSING = "missing", "Ausente"
        ERROR = "error", "Error"

    artifact = models.ForeignKey(GeneratedArtifact, on_delete=models.PROTECT, db_index=False)
    result = models.CharField(max_length=12, choices=Result.choices)
    expected_sha256 = models.CharField(max_length=64)
    observed_sha256 = models.CharField(max_length=64, blank=True)
    observed_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_integrityevent_org_id_uq"
            )
        ]


class ExternalFile(TenantModel):
    class State(models.TextChoices):
        UPLOADING = "uploading", "Subiendo"
        QUARANTINED = "quarantined", "En cuarentena"
        PENDING_SCAN = "pending_scan", "Pendiente de análisis"
        CLEAN = "clean", "Limpio"
        INFECTED = "infected", "Infectado"
        REJECTED = "rejected", "Rechazado"
        SCAN_ERROR = "scan_error", "Error de análisis"
        INTEGRITY_FAILED = "integrity_failed", "Integridad fallida"

    record = models.ForeignKey(
        ContractualRecord, on_delete=models.PROTECT, related_name="external_files"
    )
    display_name = models.CharField(max_length=240)
    storage_key = models.CharField(max_length=240, unique=True)
    declared_media_type = models.CharField(max_length=80)
    detected_media_type = models.CharField(max_length=80, blank=True)
    extension = models.CharField(max_length=12)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    state = models.CharField(max_length=20, choices=State.choices)
    validation_detail = models.CharField(max_length=500, blank=True)
    uploaded_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="uploaded_document_files",
    )
    available_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_externalfile_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__gt=0), name="documents_externalfile_size_positive"
            ),
        ]


class ExternalFileEvent(TenantModel):
    external_file = models.ForeignKey(ExternalFile, on_delete=models.PROTECT, db_index=False)
    from_state = models.CharField(max_length=20, blank=True)
    to_state = models.CharField(max_length=20, choices=ExternalFile.State.choices)
    reason = models.CharField(max_length=80)
    detail = models.CharField(max_length=500, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_externalfileevent_org_id_uq"
            )
        ]


class MalwareScanAttempt(TenantModel):
    class Result(models.TextChoices):
        CLEAN = "clean", "Limpio"
        INFECTED = "infected", "Infectado"
        UNSUPPORTED = "unsupported", "No soportado"
        TIMEOUT = "timeout", "Timeout"
        TECHNICAL_ERROR = "technical_error", "Error técnico"
        INCOMPLETE = "incomplete", "Incompleto"

    external_file = models.ForeignKey(
        ExternalFile, on_delete=models.PROTECT, related_name="scan_attempts", db_index=False
    )
    attempt = models.PositiveIntegerField()
    scanner_name = models.CharField(max_length=64)
    scanner_version = models.CharField(max_length=80, blank=True)
    signatures_version = models.CharField(max_length=120, blank=True)
    result = models.CharField(max_length=20, choices=Result.choices)
    malware_name = models.CharField(max_length=200, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()

    class Meta:
        ordering = ["attempt", "started_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_scanattempt_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "external_file", "attempt"],
                name="documents_scanattempt_file_attempt_uq",
            ),
            models.CheckConstraint(
                condition=Q(attempt__gte=1), name="documents_scanattempt_attempt_positive"
            ),
        ]


class ExternalAccessGrant(TenantModel):
    class Purpose(models.TextChoices):
        READ = "read", "Lectura"
        DOWNLOAD = "download", "Descarga"
        ACCEPT = "accept", "Aceptación"

    issued_version = models.ForeignKey(IssuedInstrumentVersion, on_delete=models.PROTECT)
    artifact = models.ForeignKey(GeneratedArtifact, on_delete=models.PROTECT)
    purpose = models.CharField(max_length=12, choices=Purpose.choices)
    token_hmac = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_index=False,
    )
    max_exchanges = models.PositiveSmallIntegerField(default=1)
    exchange_count = models.PositiveSmallIntegerField(default=0)
    created_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="created_document_grants",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_grant_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(max_exchanges__gte=1), name="documents_grant_max_exchanges_positive"
            ),
            models.CheckConstraint(
                condition=Q(exchange_count__lte=models.F("max_exchanges")),
                name="documents_grant_exchange_count_valid",
            ),
        ]


class ExternalDocumentSession(TenantModel):
    grant = models.ForeignKey(ExternalAccessGrant, on_delete=models.PROTECT)
    token_hmac = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_externalsession_org_id_uq"
            )
        ]


class AcceptanceChallenge(TenantModel):
    grant = models.ForeignKey(ExternalAccessGrant, on_delete=models.PROTECT)
    issued_version = models.ForeignKey(IssuedInstrumentVersion, on_delete=models.PROTECT)
    artifact = models.ForeignKey(GeneratedArtifact, on_delete=models.PROTECT)
    token_hmac = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_challenge_org_id_uq"
            )
        ]


class AcceptanceEvidence(TenantModel):
    class Provenance(models.TextChoices):
        DOCUMENT_LINK = "document_link", "Acceso documental P9"
        PORTAL_SESSION = "portal_session", "Sesión Portal P14"

    challenge = models.OneToOneField(
        AcceptanceChallenge, on_delete=models.PROTECT, null=True, blank=True
    )
    provenance = models.CharField(
        max_length=20, choices=Provenance.choices, default=Provenance.DOCUMENT_LINK
    )
    portal_principal_reference = models.UUIDField(null=True, blank=True)
    portal_grant_reference = models.UUIDField(null=True, blank=True)
    portal_idempotency_key = models.UUIDField(null=True, blank=True)
    issued_version = models.ForeignKey(IssuedInstrumentVersion, on_delete=models.PROTECT)
    artifact = models.ForeignKey(GeneratedArtifact, on_delete=models.PROTECT)
    artifact_sha256 = models.CharField(max_length=64)
    manifestation_text = models.TextField()
    manifestation_version = models.CharField(max_length=32)
    acceptor_projection = models.JSONField()
    attribution_method = models.CharField(max_length=64)
    authentication_result = models.JSONField()
    mechanism_version = models.CharField(max_length=32)
    accepted_at = models.DateTimeField()
    timezone_name = models.CharField(max_length=64)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    # NULL records that privacy policy deliberately did not capture this optional evidence.
    user_agent = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001
    request_id = models.CharField(max_length=128)
    correlation_id = models.CharField(max_length=128)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_acceptance_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "portal_idempotency_key"],
                condition=Q(portal_idempotency_key__isnull=False),
                name="documents_acceptance_portal_idempotency_uq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        provenance="document_link",
                        challenge__isnull=False,
                        portal_principal_reference__isnull=True,
                        portal_grant_reference__isnull=True,
                        portal_idempotency_key__isnull=True,
                    )
                    | Q(
                        provenance="portal_session",
                        challenge__isnull=True,
                        portal_principal_reference__isnull=False,
                        portal_grant_reference__isnull=False,
                        portal_idempotency_key__isnull=False,
                    )
                ),
                name="documents_acceptance_provenance_valid",
            ),
        ]


class ExternalAccessEvent(TenantModel):
    grant = models.ForeignKey(ExternalAccessGrant, on_delete=models.PROTECT, null=True, blank=True)
    challenge = models.ForeignKey(
        AcceptanceChallenge, on_delete=models.PROTECT, null=True, blank=True
    )
    kind = models.CharField(max_length=32)
    result = models.CharField(max_length=24)
    ip_hash = models.CharField(max_length=64, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    detail = models.CharField(max_length=300, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_accessevent_org_id_uq"
            )
        ]


class ExternalRateLimitBucket(models.Model):
    key_hash = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    request_count = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["key_hash", "window_start"], name="documents_ratelimit_key_window_uq"
            )
        ]

    def __str__(self) -> str:
        return f"rate-limit:{self.window_start.isoformat()}"


class ExternalTokenLocator(models.Model):
    class Kind(models.TextChoices):
        GRANT = "grant", "Grant"
        SESSION = "session", "Sesión"
        CHALLENGE = "challenge", "Challenge"

    kind = models.CharField(max_length=12, choices=Kind.choices)
    token_hmac = models.CharField(max_length=64, unique=True)
    organization_id = models.UUIDField()
    target_id = models.UUIDField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "target_id"], name="documents_tokenlocator_kind_target_uq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.target_id}"


class RetentionPolicy(TenantModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        ACTIVE = "active", "Activa"
        RETIRED = "retired", "Retirada"

    key = models.CharField(max_length=80)
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=160)
    classification = models.CharField(max_length=80)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    rules = models.JSONField(default=dict)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_index=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_retentionpolicy_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "key", "version"],
                name="documents_retentionpolicy_key_version_uq",
            ),
        ]


class RetentionAssignment(TenantModel):
    class State(models.TextChoices):
        RETAIN = "retain", "Conservar"
        HELD = "held", "Legal hold"
        ELIGIBLE = "eligible", "Elegible para disposición"

    policy = models.ForeignKey(RetentionPolicy, on_delete=models.PROTECT)
    target_type = models.CharField(max_length=32)
    target_id = models.UUIDField()
    state = models.CharField(max_length=12, choices=State.choices, default=State.RETAIN)
    eligible_at = models.DateTimeField(null=True, blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_retentionassignment_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "target_type", "target_id"],
                name="documents_retentionassignment_target_uq",
            ),
        ]


class LegalHold(TenantModel):
    assignment = models.ForeignKey(RetentionAssignment, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    placed_at = models.DateTimeField()
    placed_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="placed_document_holds",
    )
    released_at = models.DateTimeField(null=True, blank=True)
    released_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="released_document_holds",
        null=True,
        blank=True,
    )
    release_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_legalhold_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "assignment"],
                condition=Q(released_at__isnull=True),
                name="documents_legalhold_one_active_uq",
            ),
        ]


class RetentionEvent(TenantModel):
    assignment = models.ForeignKey(RetentionAssignment, on_delete=models.PROTECT)
    kind = models.CharField(max_length=32)
    actor_membership = models.ForeignKey("organizations.Membership", on_delete=models.PROTECT)
    evidence = models.JSONField(default=dict)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_retentionevent_org_id_uq"
            )
        ]


class DocumentJob(TenantModel):
    class Type(models.TextChoices):
        FINALIZE_EXTERNAL_UPLOAD = "finalize_external_upload", "Finalización de upload"
        FINALIZE_DOMAIN_UPLOAD = "finalize_domain_upload", "Finalización de upload de dominio"
        RENDER_ISSUED_VERSION = "render_issued_version", "Render de emisión"
        RENDER_DOMAIN_ARTIFACT = "render_domain_artifact", "Render de artefacto de dominio"
        SCAN_EXTERNAL_FILE = "scan_external_file", "Análisis de archivo"
        SCAN_DOMAIN_FILE = "scan_domain_file", "Análisis de archivo de dominio"
        VERIFY_ARTIFACT = "verify_artifact", "Verificación de integridad"
        VERIFY_DOMAIN_ARTIFACT = (
            "verify_domain_artifact",
            "Verificación de artefacto de dominio",
        )

    class State(models.TextChoices):
        QUEUED = "queued", "En cola"
        RUNNING = "running", "En ejecución"
        RETRY_WAIT = "retry_wait", "Esperando reintento"
        SUCCEEDED = "succeeded", "Completado"
        DEAD = "dead", "Fallo terminal"

    job_type = models.CharField(max_length=32, choices=Type.choices)
    target_id = models.UUIDField()
    payload = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128)
    correlation_id = models.CharField(max_length=128)
    state = models.CharField(max_length=16, choices=State.choices, default=State.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    next_attempt_at = models.DateTimeField()
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.CharField(max_length=128, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    last_error_detail = models.CharField(max_length=500, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="documents_job_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "job_type", "idempotency_key"],
                name="documents_job_idempotency_uq",
            ),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1), name="documents_job_max_attempts_positive"
            ),
            models.CheckConstraint(
                condition=Q(attempts__lte=models.F("max_attempts")),
                name="documents_job_attempts_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "state", "next_attempt_at"],
                name="documents_job_claim_idx",
            )
        ]


class DocumentJobAttempt(TenantModel):
    job = models.ForeignKey(DocumentJob, on_delete=models.PROTECT, related_name="history")
    attempt = models.PositiveSmallIntegerField()
    worker_id = models.CharField(max_length=128)
    outcome = models.CharField(max_length=24)
    error_code = models.CharField(max_length=80, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()

    class Meta:
        ordering = ["attempt", "started_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_jobattempt_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "job", "attempt"],
                name="documents_jobattempt_job_attempt_uq",
            ),
        ]


class PrivateDomainFile(TenantModel):
    """Binario privado genérico; su semántica permanece en el dominio llamador."""

    class State(models.TextChoices):
        UPLOADING = "uploading", "Subiendo"
        QUARANTINED = "quarantined", "En cuarentena"
        PENDING_SCAN = "pending_scan", "Pendiente de análisis"
        CLEAN = "clean", "Limpio"
        INFECTED = "infected", "Infectado"
        REJECTED = "rejected", "Rechazado"
        SCAN_ERROR = "scan_error", "Error de análisis"
        INTEGRITY_FAILED = "integrity_failed", "Integridad fallida"

    owner_domain = models.CharField(max_length=32)
    owner_id = models.UUIDField()
    purpose = models.CharField(max_length=40)
    display_name = models.CharField(max_length=240)
    storage_key = models.CharField(max_length=240, unique=True)
    declared_media_type = models.CharField(max_length=80)
    detected_media_type = models.CharField(max_length=80, blank=True)
    extension = models.CharField(max_length=12)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    state = models.CharField(max_length=20, choices=State.choices)
    validation_detail = models.CharField(max_length=500, blank=True)
    uploaded_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="uploaded_private_domain_files",
        db_index=False,
    )
    available_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_domainfile_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__gt=0), name="documents_domainfile_size_positive"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "owner_domain", "owner_id", "purpose"],
                name="documents_domainfile_owner_idx",
            )
        ]


class PrivateDomainFileEvent(TenantModel):
    domain_file = models.ForeignKey(
        PrivateDomainFile, on_delete=models.PROTECT, related_name="events", db_index=False
    )
    from_state = models.CharField(max_length=20, blank=True)
    to_state = models.CharField(max_length=20, choices=PrivateDomainFile.State.choices)
    reason = models.CharField(max_length=80)
    detail = models.CharField(max_length=500, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_domainfile_event_org_id_uq"
            )
        ]


class PrivateDomainScanAttempt(TenantModel):
    domain_file = models.ForeignKey(
        PrivateDomainFile,
        on_delete=models.PROTECT,
        related_name="scan_attempts",
        db_index=False,
    )
    attempt = models.PositiveIntegerField()
    scanner_name = models.CharField(max_length=64)
    scanner_version = models.CharField(max_length=80, blank=True)
    signatures_version = models.CharField(max_length=120, blank=True)
    result = models.CharField(max_length=20, choices=MalwareScanAttempt.Result.choices)
    malware_name = models.CharField(max_length=200, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_domainscan_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "domain_file", "attempt"],
                name="documents_domainscan_attempt_uq",
            ),
        ]


class GeneratedDomainArtifact(TenantModel):
    class State(models.TextChoices):
        PENDING_RENDER = "pending_render", "Pendiente de render"
        AVAILABLE = "available", "Disponible"
        RENDER_FAILED = "render_failed", "Render fallido"
        INTEGRITY_FAILED = "integrity_failed", "Integridad fallida"

    owner_domain = models.CharField(max_length=32)
    owner_id = models.UUIDField()
    purpose = models.CharField(max_length=40)
    source_snapshot_sha256 = models.CharField(max_length=64)
    render_payload = models.JSONField()
    storage_key = models.CharField(max_length=240, unique=True, null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    media_type = models.CharField(max_length=80, default="application/pdf")
    renderer_name = models.CharField(max_length=64, blank=True)
    renderer_version = models.CharField(max_length=32, blank=True)
    render_environment = models.CharField(max_length=128, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING_RENDER)
    stored_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="documents_domainartifact_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "owner_domain", "owner_id", "purpose"],
                name="documents_domainartifact_owner_purpose_uq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "owner_domain", "owner_id"],
                name="docs_domainartifact_owner_idx",
            )
        ]
