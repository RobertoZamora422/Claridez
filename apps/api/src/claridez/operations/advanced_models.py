# ruff: noqa: DJ008

from __future__ import annotations

import uuid

from django.contrib.postgres.fields import DateTimeRangeField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Trim


class OperationsTenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, db_index=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class OperationalTemplate(OperationsTenantModel):
    event_type = models.ForeignKey(
        "catalog.EventType", on_delete=models.PROTECT, related_name="operational_templates"
    )
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=1)
    created_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="created_operational_templates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_template_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "event_type"], name="operations_template_event_type_uq"
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="operations_template_revision_positive"
            ),
        ]


class OperationalTemplateVersion(OperationsTenantModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PUBLISHED = "published", "Publicada"
        RETIRED = "retired", "Retirada"

    template = models.ForeignKey(
        OperationalTemplate, on_delete=models.PROTECT, related_name="versions"
    )
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    content_sha256 = models.CharField(max_length=64, blank=True)
    created_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="created_operational_template_versions",
    )
    published_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="published_operational_template_versions",
        null=True,
        blank=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_template_version_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "template", "version"],
                name="operations_template_version_number_uq",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="operations_template_version_positive"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="draft",
                        published_at__isnull=True,
                        published_by_membership__isnull=True,
                        retired_at__isnull=True,
                    )
                    | Q(
                        status="published",
                        published_at__isnull=False,
                        published_by_membership__isnull=False,
                        retired_at__isnull=True,
                    )
                    | Q(
                        status="retired",
                        published_at__isnull=False,
                        published_by_membership__isnull=False,
                        retired_at__isnull=False,
                    )
                ),
                name="operations_template_version_state_valid",
            ),
        ]


class TemplateReadinessDefinition(OperationsTenantModel):
    version = models.ForeignKey(
        OperationalTemplateVersion, on_delete=models.PROTECT, related_name="readiness_definitions"
    )
    key = models.CharField(max_length=64)
    title = models.CharField(max_length=160)
    section = models.CharField(max_length=16)
    is_required = models.BooleanField(default=True)
    days_before = models.PositiveIntegerField(default=0)
    role_key = models.CharField(max_length=64, blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_readiness_definition_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "version", "key"],
                name="operations_readiness_definition_key_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "version", "position"],
                name="operations_readiness_definition_position_uq",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1), name="operations_readiness_definition_position_ck"
            ),
        ]


class TemplatePhaseDefinition(OperationsTenantModel):
    class Phase(models.TextChoices):
        SETUP = "setup", "Montaje"
        EXECUTION = "execution", "Ejecución"
        TEARDOWN = "teardown", "Desmontaje"
        POST_EVENT = "post_event", "Postevento"

    version = models.ForeignKey(
        OperationalTemplateVersion, on_delete=models.PROTECT, related_name="phase_definitions"
    )
    key = models.CharField(max_length=64)
    phase = models.CharField(max_length=16, choices=Phase.choices)
    title = models.CharField(max_length=160)
    is_required = models.BooleanField(default=True)
    role_key = models.CharField(max_length=64, blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["phase", "position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_phase_definition_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "version", "key"],
                name="operations_phase_definition_key_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "version", "phase", "position"],
                name="operations_phase_definition_position_uq",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1), name="operations_phase_definition_position_ck"
            ),
        ]


class TemplateRoleDefinition(OperationsTenantModel):
    version = models.ForeignKey(
        OperationalTemplateVersion, on_delete=models.PROTECT, related_name="role_definitions"
    )
    key = models.CharField(max_length=64)
    label = models.CharField(max_length=120)
    phase = models.CharField(
        max_length=16, choices=TemplatePhaseDefinition.Phase.choices, blank=True
    )
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_role_definition_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "version", "key"],
                name="operations_role_definition_key_uq",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1), name="operations_role_definition_position_ck"
            ),
        ]


class TemplateResourceNeed(OperationsTenantModel):
    class Anchor(models.TextChoices):
        OCCUPIED_START = "occupied_start", "Inicio de ocupación"
        EVENT_START = "event_start", "Inicio del evento"
        EVENT_END = "event_end", "Fin del evento"
        OCCUPIED_END = "occupied_end", "Fin de ocupación"

    version = models.ForeignKey(
        OperationalTemplateVersion, on_delete=models.PROTECT, related_name="resource_needs"
    )
    key = models.CharField(max_length=64)
    resource = models.ForeignKey(
        "resources.Resource", on_delete=models.PROTECT, related_name="operational_template_needs"
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    start_anchor = models.CharField(max_length=20, choices=Anchor.choices)
    start_offset_minutes = models.IntegerField(default=0)
    end_anchor = models.CharField(max_length=20, choices=Anchor.choices)
    end_offset_minutes = models.IntegerField(default=0)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_resource_need_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "version", "key"],
                name="operations_resource_need_key_uq",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="operations_resource_need_quantity_ck"
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1), name="operations_resource_need_position_ck"
            ),
        ]


class OperationalPlanSnapshot(OperationsTenantModel):
    class SourceKind(models.TextChoices):
        ORGANIZATION = "organization", "Organizacional"
        SYSTEM = "system", "Sistema"
        LEGACY_CUTOVER = "legacy_cutover", "Cutover legado"

    preparation = models.OneToOneField(
        "operations.EventPreparation", on_delete=models.PROTECT, related_name="operational_snapshot"
    )
    source_kind = models.CharField(max_length=16, choices=SourceKind.choices)
    source_version = models.CharField(max_length=80)
    template_version = models.ForeignKey(
        OperationalTemplateVersion,
        on_delete=models.PROTECT,
        related_name="event_snapshots",
        null=True,
        blank=True,
    )
    event_type_id = models.UUIDField()
    event_type_label = models.CharField(max_length=100)
    canonical_payload = models.JSONField(default=dict)
    content_sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_plan_snapshot_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "preparation"], name="operations_plan_snapshot_prep_uq"
            ),
            models.CheckConstraint(
                condition=(
                    Q(source_kind="organization", template_version__isnull=False)
                    | Q(source_kind__in=["system", "legacy_cutover"], template_version__isnull=True)
                ),
                name="operations_plan_snapshot_source_ck",
            ),
        ]


class OperationalVerification(OperationsTenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        COMPLETED = "completed", "Completada"
        NOT_APPLICABLE = "not_applicable", "No aplica"

    preparation = models.ForeignKey(
        "operations.EventPreparation", on_delete=models.PROTECT, related_name="phase_verifications"
    )
    snapshot = models.ForeignKey(
        OperationalPlanSnapshot, on_delete=models.PROTECT, related_name="verifications"
    )
    definition = models.ForeignKey(
        TemplatePhaseDefinition,
        on_delete=models.PROTECT,
        related_name="event_verifications",
        null=True,
        blank=True,
    )
    source_key = models.CharField(max_length=64)
    phase = models.CharField(max_length=16, choices=TemplatePhaseDefinition.Phase.choices)
    title = models.CharField(max_length=160)
    is_required = models.BooleanField(default=True)
    role_key = models.CharField(max_length=64, blank=True)
    position = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    status_reason = models.CharField(max_length=500, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="completed_operational_verifications",
        null=True,
        blank=True,
    )
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["phase", "position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_verification_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "preparation", "source_key"],
                name="operations_verification_source_key_uq",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1) & Q(revision__gte=1),
                name="operations_verification_numbers_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="pending",
                        completed_at__isnull=True,
                        completed_by_membership__isnull=True,
                        status_reason="",
                    )
                    | Q(
                        status="completed",
                        completed_at__isnull=False,
                        completed_by_membership__isnull=False,
                        status_reason="",
                    )
                    | (
                        Q(
                            status="not_applicable",
                            completed_at__isnull=False,
                            completed_by_membership__isnull=False,
                        )
                        & ~Q(status_reason="")
                    )
                ),
                name="operations_verification_resolution_ck",
            ),
        ]


class OperationalVerificationEvent(OperationsTenantModel):
    verification = models.ForeignKey(
        OperationalVerification, on_delete=models.PROTECT, related_name="events"
    )
    from_status = models.CharField(max_length=16)
    to_status = models.CharField(max_length=16, choices=OperationalVerification.Status.choices)
    reason = models.CharField(max_length=500, blank=True)
    verification_revision = models.PositiveIntegerField()
    actor_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="operational_verification_events",
    )
    occurred_at = models.DateTimeField()
    idempotency_key = models.UUIDField()
    correction_reason = models.CharField(max_length=500, blank=True)
    corrects = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="correction",
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_verification_event_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "verification", "verification_revision"],
                name="operations_verification_event_revision_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_verification_event_request_uq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(corrects__isnull=True, correction_reason="")
                    | (Q(corrects__isnull=False) & ~Q(correction_reason=""))
                ),
                name="operations_verification_event_correction_ck",
            ),
        ]


class OperationalPhaseFact(OperationsTenantModel):
    class Phase(models.TextChoices):
        SETUP = "setup", "Montaje"
        TEARDOWN = "teardown", "Desmontaje"

    class FactKind(models.TextChoices):
        STARTED = "started", "Iniciada"
        COMPLETED = "completed", "Finalizada"

    preparation = models.ForeignKey(
        "operations.EventPreparation", on_delete=models.PROTECT, related_name="phase_facts"
    )
    phase = models.CharField(max_length=12, choices=Phase.choices)
    fact_kind = models.CharField(max_length=12, choices=FactKind.choices)
    observed_at = models.DateTimeField()
    actor_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="operational_phase_facts"
    )
    preparation_revision = models.PositiveIntegerField()
    idempotency_key = models.UUIDField()
    provenance = models.CharField(max_length=32, default="user_observation")
    corrects = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="correction",
        null=True,
        blank=True,
    )
    correction_reason = models.CharField(max_length=500, blank=True)
    payload_sha256 = models.CharField(max_length=64)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_phase_fact_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_phase_fact_request_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "preparation", "phase", "fact_kind"],
                condition=Q(corrects__isnull=True),
                name="operations_phase_fact_original_uq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(corrects__isnull=True, correction_reason="")
                    | (Q(corrects__isnull=False) & ~Q(correction_reason=""))
                ),
                name="operations_phase_fact_correction_ck",
            ),
        ]


class OperationalResponsibility(OperationsTenantModel):
    preparation = models.ForeignKey(
        "operations.EventPreparation", on_delete=models.PROTECT, related_name="responsibilities"
    )
    snapshot = models.ForeignKey(
        OperationalPlanSnapshot, on_delete=models.PROTECT, related_name="responsibilities"
    )
    role_key = models.CharField(max_length=64)
    phase = models.CharField(
        max_length=16, choices=TemplatePhaseDefinition.Phase.choices, blank=True
    )
    membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="operational_responsibilities",
        null=True,
        blank=True,
    )
    supersedes = models.OneToOneField(
        "self", on_delete=models.PROTECT, related_name="superseded_by", null=True, blank=True
    )
    assigned_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="assigned_operational_responsibilities",
    )
    preparation_revision = models.PositiveIntegerField()
    idempotency_key = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_responsibility_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_responsibility_request_uq",
            ),
        ]


class OperationalIncident(OperationsTenantModel):
    class Type(models.TextChoices):
        SAFETY = "safety", "Seguridad"
        SCHEDULE_OR_SPACE = "schedule_or_space", "Agenda o espacio"
        RESOURCE = "resource", "Recurso"
        SUPPLIER = "supplier", "Proveedor"
        SERVICE_QUALITY = "service_quality", "Calidad del servicio"
        CUSTOMER_SCOPE = "customer_scope", "Alcance del cliente"
        OTHER_OPERATIONAL = "other_operational", "Otra operativa"

    class Severity(models.TextChoices):
        LOW = "low", "Baja"
        MEDIUM = "medium", "Media"
        HIGH = "high", "Alta"
        CRITICAL = "critical", "Crítica"

    class Status(models.TextChoices):
        OPEN = "open", "Abierta"
        CONTAINED = "contained", "Contenida"
        RESOLVED = "resolved", "Resuelta"

    preparation = models.ForeignKey(
        "operations.EventPreparation", on_delete=models.PROTECT, related_name="incidents"
    )
    incident_type = models.CharField(max_length=24, choices=Type.choices)
    severity = models.CharField(max_length=12, choices=Severity.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    description = models.CharField(max_length=1000)
    impact = models.CharField(max_length=1000)
    responsible_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="responsible_operational_incidents",
        null=True,
        blank=True,
    )
    reported_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="reported_operational_incidents",
    )
    reported_at = models.DateTimeField()
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_incident_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="operations_incident_revision_positive"
            ),
        ]


class OperationalIncidentEvent(OperationsTenantModel):
    class Kind(models.TextChoices):
        OPENED = "opened", "Abierta"
        CONTAINED = "contained", "Contenida"
        RESOLVED = "resolved", "Resuelta"
        REASSIGNED = "reassigned", "Reasignada"
        IMPACT_UPDATED = "impact_updated", "Impacto actualizado"
        CORRECTED = "corrected", "Corregida"

    incident = models.ForeignKey(
        OperationalIncident, on_delete=models.PROTECT, related_name="events"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12, choices=OperationalIncident.Status.choices)
    severity = models.CharField(max_length=12, choices=OperationalIncident.Severity.choices)
    impact = models.CharField(max_length=1000)
    detail = models.CharField(max_length=1000, blank=True)
    responsible_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="operational_incident_events_as_responsible",
        null=True,
        blank=True,
    )
    actor_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="operational_incident_events",
    )
    incident_revision = models.PositiveIntegerField()
    occurred_at = models.DateTimeField()
    idempotency_key = models.UUIDField()
    corrects = models.OneToOneField(
        "self", on_delete=models.PROTECT, related_name="correction", null=True, blank=True
    )

    class Meta:
        ordering = ["incident_revision", "occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_incident_event_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "incident", "incident_revision"],
                name="operations_incident_event_revision_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_incident_event_request_uq",
            ),
            models.CheckConstraint(
                condition=Q(kind="corrected", corrects__isnull=False) | ~Q(kind="corrected"),
                name="operations_incident_event_correction_ck",
            ),
        ]


class OperationalChangeProposal(OperationsTenantModel):
    class Scope(models.TextChoices):
        READINESS = "readiness", "Readiness"
        VERIFICATION = "verification", "Verificación"
        RESPONSIBILITY = "responsibility", "Responsabilidad"
        RESOURCE_NEED = "resource_need", "Necesidad de recurso"
        RESOURCE_WINDOW = "resource_window", "Ventana de recurso"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        APPROVED = "approved", "Aprobada"
        REJECTED = "rejected", "Rechazada"

    preparation = models.ForeignKey(
        "operations.EventPreparation", on_delete=models.PROTECT, related_name="change_proposals"
    )
    scope = models.CharField(max_length=20, choices=Scope.choices)
    target_id = models.UUIDField()
    before_payload = models.JSONField(default=dict)
    proposed_payload = models.JSONField(default=dict)
    reason = models.CharField(max_length=1000)
    impact = models.CharField(max_length=1000)
    proposed_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="proposed_operational_changes",
    )
    expected_preparation_revision = models.PositiveIntegerField()
    idempotency_key = models.UUIDField()
    payload_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_change_proposal_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_change_proposal_request_uq",
            ),
            models.CheckConstraint(
                condition=Q(impact=Trim("impact")) & ~Q(impact=""),
                name="operations_change_proposal_impact_ck",
            ),
        ]


class OperationalChangeDecision(OperationsTenantModel):
    proposal = models.OneToOneField(
        OperationalChangeProposal, on_delete=models.PROTECT, related_name="decision"
    )
    approved = models.BooleanField()
    reason = models.CharField(max_length=1000)
    decided_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="decided_operational_changes",
    )
    expected_preparation_revision = models.PositiveIntegerField()
    idempotency_key = models.UUIDField()
    payload_sha256 = models.CharField(max_length=64)
    decided_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_change_decision_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_change_decision_request_uq",
            ),
        ]


class ReadinessDeviation(OperationsTenantModel):
    item = models.ForeignKey(
        "operations.PreparationItem", on_delete=models.PROTECT, related_name="readiness_deviations"
    )
    decision = models.OneToOneField(
        OperationalChangeDecision, on_delete=models.PROTECT, related_name="readiness_deviation"
    )
    before_payload = models.JSONField(default=dict)
    effective_payload = models.JSONField(default=dict)
    reason = models.CharField(max_length=1000)
    item_revision = models.PositiveIntegerField()
    payload_sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_readiness_deviation_org_id_uq"
            )
        ]


class OperationalResourceWindow(OperationsTenantModel):
    class SourceKind(models.TextChoices):
        ORGANIZATION_TEMPLATE = "organization_template", "Plantilla organizacional"
        SYSTEM_TEMPLATE = "system_template", "Plantilla de sistema"
        AUTHORIZED_CHANGE = "authorized_change", "Cambio autorizado"

    preparation = models.ForeignKey(
        "operations.EventPreparation", on_delete=models.PROTECT, related_name="resource_windows"
    )
    snapshot = models.ForeignKey(
        OperationalPlanSnapshot, on_delete=models.PROTECT, related_name="resource_windows"
    )
    resource_need = models.ForeignKey(
        TemplateResourceNeed,
        on_delete=models.PROTECT,
        related_name="event_windows",
        null=True,
        blank=True,
    )
    root_reservation_id = models.UUIDField()
    reservation = models.ForeignKey(
        "scheduling.Reservation",
        on_delete=models.PROTECT,
        related_name="operational_resource_windows",
    )
    schedule_allocation = models.ForeignKey(
        "scheduling.ScheduleAllocation",
        on_delete=models.PROTECT,
        related_name="operational_resource_windows",
    )
    schedule_event = models.ForeignKey(
        "scheduling.ScheduleEvent",
        on_delete=models.PROTECT,
        related_name="operational_resource_windows",
    )
    resource = models.ForeignKey(
        "resources.Resource", on_delete=models.PROTECT, related_name="operational_windows"
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    required_interval = DateTimeRangeField()
    window_revision = models.PositiveIntegerField(default=1)
    predecessor = models.OneToOneField(
        "self", on_delete=models.PROTECT, related_name="successor", null=True, blank=True
    )
    source_kind = models.CharField(max_length=24, choices=SourceKind.choices)
    source_version = models.CharField(max_length=80)
    authorization_decision = models.ForeignKey(
        OperationalChangeDecision,
        on_delete=models.PROTECT,
        related_name="resource_windows",
        null=True,
        blank=True,
    )
    schedule_reservation_revision = models.PositiveIntegerField()
    schedule_source_revision = models.PositiveIntegerField()
    idempotency_key = models.UUIDField()
    payload_sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_resource_window_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_resource_window_request_uq",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0)
                & Q(window_revision__gte=1)
                & Q(schedule_reservation_revision__gte=1)
                & Q(schedule_source_revision__gte=1),
                name="operations_resource_window_numbers_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(source_kind="authorized_change", authorization_decision__isnull=False)
                    | (
                        Q(source_kind__in=["organization_template", "system_template"])
                        & Q(authorization_decision__isnull=True)
                    )
                ),
                name="operations_resource_window_source_ck",
            ),
        ]


class OperationalEvidence(OperationsTenantModel):
    class TargetKind(models.TextChoices):
        GENERAL = "general", "General"
        VERIFICATION = "verification", "Verificación"
        INCIDENT = "incident", "Incidencia"
        CHANGE = "change", "Cambio"
        CLOSE = "close", "Cierre"

    preparation = models.ForeignKey(
        "operations.EventPreparation", on_delete=models.PROTECT, related_name="operational_evidence"
    )
    target_kind = models.CharField(max_length=16, choices=TargetKind.choices)
    target_id = models.UUIDField()
    document_file = models.ForeignKey(
        "documents.PrivateDomainFile",
        on_delete=models.PROTECT,
        related_name="operational_evidence_links",
    )
    linked_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="linked_operational_evidence",
    )
    idempotency_key = models.UUIDField()
    payload_sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_evidence_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_evidence_request_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "preparation", "target_kind", "target_id", "document_file"],
                name="operations_evidence_target_file_uq",
            ),
        ]


class PostEventClose(OperationsTenantModel):
    preparation = models.OneToOneField(
        "operations.EventPreparation", on_delete=models.PROTECT, related_name="post_event_close"
    )
    closed_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="closed_operational_events",
    )
    closed_at = models.DateTimeField()
    preparation_revision = models.PositiveIntegerField()
    source_snapshot = models.JSONField(default=dict)
    source_sha256 = models.CharField(max_length=64)
    idempotency_key = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_post_close_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "preparation"], name="operations_post_close_prep_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_post_close_request_uq",
            ),
        ]


class PostEventCloseCorrection(OperationsTenantModel):
    close = models.ForeignKey(PostEventClose, on_delete=models.PROTECT, related_name="corrections")
    reason = models.CharField(max_length=1000)
    correction_payload = models.JSONField(default=dict)
    payload_sha256 = models.CharField(max_length=64)
    corrected_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="corrected_operational_closes",
    )
    idempotency_key = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_post_close_correction_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_post_close_correction_request_uq",
            ),
        ]


class OperationCommand(OperationsTenantModel):
    command_type = models.CharField(max_length=48)
    idempotency_key = models.UUIDField()
    payload_sha256 = models.CharField(max_length=64)
    result_kind = models.CharField(max_length=48)
    result_id = models.UUIDField()
    actor_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="advanced_operation_commands",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_command_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "command_type", "idempotency_key"],
                name="operations_command_idempotency_uq",
            ),
        ]
