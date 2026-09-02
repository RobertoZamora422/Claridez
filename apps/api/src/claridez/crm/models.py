from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from django.db.models.functions import Trim

from claridez.organizations.models import Membership, Organization


class Interaction(models.Model):
    class Channel(models.TextChoices):
        PHONE_CALL = "phone_call", "Llamada"
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "Correo"
        IN_PERSON = "in_person", "Presencial"
        SOCIAL_NETWORK = "social_network", "Red social"
        OTHER = "other", "Otro"

    class Direction(models.TextChoices):
        INBOUND = "inbound", "Entrante"
        OUTBOUND = "outbound", "Saliente"

    class RecorderKind(models.TextChoices):
        INTERNAL_MEMBERSHIP = "internal_membership", "Membresía interna"
        COMMUNICATIONS = "communications", "Comunicación semántica"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="crm_interactions", db_index=False
    )
    event_request = models.ForeignKey(
        "commercial.EventRequest",
        on_delete=models.PROTECT,
        related_name="crm_interactions",
        null=True,
        blank=True,
        db_index=False,
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    direction = models.CharField(max_length=12, choices=Direction.choices)
    occurred_at = models.DateTimeField()
    responsible_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        related_name="responsible_crm_interactions",
        db_index=False,
        null=True,
        blank=True,
    )
    summary = models.CharField(max_length=1000)
    correction_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="corrections",
        null=True,
        blank=True,
        db_index=False,
    )
    recorded_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        related_name="recorded_crm_interactions",
        db_index=False,
        null=True,
        blank=True,
    )
    recorder_kind = models.CharField(
        max_length=24, choices=RecorderKind.choices, default=RecorderKind.INTERNAL_MEMBERSHIP
    )
    communication_purpose = models.CharField(max_length=32, blank=True)
    communication_reference = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="crm_interaction_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(
                    channel__in=[
                        "phone_call",
                        "whatsapp",
                        "email",
                        "in_person",
                        "social_network",
                        "other",
                    ]
                ),
                name="crm_interaction_channel_valid",
            ),
            models.CheckConstraint(
                condition=Q(direction__in=["inbound", "outbound"]),
                name="crm_interaction_direction_valid",
            ),
            models.CheckConstraint(
                condition=Q(summary=Trim("summary")) & ~Q(summary=""),
                name="crm_interaction_summary_canonical",
            ),
            models.CheckConstraint(
                condition=~Q(id=models.F("correction_of")),
                name="crm_interaction_not_self_correction",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        recorder_kind="internal_membership",
                        responsible_membership__isnull=False,
                        recorded_by_membership__isnull=False,
                        communication_purpose="",
                        communication_reference__isnull=True,
                    )
                    | (
                        Q(
                            recorder_kind="communications",
                            responsible_membership__isnull=True,
                            recorded_by_membership__isnull=True,
                            communication_purpose=Trim("communication_purpose"),
                            communication_reference__isnull=False,
                            correction_of__isnull=True,
                        )
                        & ~Q(communication_purpose="")
                    )
                ),
                name="crm_interaction_recorder_valid",
            ),
            models.UniqueConstraint(
                fields=["organization", "communication_reference"],
                condition=Q(recorder_kind="communications"),
                name="crm_interaction_communication_ref_uq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.person_id}@{self.occurred_at.isoformat()}"


class FollowUpTask(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Pendiente"
        COMPLETED = "completed", "Completada"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="crm_tasks", db_index=False
    )
    event_request = models.ForeignKey(
        "commercial.EventRequest",
        on_delete=models.PROTECT,
        related_name="crm_tasks",
        null=True,
        blank=True,
        db_index=False,
    )
    title = models.CharField(max_length=180)
    due_at = models.DateTimeField()
    next_contact_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    responsible_membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="crm_tasks", db_index=False
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        related_name="completed_crm_tasks",
        null=True,
        blank=True,
        db_index=False,
    )
    cancellation_reason = models.CharField(max_length=500, blank=True)
    cancellation_reason_unavailable = models.BooleanField(default=False, editable=False)
    revision = models.PositiveIntegerField(default=1)
    created_by_membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="created_crm_tasks", db_index=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="crm_task_org_id_uq"),
            models.CheckConstraint(
                condition=Q(title=Trim("title")) & ~Q(title=""), name="crm_task_title_canonical"
            ),
            models.CheckConstraint(
                condition=Q(status__in=["open", "completed", "cancelled"]),
                name="crm_task_status_valid",
            ),
            models.CheckConstraint(condition=Q(revision__gte=1), name="crm_task_revision_positive"),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="completed",
                        completed_at__isnull=False,
                        completed_by_membership__isnull=False,
                    )
                    | Q(
                        status__in=["open", "cancelled"],
                        completed_at__isnull=True,
                        completed_by_membership__isnull=True,
                    )
                ),
                name="crm_task_completed_evidence",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="cancelled",
                        cancellation_reason=Trim("cancellation_reason"),
                        cancellation_reason_unavailable=False,
                    )
                    & ~Q(cancellation_reason="")
                    | Q(
                        status="cancelled",
                        cancellation_reason="",
                        cancellation_reason_unavailable=True,
                    )
                    | Q(
                        status__in=["open", "completed"],
                        cancellation_reason="",
                        cancellation_reason_unavailable=False,
                    )
                ),
                name="crm_task_cancellation_reason",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class FollowUpTaskHistory(models.Model):
    class Kind(models.TextChoices):
        CREATED = "created", "Creación"
        UPDATED = "updated", "Actualización"
        COMPLETED = "completed", "Finalización"
        CANCELLED = "cancelled", "Cancelación"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    task = models.ForeignKey(
        FollowUpTask, on_delete=models.PROTECT, related_name="history", db_index=False
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    revision = models.PositiveIntegerField()
    title = models.CharField(max_length=180)
    due_at = models.DateTimeField()
    next_contact_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=FollowUpTask.Status.choices)
    responsible_membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="crm_task_history_responsibilities"
    )
    changed_by_membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="crm_task_history_actions"
    )
    reason = models.CharField(max_length=500, blank=True)
    reason_unavailable = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="crm_taskhistory_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "task", "revision"],
                name="crm_taskhistory_org_task_revision_uq",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="crm_taskhistory_revision_positive"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind="cancelled",
                        reason=Trim("reason"),
                        reason_unavailable=False,
                    )
                    & ~Q(reason="")
                    | Q(kind="cancelled", reason="", reason_unavailable=True)
                    | Q(
                        kind__in=["created", "updated", "completed"],
                        reason="",
                        reason_unavailable=False,
                    )
                ),
                name="crm_taskhistory_reason_matches_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.task_id}@{self.revision}"
