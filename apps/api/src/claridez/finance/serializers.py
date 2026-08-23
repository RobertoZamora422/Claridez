from rest_framework import serializers

from .models import (
    DirectCostCorrection,
    EvidenceDecision,
    ExpenseAllocation,
    ExpenseOccurrence,
    FinanceCategory,
    OperatingCashMovement,
    RecognitionAdjustment,
)


class FinanceErrorDetailSerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.CharField()
    message = serializers.CharField()


class FinanceErrorSerializer(serializers.Serializer[dict[str, object]]):
    error = FinanceErrorDetailSerializer()


class FinanceCapabilitiesResponseSerializer(serializers.Serializer[dict[str, object]]):
    capabilities = serializers.ListField(child=serializers.CharField())


class EntityResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()


class CategoryCreateSerializer(serializers.Serializer[dict[str, object]]):
    kind = serializers.ChoiceField(choices=FinanceCategory.Kind.choices)
    name = serializers.CharField(max_length=120)


class PeriodCreateSerializer(serializers.Serializer[dict[str, object]]):
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    label = serializers.CharField(max_length=80)  # type: ignore[assignment]


class DirectCostPlanLineSerializer(serializers.Serializer[dict[str, object]]):
    category_id = serializers.UUIDField()
    description = serializers.CharField(max_length=300)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class DirectCostPlanCreateSerializer(serializers.Serializer[dict[str, object]]):
    root_reservation_id = serializers.UUIDField()
    venue_id = serializers.UUIDField()
    currency = serializers.CharField(min_length=3, max_length=3)
    reason = serializers.CharField(max_length=500)
    lines = DirectCostPlanLineSerializer(many=True, allow_empty=False)


class CostEvidenceCreateSerializer(serializers.Serializer[dict[str, object]]):
    root_reservation_id = serializers.UUIDField()
    venue_id = serializers.UUIDField()
    category_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    economic_date = serializers.DateField()
    description = serializers.CharField(max_length=500)
    evidence_reference = serializers.CharField(max_length=300)


class EvidenceDecisionCreateSerializer(serializers.Serializer[dict[str, object]]):
    decision = serializers.ChoiceField(choices=EvidenceDecision.Decision.choices)
    reason = serializers.CharField(max_length=500)


class DirectCostCreateSerializer(CostEvidenceCreateSerializer):
    pass


class CorrectionCreateSerializer(serializers.Serializer[dict[str, object]]):
    direction = serializers.ChoiceField(choices=DirectCostCorrection.Direction.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    economic_date = serializers.DateField()
    reason = serializers.CharField(max_length=500)
    evidence_reference = serializers.CharField(max_length=300, allow_blank=True, required=False)


class RecurringRuleCreateSerializer(serializers.Serializer[dict[str, object]]):
    category_id = serializers.UUIDField()
    name = serializers.CharField(max_length=160)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    day_of_month = serializers.IntegerField(min_value=1, max_value=28)
    valid_from = serializers.DateField()
    valid_until = serializers.DateField(required=False, allow_null=True)
    default_venue_id = serializers.UUIDField(required=False, allow_null=True)


class ExpenseAllocationSerializer(serializers.Serializer[dict[str, object]]):
    scope = serializers.ChoiceField(choices=ExpenseAllocation.Scope.choices)
    root_reservation_id = serializers.UUIDField(required=False, allow_null=True)
    venue_id = serializers.UUIDField(required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class ExpenseCreateSerializer(serializers.Serializer[dict[str, object]]):
    category_id = serializers.UUIDField()
    expense_type = serializers.ChoiceField(choices=ExpenseOccurrence.ExpenseType.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    economic_date = serializers.DateField()
    description = serializers.CharField(max_length=500)
    evidence_reference = serializers.CharField(max_length=300)
    allocations = ExpenseAllocationSerializer(many=True, allow_empty=False)


class RecurringOccurrenceCreateSerializer(serializers.Serializer[dict[str, object]]):
    economic_date = serializers.DateField()
    evidence_reference = serializers.CharField(max_length=300)


class ExpenseCorrectionCreateSerializer(CorrectionCreateSerializer):
    scope = serializers.ChoiceField(choices=ExpenseAllocation.Scope.choices)
    root_reservation_id = serializers.UUIDField(required=False, allow_null=True)
    venue_id = serializers.UUIDField(required=False, allow_null=True)


class BudgetLineSerializer(serializers.Serializer[dict[str, object]]):
    category_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class BudgetCreateSerializer(serializers.Serializer[dict[str, object]]):
    period_id = serializers.UUIDField()
    venue_id = serializers.UUIDField(required=False, allow_null=True)
    currency = serializers.CharField(min_length=3, max_length=3)
    reason = serializers.CharField(max_length=500)
    lines = BudgetLineSerializer(many=True, allow_empty=False)


class CashMovementCreateSerializer(serializers.Serializer[dict[str, object]]):
    direction = serializers.ChoiceField(choices=OperatingCashMovement.Direction.choices)
    source_kind = serializers.ChoiceField(choices=OperatingCashMovement.SourceKind.choices)
    source_id = serializers.UUIDField()
    original_outflow_id = serializers.UUIDField(required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    expense_attributions = ExpenseAllocationSerializer(many=True, required=False, default=list)
    economic_date = serializers.DateField()
    reason = serializers.CharField(max_length=500)
    evidence_reference = serializers.CharField(max_length=300)


class CashCorrectionCreateSerializer(serializers.Serializer[dict[str, object]]):
    direction = serializers.ChoiceField(choices=DirectCostCorrection.Direction.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    expense_attributions = ExpenseAllocationSerializer(many=True, required=False, default=list)
    economic_date = serializers.DateField()
    reason = serializers.CharField(max_length=500)


class RecognitionAdjustmentCreateSerializer(serializers.Serializer[dict[str, object]]):
    root_reservation_id = serializers.UUIDField()
    direction = serializers.ChoiceField(choices=RecognitionAdjustment.Direction.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)
    economic_date = serializers.DateField()
    reason_code = serializers.ChoiceField(choices=RecognitionAdjustment.ReasonCode.choices)
    reason = serializers.CharField(max_length=500)
    evidence_reference = serializers.CharField(max_length=300)


class RecognitionCorrectionCreateSerializer(serializers.Serializer[dict[str, object]]):
    direction = serializers.ChoiceField(choices=DirectCostCorrection.Direction.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    economic_date = serializers.DateField()
    reason = serializers.CharField(max_length=500)


class FinanceOverviewResponseSerializer(serializers.Serializer[dict[str, object]]):
    organization_id = serializers.UUIDField()
    currency = serializers.CharField()
    timezone = serializers.CharField()
    period = serializers.JSONField(allow_null=True)
    filters = serializers.JSONField()
    ordinary = serializers.JSONField()
    prior_period_adjustments = serializers.JSONField()
    presented = serializers.JSONField()
    events = serializers.ListField(child=serializers.JSONField())
    categories = serializers.ListField(child=serializers.JSONField())
    periods = serializers.ListField(child=serializers.JSONField())
    direct_cost_plans = serializers.ListField(child=serializers.JSONField())
    direct_costs = serializers.ListField(child=serializers.JSONField())
    cost_evidence = serializers.ListField(child=serializers.JSONField())
    expenses = serializers.ListField(child=serializers.JSONField())
    recurring_rules = serializers.ListField(child=serializers.JSONField())
    budgets = serializers.ListField(child=serializers.JSONField())
    cash_movements = serializers.ListField(child=serializers.JSONField())
    recognition_adjustments = serializers.ListField(child=serializers.JSONField())
    p10_source_references = serializers.ListField(child=serializers.JSONField())


class EvidenceContextResponseSerializer(serializers.Serializer[dict[str, object]]):
    categories = serializers.ListField(child=serializers.JSONField())
    events = serializers.ListField(child=serializers.JSONField())
