from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q

from claridez.organizations.models import Membership, Organization


class EventPreparation(models.Model):
    class Status(models.TextChoices):
        PREPARING = "preparing", "En preparación"
        READY = "ready", "Listo"
        IN_PROGRESS = "in_progress", "En ejecución"
        COMPLETED = "completed", "Completado"
        CANCELLED = "cancelled", "Cancelado"
        RESCHEDULED = "rescheduled", "Reprogramado"

    reservation = models.OneToOneField(
        "scheduling.Reservation",
        on_delete=models.PROTECT,
        related_name="preparation",
        primary_key=True,
    )
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PREPARING)
    responsible_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="responsible_event_preparations",
    )
    operational_notes = models.TextField(blank=True, max_length=4000)
    baseline_version = models.CharField(max_length=32, default="operations-5.2-v1", editable=False)
    revision = models.PositiveIntegerField(default=1)
    ready_at = models.DateTimeField(null=True, blank=True)
    ready_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="readied_event_preparations",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    started_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="started_event_preparations",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="completed_event_preparations",
    )
    rescheduled_to_reservation = models.OneToOneField(
        "scheduling.Reservation",
        on_delete=models.PROTECT,
        related_name="rescheduled_from_preparation",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reservation"], name="operations_preparation_org_res_uq"
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "preparing",
                        "ready",
                        "in_progress",
                        "completed",
                        "cancelled",
                        "rescheduled",
                    ]
                ),
                name="operations_preparation_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="operations_preparation_revision_positive"
            ),
            models.CheckConstraint(
                condition=(
                    Q(ready_at__isnull=True, ready_by_membership__isnull=True)
                    | Q(ready_at__isnull=False, ready_by_membership__isnull=False)
                ),
                name="operations_preparation_ready_evidence",
            ),
            models.CheckConstraint(
                condition=(
                    Q(started_at__isnull=True, started_by_membership__isnull=True)
                    | Q(started_at__isnull=False, started_by_membership__isnull=False)
                ),
                name="operations_preparation_started_evidence",
            ),
            models.CheckConstraint(
                condition=(
                    Q(completed_at__isnull=True, completed_by_membership__isnull=True)
                    | Q(completed_at__isnull=False, completed_by_membership__isnull=False)
                ),
                name="operations_preparation_completed_evidence",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="rescheduled", rescheduled_to_reservation__isnull=False)
                    | (~Q(status="rescheduled") & Q(rescheduled_to_reservation__isnull=True))
                ),
                name="operations_preparation_rescheduled_evidence",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="operations_prep_status_idx"),
            models.Index(
                fields=["organization", "responsible_membership"],
                name="operations_prep_owner_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reservation_id}@{self.status}"


class PreparationItem(models.Model):
    class SourceKind(models.TextChoices):
        BASELINE_5_2 = "baseline_5_2", "Baseline 5.2"
        MANUAL = "manual", "Manual"
        P13_TEMPLATE_READINESS = "p13_template_readiness", "Readiness de plantilla P13"

    class Section(models.TextChoices):
        DEFINITIONS = "definitions", "Definiciones"
        SETUP = "setup", "Preparación"
        FINAL_REVIEW = "final_review", "Revisión final"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        IN_PROGRESS = "in_progress", "En curso"
        BLOCKED = "blocked", "Bloqueado"
        COMPLETED = "completed", "Completado"
        NOT_APPLICABLE = "not_applicable", "No aplica"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    preparation = models.ForeignKey(
        EventPreparation, on_delete=models.PROTECT, related_name="items", db_index=False
    )
    client_request_id = models.UUIDField()
    baseline_key = models.CharField(max_length=48, null=True, blank=True)  # noqa: DJ001
    source_kind = models.CharField(
        max_length=32, choices=SourceKind.choices, default=SourceKind.MANUAL
    )
    template_readiness_definition = models.ForeignKey(
        "operations.TemplateReadinessDefinition",
        on_delete=models.PROTECT,
        related_name="preparation_items",
        null=True,
        blank=True,
    )
    template_role_key = models.CharField(max_length=64, blank=True)
    section = models.CharField(max_length=16, choices=Section.choices)
    position = models.PositiveIntegerField()
    title = models.CharField(max_length=160)
    is_required = models.BooleanField(default=True)
    responsible_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="responsible_preparation_items",
    )
    due_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True, max_length=2000)
    status_note = models.CharField(max_length=500, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="resolved_preparation_items",
    )
    carried_from_item = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="carried_copies",
        null=True,
        blank=True,
    )
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_item_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "preparation", "position"],
                name="operations_item_org_position_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "preparation", "client_request_id"],
                name="operations_item_org_request_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "preparation", "baseline_key"],
                condition=Q(baseline_key__isnull=False),
                name="operations_item_org_baseline_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "preparation", "carried_from_item"],
                condition=Q(carried_from_item__isnull=False),
                name="operations_item_org_carried_uq",
            ),
            models.CheckConstraint(
                condition=Q(section__in=["definitions", "setup", "final_review"]),
                name="operations_item_section_valid",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "pending",
                        "in_progress",
                        "blocked",
                        "completed",
                        "not_applicable",
                    ]
                ),
                name="operations_item_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1) & Q(revision__gte=1),
                name="operations_item_numbers_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status__in=["completed", "not_applicable"],
                        resolved_at__isnull=False,
                        resolved_by_membership__isnull=False,
                    )
                    | Q(
                        status__in=["pending", "in_progress", "blocked"],
                        resolved_at__isnull=True,
                        resolved_by_membership__isnull=True,
                    )
                ),
                name="operations_item_resolution_valid",
            ),
            models.CheckConstraint(
                condition=(Q(status__in=["blocked", "not_applicable"]) & ~Q(status_note=""))
                | (Q(status__in=["pending", "in_progress", "completed"]) & Q(status_note="")),
                name="operations_item_status_note_valid",
            ),
            models.CheckConstraint(
                condition=~Q(baseline_key="final_readiness_review", status="not_applicable"),
                name="operations_final_review_applies",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        source_kind="baseline_5_2",
                        baseline_key__isnull=False,
                        template_readiness_definition__isnull=True,
                    )
                    | Q(
                        source_kind="manual",
                        baseline_key__isnull=True,
                        template_readiness_definition__isnull=True,
                    )
                    | Q(
                        source_kind="p13_template_readiness",
                        baseline_key__isnull=True,
                        template_readiness_definition__isnull=False,
                    )
                ),
                name="operations_item_source_shape_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "preparation", "status"],
                name="operations_item_status_idx",
            ),
            models.Index(fields=["organization", "due_on"], name="operations_item_due_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.preparation_id}@{self.position}"


class PreparationTransition(models.Model):
    class Cause(models.TextChoices):
        INITIALIZED = "initialized", "Inicializada"
        READINESS_DECLARED = "readiness_declared", "Lista"
        CHECKLIST_REOPENED = "checklist_reopened", "Checklist reabierto"
        EXECUTION_STARTED = "execution_started", "Ejecución iniciada"
        EXECUTION_COMPLETED = "execution_completed", "Ejecución completada"
        COMMERCIAL_CANCELLATION = "commercial_cancellation", "Cancelación comercial"
        SCHEDULE_RESCHEDULE = "schedule_reschedule", "Reprogramación de agenda"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    preparation = models.ForeignKey(
        EventPreparation, on_delete=models.PROTECT, related_name="transitions", db_index=False
    )
    from_status = models.CharField(max_length=16, null=True, blank=True)  # noqa: DJ001
    to_status = models.CharField(max_length=16, choices=EventPreparation.Status.choices)
    cause = models.CharField(max_length=32, choices=Cause.choices)
    actor_membership = models.ForeignKey(Membership, on_delete=models.PROTECT)
    preparation_revision = models.PositiveIntegerField()
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["preparation_revision", "occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="operations_transition_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "preparation", "preparation_revision"],
                name="operations_transition_org_revision_uq",
            ),
            models.CheckConstraint(
                condition=Q(preparation_revision__gte=1),
                name="operations_transition_revision_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.preparation_id}@{self.preparation_revision}"


from .advanced_models import (  # noqa: E402, F401
    OperationalChangeDecision,
    OperationalChangeProposal,
    OperationalEvidence,
    OperationalIncident,
    OperationalIncidentEvent,
    OperationalPhaseFact,
    OperationalPlanSnapshot,
    OperationalResourceWindow,
    OperationalResponsibility,
    OperationalTemplate,
    OperationalTemplateVersion,
    OperationalVerification,
    OperationalVerificationEvent,
    OperationCommand,
    PostEventClose,
    PostEventCloseCorrection,
    ReadinessDeviation,
    TemplatePhaseDefinition,
    TemplateReadinessDefinition,
    TemplateResourceNeed,
    TemplateRoleDefinition,
)
