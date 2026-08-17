from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import (
    CollectionScheduleRevision,
    MovementReversal,
    ReceivableAdjustment,
    ReceivedPayment,
)


class ReceivablesErrorDetailSerializer(serializers.Serializer[dict[str, str]]):
    code = serializers.CharField()
    message = serializers.CharField()


class ReceivablesErrorSerializer(serializers.Serializer[dict[str, object]]):
    error = ReceivablesErrorDetailSerializer()


class ReceivablesResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Fallback para proyecciones excepcionalmente dinámicas; no envuelve la respuesta."""


class DueProjectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField(required=False)
    due_key = serializers.UUIDField(allow_null=True)
    position = serializers.IntegerField(required=False)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3, required=False)
    due_on = serializers.DateField(allow_null=True)
    revision = serializers.IntegerField(required=False)


class ObligationProjectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    root_reservation_id = serializers.UUIDField()
    current_reservation_id = serializers.UUIDField()
    event_request_id = serializers.UUIDField()
    quotation_version_id = serializers.UUIDField(required=False)
    quotation_visible_number = serializers.CharField(required=False)
    quotation_version = serializers.IntegerField(required=False)
    counterparty_person_id = serializers.UUIDField()
    counterparty_name = serializers.CharField()
    currency = serializers.CharField(min_length=3, max_length=3)
    subtotal = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)
    discount_total = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)
    original_total = serializers.DecimalField(max_digits=18, decimal_places=2)
    adjusted_total = serializers.DecimalField(max_digits=18, decimal_places=2)
    applied_total = serializers.DecimalField(max_digits=18, decimal_places=2)
    balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    derived_status = serializers.ChoiceField(choices=["open", "partial", "satisfied"])
    reservation_status = serializers.CharField()
    financial_review_required = serializers.BooleanField()
    confirmed_at = serializers.DateTimeField(required=False)
    schedule_configured = serializers.BooleanField(required=False)
    schedule = DueProjectionSerializer(many=True, required=False)


class CurrencyGroupSerializer(serializers.Serializer[dict[str, object]]):
    currency = serializers.CharField(min_length=3, max_length=3)
    original_total = serializers.DecimalField(max_digits=18, decimal_places=2)
    balance = serializers.DecimalField(max_digits=18, decimal_places=2)


class PortfolioResponseSerializer(serializers.Serializer[dict[str, object]]):
    currency_groups = CurrencyGroupSerializer(many=True)
    obligations = ObligationProjectionSerializer(many=True)


class AgingEntrySerializer(serializers.Serializer[dict[str, object]]):
    obligation_id = serializers.UUIDField()
    root_reservation_id = serializers.UUIDField()
    counterparty_person_id = serializers.UUIDField()
    counterparty_name = serializers.CharField()
    currency = serializers.CharField(min_length=3, max_length=3)
    due_key = serializers.UUIDField(allow_null=True)
    due_on = serializers.DateField(allow_null=True)
    open_amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    days_overdue = serializers.IntegerField(allow_null=True)
    bucket = serializers.ChoiceField(
        choices=["current", "1_30", "31_60", "61_90", "over_90", "unscheduled"]
    )


class AgingResponseSerializer(serializers.Serializer[dict[str, object]]):
    as_of = serializers.DateField()
    buckets = serializers.JSONField(help_text="Totales por bucket y moneda; importes decimal.")
    entries = AgingEntrySerializer(many=True)


class ApplicationProjectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    payment_id = serializers.UUIDField()
    obligation_id = serializers.UUIDField()
    due_key = serializers.UUIDField(allow_null=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    applied_at = serializers.DateTimeField()
    restored_by_refunds = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)
    reversed = serializers.BooleanField(required=False)
    reversal_id = serializers.UUIDField(allow_null=True, required=False)


class PaymentProjectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    counterparty_person_id = serializers.UUIDField()
    root_reservation_id = serializers.UUIDField(allow_null=True)
    event_request_id = serializers.UUIDField(allow_null=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    unapplied_amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    reported_at = serializers.DateTimeField()
    method = serializers.ChoiceField(choices=ReceivedPayment.Method.choices)
    reference = serializers.CharField(allow_blank=True)
    observation = serializers.CharField(allow_blank=True)
    provenance = serializers.ChoiceField(choices=ReceivedPayment.Provenance.choices)
    evidence_level = serializers.ChoiceField(choices=ReceivedPayment.EvidenceLevel.choices)
    possible_duplicate = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    applications = ApplicationProjectionSerializer(many=True, required=False)


class PaymentsResponseSerializer(serializers.Serializer[dict[str, object]]):
    payments = PaymentProjectionSerializer(many=True)


class ReceivablesCapabilitiesResponseSerializer(serializers.Serializer[dict[str, object]]):
    capabilities = serializers.ListField(child=serializers.CharField())


class ScheduleCommandResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    obligation_id = serializers.UUIDField()
    revision = serializers.IntegerField()


class AdjustmentProjectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    obligation_id = serializers.UUIDField()
    direction = serializers.ChoiceField(choices=ReceivableAdjustment.Direction.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    reason = serializers.CharField()
    occurred_at = serializers.DateTimeField()


class ReversalProjectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    target_kind = serializers.ChoiceField(choices=MovementReversal.TargetKind.choices)
    target_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    reason = serializers.CharField()
    reversed_at = serializers.DateTimeField()


class RefundProjectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    payment_id = serializers.UUIDField()
    obligation_id = serializers.UUIDField(allow_null=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    refunded_at = serializers.DateTimeField()
    reason = serializers.CharField()


class ReceiptProjectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    visible_number = serializers.CharField()
    year = serializers.IntegerField()
    sequence = serializers.IntegerField()
    payment_id = serializers.UUIDField()
    obligation_id = serializers.UUIDField(allow_null=True)
    snapshot = serializers.JSONField(help_text="Snapshot inmutable al emitir el recibo.")
    snapshot_sha256 = serializers.CharField()
    issued_at = serializers.DateTimeField()
    document_artifact_id = serializers.UUIDField(allow_null=True)
    label = serializers.CharField()  # type: ignore[assignment]


class EvidenceProjectionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    display_name = serializers.CharField()
    media_type = serializers.CharField(required=False)
    sha256 = serializers.CharField()
    size_bytes = serializers.IntegerField()
    state = serializers.CharField()
    meaning = serializers.CharField(required=False)


class EvidenceListResponseSerializer(serializers.Serializer[dict[str, object]]):
    evidence = EvidenceProjectionSerializer(many=True)


class CommercialSummaryResponseSerializer(serializers.Serializer[dict[str, object]]):
    root_reservation_id = serializers.UUIDField()
    event_request_id = serializers.UUIDField()
    currency = serializers.CharField(min_length=3, max_length=3)
    original_total = serializers.DecimalField(max_digits=18, decimal_places=2)
    applied_total = serializers.DecimalField(max_digits=18, decimal_places=2)
    balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    derived_status = serializers.ChoiceField(choices=["open", "partial", "satisfied"])


class StatementResponseSerializer(ObligationProjectionSerializer):
    payments = PaymentProjectionSerializer(many=True)
    applications = ApplicationProjectionSerializer(many=True)
    adjustments = AdjustmentProjectionSerializer(many=True)
    refunds = RefundProjectionSerializer(many=True)
    reversals = ReversalProjectionSerializer(many=True)
    receipts = ReceiptProjectionSerializer(many=True)


class FinancialEvidenceUploadSerializer(serializers.Serializer[dict[str, object]]):
    file = serializers.FileField()


class DueInputSerializer(serializers.Serializer[dict[str, object]]):
    due_key = serializers.UUIDField(required=False)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    due_on = serializers.DateField()


class ScheduleRevisionSerializer(serializers.Serializer[dict[str, object]]):
    dues = DueInputSerializer(many=True, allow_empty=True)
    provenance = serializers.ChoiceField(choices=CollectionScheduleRevision.Provenance.choices)
    reason = serializers.CharField(max_length=500)


class PaymentCreateSerializer(serializers.Serializer[dict[str, object]]):
    counterparty_person_id = serializers.UUIDField()
    root_reservation_id = serializers.UUIDField(required=False, allow_null=True)
    event_request_id = serializers.UUIDField(required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    reported_at = serializers.DateTimeField()
    method = serializers.ChoiceField(choices=ReceivedPayment.Method.choices)
    reference = serializers.CharField(max_length=300, required=False, allow_blank=True)
    observation = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    evidence_level = serializers.ChoiceField(
        choices=ReceivedPayment.EvidenceLevel.choices,
        required=False,
        default=ReceivedPayment.EvidenceLevel.INTERNAL_REPORT,
    )
    duplicate_review_note = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ApplicationCreateSerializer(serializers.Serializer[dict[str, object]]):
    obligation_id = serializers.UUIDField()
    due_key = serializers.UUIDField(required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class AdjustmentCreateSerializer(serializers.Serializer[dict[str, object]]):
    direction = serializers.ChoiceField(choices=ReceivableAdjustment.Direction.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    reason = serializers.CharField(max_length=500)
    correlation_reference = serializers.CharField(max_length=300, required=False, allow_blank=True)
    evidence_reference = serializers.CharField(max_length=300, required=False, allow_blank=True)


class ReversalCreateSerializer(serializers.Serializer[dict[str, str]]):
    reason = serializers.CharField(max_length=500)


class RefundAllocationSerializer(serializers.Serializer[dict[str, object]]):
    application_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class RefundCreateSerializer(serializers.Serializer[dict[str, object]]):
    obligation_id = serializers.UUIDField(required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    refunded_at = serializers.DateTimeField()
    method = serializers.ChoiceField(choices=ReceivedPayment.Method.choices)
    reference = serializers.CharField(max_length=300, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=500)
    evidence_reference = serializers.CharField(max_length=300, required=False, allow_blank=True)
    allocations = RefundAllocationSerializer(many=True, required=False, default=list)


class MovementKindSerializer(serializers.Serializer[dict[str, str]]):
    target_kind = serializers.ChoiceField(choices=MovementReversal.TargetKind.choices)


def decimal_value(data: dict[str, object], field: str) -> Decimal:
    return data[field]  # type: ignore[return-value]
