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


class ReceivableObligation(TenantModel):
    root_reservation_id = models.UUIDField()
    confirmation_source_id = models.UUIDField()
    confirmation_event_id = models.UUIDField()
    event_request_id = models.UUIDField()
    quotation_version_id = models.UUIDField()
    quotation_visible_number = models.CharField(max_length=40)
    quotation_version = models.PositiveIntegerField()
    counterparty_person_id = models.UUIDField()
    counterparty_name_snapshot = models.CharField(max_length=240)
    currency = models.CharField(max_length=3)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2)
    discount_total = models.DecimalField(max_digits=18, decimal_places=2)
    original_total = models.DecimalField(max_digits=18, decimal_places=2)
    economic_terms_snapshot = models.JSONField(default=dict)
    confirmed_at = models.DateTimeField()
    created_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="created_receivable_obligations",
        db_index=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_obligation_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "root_reservation_id"],
                name="receivables_obligation_org_root_uq",
            ),
            models.CheckConstraint(
                condition=Q(quotation_version__gte=1),
                name="receivables_obligation_quote_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(subtotal__gte=0)
                    & Q(discount_total__gte=0)
                    & Q(original_total__gte=0)
                    & Q(discount_total__lte=models.F("subtotal"))
                    & Q(original_total=models.F("subtotal") - models.F("discount_total"))
                ),
                name="receivables_obligation_totals_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "counterparty_person_id", "created_at"],
                name="recv_obligation_person_idx",
            ),
            models.Index(
                fields=["organization", "event_request_id"],
                name="recv_obligation_request_idx",
            ),
        ]


class CollectionScheduleRevision(TenantModel):
    class Provenance(models.TextChoices):
        MANUAL = "manual", "Configuración manual"
        COMMERCIAL_TERMS = "commercial_terms", "Términos comerciales estructurados"
        LEGACY_REVIEW = "legacy_review", "Revisión histórica"

    obligation = models.ForeignKey(
        ReceivableObligation, on_delete=models.PROTECT, related_name="schedule_revisions"
    )
    revision = models.PositiveIntegerField()
    provenance = models.CharField(max_length=32, choices=Provenance.choices)
    reason = models.CharField(max_length=500)
    actor_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="receivable_schedule_revisions",
        db_index=False,
    )
    published_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_schedule_revision_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "obligation", "revision"],
                name="receivables_schedule_revision_org_number_uq",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="receivables_schedule_revision_positive"
            ),
        ]


class CollectionScheduleDue(TenantModel):
    schedule_revision = models.ForeignKey(
        CollectionScheduleRevision, on_delete=models.PROTECT, related_name="dues"
    )
    obligation = models.ForeignKey(
        ReceivableObligation, on_delete=models.PROTECT, related_name="schedule_dues"
    )
    due_key = models.UUIDField()
    position = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    due_on = models.DateField()

    class Meta:
        ordering = ["due_on", "position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_due_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "schedule_revision", "position"],
                name="receivables_due_revision_position_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "schedule_revision", "due_key"],
                name="receivables_due_revision_key_uq",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1), name="receivables_due_position_positive"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="receivables_due_amount_positive"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "obligation", "due_on"],
                name="recv_due_obligation_date_idx",
            )
        ]


class ReceivedPayment(TenantModel):
    class Method(models.TextChoices):
        CASH = "cash", "Efectivo"
        BANK_TRANSFER = "bank_transfer", "Transferencia bancaria"
        CARD_EXTERNAL = "card_external", "Tarjeta procesada externamente"
        CHECK = "check", "Cheque"
        OTHER = "other", "Otro medio externo"
        LEGACY_UNSPECIFIED = "legacy_unspecified", "Medio histórico no especificado"

    class Provenance(models.TextChoices):
        MANUAL = "manual", "Registro manual"
        CONFIRMATION_DEPOSIT = "confirmation_deposit", "Anticipo de confirmación"
        LEGACY_5_1_CONFIRMATION = "legacy_5_1_confirmation", "Confirmación histórica 5.1"

    class EvidenceLevel(models.TextChoices):
        INTERNAL_REPORT = "internal_report", "Declaración interna"
        ATTACHED_SUPPORT = "attached_support", "Comprobante adjunto"

    root_reservation_id = models.UUIDField(null=True, blank=True)
    event_request_id = models.UUIDField(null=True, blank=True)
    counterparty_person_id = models.UUIDField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    reported_at = models.DateTimeField()
    method = models.CharField(max_length=32, choices=Method.choices)
    reference = models.CharField(max_length=300, blank=True)
    normalized_reference = models.CharField(max_length=300, blank=True)
    observation = models.CharField(max_length=1000, blank=True)
    provenance = models.CharField(max_length=32, choices=Provenance.choices)
    evidence_level = models.CharField(max_length=32, choices=EvidenceLevel.choices)
    confirmation_source_id = models.UUIDField(null=True, blank=True)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="recorded_received_payments",
        db_index=False,
    )
    possible_duplicate = models.BooleanField(default=False)
    duplicate_review_note = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_payment_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "confirmation_source_id"],
                condition=Q(confirmation_source_id__isnull=False),
                name="receivables_payment_confirmation_source_uq",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="receivables_payment_amount_positive"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "counterparty_person_id", "reported_at"],
                name="recv_payment_person_date_idx",
            ),
            models.Index(
                fields=["organization", "root_reservation_id"],
                name="receivables_payment_root_idx",
            ),
        ]


class PaymentApplication(TenantModel):
    payment = models.ForeignKey(
        ReceivedPayment, on_delete=models.PROTECT, related_name="applications"
    )
    obligation = models.ForeignKey(
        ReceivableObligation, on_delete=models.PROTECT, related_name="payment_applications"
    )
    due_key = models.UUIDField(null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    applied_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="receivable_payment_applications",
        db_index=False,
    )
    applied_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_application_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="receivables_application_amount_positive"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "payment", "created_at"],
                name="recv_application_payment_idx",
            ),
            models.Index(
                fields=["organization", "obligation", "created_at"],
                name="recv_app_obligation_idx",
            ),
        ]


class ReceivableAdjustment(TenantModel):
    class Direction(models.TextChoices):
        INCREASE = "increase", "Aumenta la obligación"
        DECREASE = "decrease", "Disminuye la obligación"

    obligation = models.ForeignKey(
        ReceivableObligation, on_delete=models.PROTECT, related_name="adjustments"
    )
    direction = models.CharField(max_length=12, choices=Direction.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    reason = models.CharField(max_length=500)
    correlation_reference = models.CharField(max_length=300, blank=True)
    evidence_reference = models.CharField(max_length=300, blank=True)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="receivable_adjustments",
        db_index=False,
    )
    occurred_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_adjustment_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="receivables_adjustment_amount_positive"
            ),
        ]


class RefundRecord(TenantModel):
    payment = models.ForeignKey(ReceivedPayment, on_delete=models.PROTECT, related_name="refunds")
    obligation = models.ForeignKey(
        ReceivableObligation,
        on_delete=models.PROTECT,
        related_name="refunds",
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    refunded_at = models.DateTimeField()
    method = models.CharField(max_length=32, choices=ReceivedPayment.Method.choices)
    reference = models.CharField(max_length=300, blank=True)
    reason = models.CharField(max_length=500)
    evidence_reference = models.CharField(max_length=300, blank=True)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="recorded_refunds",
        db_index=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_refund_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="receivables_refund_amount_positive"
            ),
        ]


class RefundApplication(TenantModel):
    refund = models.ForeignKey(RefundRecord, on_delete=models.PROTECT, related_name="allocations")
    payment_application = models.ForeignKey(
        PaymentApplication, on_delete=models.PROTECT, related_name="refund_allocations"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_refund_application_org_id_uq"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="receivables_refund_application_amount_positive"
            ),
        ]


class MovementReversal(TenantModel):
    class TargetKind(models.TextChoices):
        PAYMENT = "payment", "Pago"
        APPLICATION = "application", "Aplicación"
        ADJUSTMENT = "adjustment", "Ajuste"
        REFUND = "refund", "Devolución"

    target_kind = models.CharField(max_length=16, choices=TargetKind.choices)
    target_id = models.UUIDField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    reason = models.CharField(max_length=500)
    reversed_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="receivable_movement_reversals",
        db_index=False,
    )
    reversed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_reversal_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "target_kind", "target_id"],
                name="receivables_reversal_target_uq",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="receivables_reversal_amount_positive"
            ),
        ]


class ReceiptSequence(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, db_index=False
    )
    year = models.PositiveIntegerField()
    next_value = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "year"], name="receivables_receipt_sequence_org_year_uq"
            ),
            models.CheckConstraint(
                condition=Q(next_value__gte=1), name="receivables_receipt_sequence_positive"
            ),
        ]


class Receipt(TenantModel):
    payment = models.ForeignKey(ReceivedPayment, on_delete=models.PROTECT, related_name="receipts")
    obligation = models.ForeignKey(
        ReceivableObligation,
        on_delete=models.PROTECT,
        related_name="receipts",
        null=True,
        blank=True,
    )
    year = models.PositiveIntegerField()
    sequence = models.PositiveIntegerField()
    visible_number = models.CharField(max_length=40)
    snapshot = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    issued_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="issued_receivable_receipts",
        db_index=False,
    )
    issued_at = models.DateTimeField()
    document_artifact_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_receipt_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "year", "sequence"],
                name="receivables_receipt_org_year_sequence_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "visible_number"],
                name="receivables_receipt_org_visible_uq",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1), name="receivables_receipt_number_positive"
            ),
        ]


class FinancialCommand(TenantModel):
    command_type = models.CharField(max_length=48)
    idempotency_key = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    result_type = models.CharField(max_length=48)
    result_reference = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_command_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "command_type", "idempotency_key"],
                name="receivables_command_idempotency_uq",
            ),
        ]


class FinancialEvent(TenantModel):
    kind = models.CharField(max_length=48)
    aggregate_type = models.CharField(max_length=48)
    aggregate_id = models.UUIDField()
    actor_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="receivable_financial_events",
        null=True,
        blank=True,
        db_index=False,
    )
    payload = models.JSONField(default=dict)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["occurred_at", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_event_org_id_uq"
            )
        ]


class LegacyEvidenceReview(TenantModel):
    root_reservation_id = models.UUIDField()
    confirmation_source_id = models.UUIDField()
    classification = models.CharField(max_length=48)
    reason = models.CharField(max_length=500)
    source_snapshot = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_legacy_review_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "confirmation_source_id"],
                name="receivables_legacy_review_source_uq",
            ),
        ]


class FinancialEvidenceLink(TenantModel):
    owner_type = models.CharField(max_length=32)
    owner_id = models.UUIDField()
    document_file_id = models.UUIDField()
    evidence_purpose = models.CharField(max_length=48)
    linked_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="receivable_financial_evidence_links",
        db_index=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="receivables_evidence_link_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "owner_type", "owner_id", "document_file_id"],
                name="receivables_evidence_link_owner_file_uq",
            ),
        ]
