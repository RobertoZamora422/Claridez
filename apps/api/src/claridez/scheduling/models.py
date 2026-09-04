from __future__ import annotations

import uuid

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Trim

from claridez.organizations.models import Membership, Organization, Space, Venue


class SpaceSchedulePolicy(models.Model):
    space = models.OneToOneField(
        Space,
        on_delete=models.PROTECT,
        related_name="schedule_policy",
        primary_key=True,
    )
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    setup_minutes = models.PositiveIntegerField(default=0)
    teardown_minutes = models.PositiveIntegerField(default=0)
    buffer_before_minutes = models.PositiveIntegerField(default=0)
    buffer_after_minutes = models.PositiveIntegerField(default=0)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "space"], name="scheduling_policy_org_space_uq"
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="scheduling_policy_revision_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.space_id}@r{self.revision}"


class Reservation(models.Model):
    class Status(models.TextChoices):
        PROVISIONAL = "provisional", "Provisional"
        CONFIRMED = "confirmed", "Confirmada"
        EXPIRED = "expired", "Vencida"
        CANCELLED = "cancelled", "Cancelada"
        RESCHEDULED = "rescheduled", "Reprogramada"

    class ConfirmationKind(models.TextChoices):
        EXTERNAL_DEPOSIT = "external_deposit", "Anticipo recibido externamente"
        WAIVER = "waiver", "Excepción autorizada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    event_request = models.ForeignKey(
        "commercial.EventRequest",
        on_delete=models.PROTECT,
        related_name="reservations",
        db_index=False,
    )
    quotation_version = models.ForeignKey(
        "commercial.QuotationVersion",
        on_delete=models.PROTECT,
        related_name="reservation",
        db_index=False,
    )
    space = models.ForeignKey(
        Space, on_delete=models.PROTECT, related_name="reservations", db_index=False
    )
    root = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="chain_members",
        db_constraint=False,
        db_index=False,
    )
    predecessor = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="successor",
        null=True,
        blank=True,
        db_constraint=False,
    )
    confirmation_source = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="confirmation_successors",
        null=True,
        blank=True,
        db_constraint=False,
        db_index=False,
    )
    event_interval = DateTimeRangeField()
    event_timezone = models.CharField(max_length=64)
    setup_minutes = models.PositiveIntegerField(default=0)
    teardown_minutes = models.PositiveIntegerField(default=0)
    buffer_before_minutes = models.PositiveIntegerField(default=0)
    buffer_after_minutes = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROVISIONAL)
    revision = models.PositiveIntegerField(default=1)
    hold_expires_at = models.DateTimeField()
    confirmation_kind = models.CharField(
        max_length=24, choices=ConfirmationKind.choices, blank=True
    )
    recognized_deposit_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    deposit_reported_at = models.DateTimeField(null=True, blank=True)
    deposit_reference = models.CharField(max_length=300, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="confirmed_reservations",
    )
    waiver_reason = models.CharField(max_length=500, blank=True)
    waiver_authorized_at = models.DateTimeField(null=True, blank=True)
    waiver_authorized_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="waived_reservation_deposits",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cancelled_reservations",
    )
    cancellation_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "commercial_reservation"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="commercial_reservation_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "quotation_version"],
                condition=Q(predecessor__isnull=True),
                name="scheduling_reservation_quote_root_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "event_request"],
                condition=Q(status__in=["provisional", "confirmed"]),
                name="commercial_reservation_one_active_request_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "root"],
                condition=Q(status__in=["provisional", "confirmed"]),
                name="scheduling_reservation_one_active_root_uq",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "provisional",
                        "confirmed",
                        "expired",
                        "cancelled",
                        "rescheduled",
                    ]
                ),
                name="commercial_reservation_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="scheduling_reservation_revision_positive"
            ),
            models.CheckConstraint(
                condition=(
                    Q(predecessor__isnull=True, root=F("id"))
                    | (Q(predecessor__isnull=False) & ~Q(root=F("id")))
                ),
                name="scheduling_reservation_root_shape",
            ),
            models.CheckConstraint(
                condition=Q(recognized_deposit_amount__isnull=True)
                | Q(recognized_deposit_amount__gt=0),
                name="commercial_reservation_deposit_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "root", "created_at", "id"],
                name="scheduling_res_root_chain_idx",
            ),
            models.Index(
                fields=["organization", "event_request", "status"],
                name="scheduling_res_request_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_request_id}@{self.status}"


class ScheduleBlock(models.Model):
    class Scope(models.TextChoices):
        SPACES = "spaces", "Espacios seleccionados"
        VENUE = "venue", "Sede completa"

    class Status(models.TextChoices):
        ACTIVE = "active", "Activo"
        RELEASED = "released", "Liberado"
        CANCELLED = "cancelled", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="schedule_blocks")
    scope = models.CharField(max_length=8, choices=Scope.choices)
    blocked_interval = DateTimeRangeField()
    event_timezone = models.CharField(max_length=64)
    reason = models.CharField(max_length=500)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    revision = models.PositiveIntegerField(default=1)
    created_by_membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="created_schedule_blocks"
    )
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        related_name="ended_schedule_blocks",
        null=True,
        blank=True,
    )
    termination_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="scheduling_block_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(scope__in=["spaces", "venue"]), name="scheduling_block_scope_valid"
            ),
            models.CheckConstraint(
                condition=Q(status__in=["active", "released", "cancelled"]),
                name="scheduling_block_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="scheduling_block_revision_positive"
            ),
            models.CheckConstraint(
                condition=Q(reason=Trim("reason")) & ~Q(reason=""),
                name="scheduling_block_reason_required",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="active",
                        ended_at__isnull=True,
                        ended_by_membership__isnull=True,
                        termination_reason="",
                    )
                    | (
                        Q(
                            status__in=["released", "cancelled"],
                            ended_at__isnull=False,
                            ended_by_membership__isnull=False,
                        )
                        & ~Q(termination_reason="")
                    )
                ),
                name="scheduling_block_termination_evidence",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "venue", "status"], name="scheduling_block_venue_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.venue_id}@{self.status}"


class ScheduleBlockTarget(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    block = models.ForeignKey(
        ScheduleBlock, on_delete=models.PROTECT, related_name="targets", db_index=False
    )
    space = models.ForeignKey(
        Space,
        on_delete=models.PROTECT,
        related_name="schedule_block_targets",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="scheduling_blocktarget_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "block", "space"],
                name="scheduling_blocktarget_org_block_space_uq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.block_id}:{self.space_id}"


class ScheduleEvent(models.Model):
    class Kind(models.TextChoices):
        CUTOVER_SNAPSHOT = "cutover_snapshot", "Snapshot de cutover"
        RESERVATION_HOLD_CREATED = "reservation_hold_created", "Hold creado"
        RESERVATION_CONFIRMED = "reservation_confirmed", "Reserva confirmada"
        RESERVATION_EXPIRED = "reservation_expired", "Hold vencido"
        RESERVATION_RESCHEDULED = "reservation_rescheduled", "Reserva reprogramada"
        RESERVATION_CANCELLED = "reservation_cancelled", "Reserva cancelada"
        BLOCK_CREATED = "block_created", "Bloqueo creado"
        BLOCK_RELEASED = "block_released", "Bloqueo liberado"
        BLOCK_CANCELLED = "block_cancelled", "Bloqueo cancelado"

    class Source(models.TextChoices):
        USER = "user", "Usuario"
        DATABASE_EXPIRATION = "database_expiration", "Expiración de base de datos"
        CUTOVER = "cutover", "Cutover"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    kind = models.CharField(max_length=32, choices=Kind.choices)
    source = models.CharField(max_length=24, choices=Source.choices)
    actor_membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        related_name="schedule_events",
        null=True,
        blank=True,
    )
    reason = models.CharField(max_length=500, blank=True)
    event_request = models.ForeignKey(
        "commercial.EventRequest",
        on_delete=models.PROTECT,
        related_name="schedule_events",
        null=True,
        blank=True,
        db_index=False,
    )
    root_reservation = models.ForeignKey(
        Reservation,
        on_delete=models.PROTECT,
        related_name="root_schedule_events",
        null=True,
        blank=True,
        db_constraint=False,
    )
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.PROTECT,
        related_name="schedule_events",
        null=True,
        blank=True,
        db_constraint=False,
    )
    predecessor = models.ForeignKey(
        Reservation,
        on_delete=models.PROTECT,
        related_name="predecessor_schedule_events",
        null=True,
        blank=True,
        db_constraint=False,
    )
    successor = models.ForeignKey(
        Reservation,
        on_delete=models.PROTECT,
        related_name="successor_schedule_events",
        null=True,
        blank=True,
        db_constraint=False,
    )
    block = models.ForeignKey(
        ScheduleBlock,
        on_delete=models.PROTECT,
        related_name="schedule_events",
        null=True,
        blank=True,
        db_index=False,
    )
    aggregate_revision = models.PositiveIntegerField()
    previous_snapshot = models.JSONField(default=dict)
    new_snapshot = models.JSONField(default=dict)
    analytics_previous_venue = models.ForeignKey(
        Venue,
        on_delete=models.PROTECT,
        null=True,
        editable=False,
        db_index=False,
        related_name="previous_schedule_analytics_evidence",
    )
    analytics_new_venue = models.ForeignKey(
        Venue,
        on_delete=models.PROTECT,
        null=True,
        editable=False,
        db_index=False,
        related_name="new_schedule_analytics_evidence",
    )
    idempotency_key = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at", "recorded_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="scheduling_event_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "kind", "idempotency_key"],
                name="scheduling_event_idempotency_uq",
            ),
            models.CheckConstraint(
                condition=Q(aggregate_revision__gte=1),
                name="scheduling_event_revision_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(source="user", actor_membership__isnull=False)
                    | Q(
                        source__in=["database_expiration", "cutover"],
                        actor_membership__isnull=True,
                    )
                ),
                name="scheduling_event_actor_source",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "event_request", "occurred_at"],
                name="scheduling_event_request_idx",
            ),
            models.Index(
                fields=["organization", "root_reservation", "occurred_at"],
                name="scheduling_event_root_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}@{self.aggregate_revision}"


class ScheduleAllocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    space = models.ForeignKey(Space, on_delete=models.PROTECT, related_name="schedule_allocations")
    reservation = models.OneToOneField(
        Reservation,
        on_delete=models.PROTECT,
        related_name="allocation",
        null=True,
        blank=True,
        db_constraint=False,
    )
    block_target = models.OneToOneField(
        ScheduleBlockTarget,
        on_delete=models.PROTECT,
        related_name="allocation",
        null=True,
        blank=True,
        db_constraint=False,
    )
    occupied_interval = DateTimeRangeField()
    source_revision = models.PositiveIntegerField()
    source_event = models.ForeignKey(
        ScheduleEvent,
        on_delete=models.PROTECT,
        related_name="allocations",
        db_constraint=False,
    )
    is_blocking = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="scheduling_allocation_org_id_uq"
            ),
            models.CheckConstraint(
                condition=(
                    Q(reservation__isnull=False, block_target__isnull=True)
                    | Q(reservation__isnull=True, block_target__isnull=False)
                ),
                name="scheduling_allocation_one_origin",
            ),
            models.CheckConstraint(
                condition=Q(source_revision__gte=1),
                name="scheduling_allocation_revision_positive",
            ),
            ExclusionConstraint(
                name="scheduling_allocation_no_overlap",
                expressions=[
                    ("organization", RangeOperators.EQUAL),
                    ("space", RangeOperators.EQUAL),
                    ("occupied_interval", RangeOperators.OVERLAPS),
                ],
                condition=Q(is_blocking=True),
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "space", "is_blocking"],
                name="scheduling_alloc_space_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.space_id}@{self.occupied_interval}"
