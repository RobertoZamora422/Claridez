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


class FinanceCategory(TenantModel):
    class Kind(models.TextChoices):
        DIRECT_COST = "direct_cost", "Costo directo"
        VARIABLE_EXPENSE = "variable_expense", "Gasto variable"
        RECURRING_EXPENSE = "recurring_expense", "Gasto recurrente"

    kind = models.CharField(max_length=24, choices=Kind.choices)
    name = models.CharField(max_length=120)
    normalized_name = models.CharField(max_length=120)
    created_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_categories"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="finance_cat_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "kind", "normalized_name"],
                name="finance_cat_org_kind_name_uq",
            ),
        ]
        ordering = ["kind", "name", "id"]


class OperationalPeriod(TenantModel):
    starts_on = models.DateField()
    ends_on = models.DateField(help_text="Límite exclusivo del periodo.")
    label = models.CharField(max_length=80)
    currency = models.CharField(max_length=3)
    created_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_periods"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="finance_period_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "starts_on"], name="finance_period_org_start_uq"
            ),
            models.CheckConstraint(
                condition=Q(ends_on__gt=models.F("starts_on")), name="finance_period_range_ck"
            ),
        ]
        ordering = ["starts_on", "id"]


class PeriodCloseSnapshot(TenantModel):
    period = models.OneToOneField(
        OperationalPeriod, on_delete=models.PROTECT, related_name="close_snapshot"
    )
    snapshot = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    receivables_cutoff_registered_at = models.DateTimeField()
    receivables_source_count = models.PositiveIntegerField()
    receivables_source_sha256 = models.CharField(max_length=64)
    closed_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_closes"
    )
    closed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="finance_close_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "period"], name="finance_close_org_period_uq"
            ),
        ]


class DirectCostPlanRevision(TenantModel):
    root_reservation_id = models.UUIDField()
    venue_id = models.UUIDField()
    revision = models.PositiveIntegerField()
    currency = models.CharField(max_length=3)
    reason = models.CharField(max_length=500)
    published_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_cost_plans"
    )
    published_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="finance_plan_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "root_reservation_id", "revision"],
                name="finance_plan_org_root_rev_uq",
            ),
            models.CheckConstraint(condition=Q(revision__gte=1), name="finance_plan_revision_ck"),
        ]
        ordering = ["root_reservation_id", "revision", "id"]


class DirectCostPlanLine(TenantModel):
    plan_revision = models.ForeignKey(
        DirectCostPlanRevision, on_delete=models.PROTECT, related_name="lines"
    )
    category = models.ForeignKey(FinanceCategory, on_delete=models.PROTECT)
    position = models.PositiveIntegerField()
    description = models.CharField(max_length=300)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_planline_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "plan_revision", "position"],
                name="finance_planline_position_uq",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_planline_amount_ck"),
            models.CheckConstraint(
                condition=Q(position__gte=1), name="finance_planline_position_ck"
            ),
        ]
        ordering = ["position", "id"]


class OperationalCostEvidence(TenantModel):
    root_reservation_id = models.UUIDField()
    venue_id = models.UUIDField()
    category = models.ForeignKey(FinanceCategory, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    economic_date = models.DateField()
    description = models.CharField(max_length=500)
    evidence_reference = models.CharField(max_length=300)
    submitted_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_cost_evidence"
    )
    submitted_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_evidence_org_id_uq"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_evidence_amount_ck"),
        ]


class EvidenceDecision(TenantModel):
    class Decision(models.TextChoices):
        APPROVED = "approved", "Aprobada"
        REJECTED = "rejected", "Rechazada"

    evidence = models.OneToOneField(
        OperationalCostEvidence, on_delete=models.PROTECT, related_name="decision"
    )
    decision = models.CharField(max_length=12, choices=Decision.choices)
    reason = models.CharField(max_length=500)
    decided_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="finance_evidence_decisions",
    )
    decided_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_decision_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "evidence"], name="finance_decision_evidence_uq"
            ),
        ]


class ActualDirectCost(TenantModel):
    class Provenance(models.TextChoices):
        MANUAL = "manual", "Registro manual"
        OPERATIONS_EVIDENCE = "operations_evidence", "Evidencia de operaciones"

    root_reservation_id = models.UUIDField()
    venue_id = models.UUIDField()
    category = models.ForeignKey(FinanceCategory, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    economic_date = models.DateField()
    registration_period = models.ForeignKey(
        OperationalPeriod, on_delete=models.PROTECT, related_name="direct_costs"
    )
    provenance = models.CharField(max_length=24, choices=Provenance.choices)
    description = models.CharField(max_length=500)
    evidence_reference = models.CharField(max_length=300)
    source_evidence = models.OneToOneField(
        OperationalCostEvidence,
        on_delete=models.PROTECT,
        related_name="actual_cost",
        null=True,
        blank=True,
    )
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_direct_costs"
    )
    recorded_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="finance_cost_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "source_evidence"],
                condition=Q(source_evidence__isnull=False),
                name="finance_cost_evidence_uq",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_cost_amount_ck"),
        ]


class DirectCostCorrection(TenantModel):
    class Direction(models.TextChoices):
        INCREASE = "increase", "Aumenta"
        DECREASE = "decrease", "Disminuye"

    direct_cost = models.ForeignKey(
        ActualDirectCost, on_delete=models.PROTECT, related_name="corrections"
    )
    direction = models.CharField(max_length=12, choices=Direction.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    economic_date = models.DateField()
    registration_period = models.ForeignKey(
        OperationalPeriod, on_delete=models.PROTECT, related_name="direct_cost_corrections"
    )
    reason = models.CharField(max_length=500)
    evidence_reference = models.CharField(max_length=300)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="finance_cost_corrections",
    )
    recorded_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_costcorr_org_id_uq"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_costcorr_amount_ck"),
        ]


class RecurringExpenseRule(TenantModel):
    category = models.ForeignKey(FinanceCategory, on_delete=models.PROTECT)
    name = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    day_of_month = models.PositiveSmallIntegerField()
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    default_venue_id = models.UUIDField(null=True, blank=True)
    created_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_recurring_rules"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="finance_rule_org_id_uq"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_rule_amount_ck"),
            models.CheckConstraint(
                condition=Q(day_of_month__gte=1, day_of_month__lte=28),
                name="finance_rule_day_ck",
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=models.F("valid_from")),
                name="finance_rule_validity_ck",
            ),
        ]


class ExpenseOccurrence(TenantModel):
    class ExpenseType(models.TextChoices):
        VARIABLE = "variable", "Variable"
        RECURRING = "recurring", "Recurrente"

    class Provenance(models.TextChoices):
        MANUAL = "manual", "Manual"
        RECURRING = "recurring", "Regla recurrente"

    category = models.ForeignKey(FinanceCategory, on_delete=models.PROTECT)
    expense_type = models.CharField(max_length=12, choices=ExpenseType.choices)
    provenance = models.CharField(max_length=12, choices=Provenance.choices)
    recurring_rule = models.ForeignKey(
        RecurringExpenseRule,
        on_delete=models.PROTECT,
        related_name="occurrences",
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    economic_date = models.DateField()
    registration_period = models.ForeignKey(
        OperationalPeriod, on_delete=models.PROTECT, related_name="expense_occurrences"
    )
    description = models.CharField(max_length=500)
    evidence_reference = models.CharField(max_length=300)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_expenses"
    )
    recorded_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_expense_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "recurring_rule", "economic_date"],
                condition=Q(recurring_rule__isnull=False),
                name="finance_expense_rule_date_uq",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_expense_amount_ck"),
            models.CheckConstraint(
                condition=(
                    Q(provenance="manual", recurring_rule__isnull=True)
                    | Q(
                        provenance="recurring",
                        expense_type="recurring",
                        recurring_rule__isnull=False,
                    )
                ),
                name="finance_expense_provenance_ck",
            ),
        ]


class ExpenseAllocation(TenantModel):
    class Scope(models.TextChoices):
        BUSINESS = "business", "Negocio"
        VENUE = "venue", "Sede"
        EVENT = "event", "Evento"

    expense_occurrence = models.ForeignKey(
        ExpenseOccurrence, on_delete=models.PROTECT, related_name="allocations"
    )
    position = models.PositiveIntegerField()
    scope = models.CharField(max_length=12, choices=Scope.choices)
    root_reservation_id = models.UUIDField(null=True, blank=True)
    venue_id = models.UUIDField(null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="finance_alloc_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "expense_occurrence", "position"],
                name="finance_alloc_position_uq",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_alloc_amount_ck"),
            models.CheckConstraint(
                condition=(
                    Q(scope="business", root_reservation_id__isnull=True, venue_id__isnull=True)
                    | Q(scope="venue", root_reservation_id__isnull=True, venue_id__isnull=False)
                    | Q(scope="event", root_reservation_id__isnull=False, venue_id__isnull=False)
                ),
                name="finance_alloc_scope_ck",
            ),
        ]
        ordering = ["position", "id"]


class ExpenseOccurrenceCorrection(TenantModel):
    class Direction(models.TextChoices):
        INCREASE = "increase", "Aumenta"
        DECREASE = "decrease", "Disminuye"

    expense_occurrence = models.ForeignKey(
        ExpenseOccurrence, on_delete=models.PROTECT, related_name="corrections"
    )
    direction = models.CharField(max_length=12, choices=Direction.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    economic_date = models.DateField()
    registration_period = models.ForeignKey(
        OperationalPeriod, on_delete=models.PROTECT, related_name="expense_corrections"
    )
    scope = models.CharField(max_length=12, choices=ExpenseAllocation.Scope.choices)
    root_reservation_id = models.UUIDField(null=True, blank=True)
    venue_id = models.UUIDField(null=True, blank=True)
    reason = models.CharField(max_length=500)
    evidence_reference = models.CharField(max_length=300)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="finance_expense_corrections",
    )
    recorded_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_expcorr_org_id_uq"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_expcorr_amount_ck"),
            models.CheckConstraint(
                condition=(
                    Q(scope="business", root_reservation_id__isnull=True, venue_id__isnull=True)
                    | Q(scope="venue", root_reservation_id__isnull=True, venue_id__isnull=False)
                    | Q(scope="event", root_reservation_id__isnull=False, venue_id__isnull=False)
                ),
                name="finance_expcorr_scope_ck",
            ),
        ]


class OperatingBudgetRevision(TenantModel):
    period = models.ForeignKey(
        OperationalPeriod, on_delete=models.PROTECT, related_name="budget_revisions"
    )
    venue_id = models.UUIDField(null=True, blank=True)
    revision = models.PositiveIntegerField()
    currency = models.CharField(max_length=3)
    reason = models.CharField(max_length=500)
    published_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_budgets"
    )
    published_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="finance_budget_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "period", "venue_id", "revision"],
                name="finance_budget_scope_rev_uq",
                nulls_distinct=False,
            ),
            models.CheckConstraint(condition=Q(revision__gte=1), name="finance_budget_revision_ck"),
        ]


class OperatingBudgetLine(TenantModel):
    budget_revision = models.ForeignKey(
        OperatingBudgetRevision, on_delete=models.PROTECT, related_name="lines"
    )
    category = models.ForeignKey(FinanceCategory, on_delete=models.PROTECT)
    position = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_budgetline_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "budget_revision", "position"],
                name="finance_budgetline_position_uq",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_budgetline_amount_ck"),
        ]


class OperatingCashMovement(TenantModel):
    class Direction(models.TextChoices):
        OUTFLOW = "outflow", "Salida"
        RECOVERY = "recovery", "Recuperación"

    class SourceKind(models.TextChoices):
        DIRECT_COST = "direct_cost", "Costo directo"
        EXPENSE = "expense", "Gasto"

    direction = models.CharField(max_length=12, choices=Direction.choices)
    source_kind = models.CharField(max_length=16, choices=SourceKind.choices)
    source_id = models.UUIDField()
    original_outflow = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="recoveries",
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    economic_date = models.DateField()
    registration_period = models.ForeignKey(
        OperationalPeriod, on_delete=models.PROTECT, related_name="cash_movements"
    )
    reason = models.CharField(max_length=500)
    evidence_reference = models.CharField(max_length=300)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership", on_delete=models.PROTECT, related_name="finance_cash_movements"
    )
    recorded_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="finance_cash_org_id_uq"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_cash_amount_ck"),
            models.CheckConstraint(
                condition=(
                    Q(direction="outflow", original_outflow__isnull=True)
                    | Q(direction="recovery", original_outflow__isnull=False)
                ),
                name="finance_cash_direction_ck",
            ),
        ]


class CashMovementCorrection(TenantModel):
    class Direction(models.TextChoices):
        INCREASE = "increase", "Aumenta"
        DECREASE = "decrease", "Disminuye"

    cash_movement = models.ForeignKey(
        OperatingCashMovement, on_delete=models.PROTECT, related_name="corrections"
    )
    direction = models.CharField(max_length=12, choices=Direction.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    economic_date = models.DateField()
    registration_period = models.ForeignKey(
        OperationalPeriod, on_delete=models.PROTECT, related_name="cash_corrections"
    )
    reason = models.CharField(max_length=500)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="finance_cash_corrections",
    )
    recorded_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_cashcorr_org_id_uq"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_cashcorr_amount_ck"),
        ]


class RecognitionAdjustment(TenantModel):
    class Direction(models.TextChoices):
        INCREASE = "increase", "Aumenta"
        DECREASE = "decrease", "Disminuye"

    class ReasonCode(models.TextChoices):
        MEASUREMENT = "measurement_correction", "Corrección de medición"
        OMISSION = "omission_correction", "Corrección de omisión"
        DUPLICATE = "duplicate_correction", "Corrección de duplicidad"

    root_reservation_id = models.UUIDField()
    venue_id = models.UUIDField()
    direction = models.CharField(max_length=12, choices=Direction.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    economic_date = models.DateField()
    registration_period = models.ForeignKey(
        OperationalPeriod, on_delete=models.PROTECT, related_name="recognition_adjustments"
    )
    reason_code = models.CharField(max_length=32, choices=ReasonCode.choices)
    reason = models.CharField(max_length=500)
    evidence_reference = models.CharField(max_length=300)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="finance_recognition_adjustments",
    )
    recorded_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_recognition_org_id_uq"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_recognition_amount_ck"),
        ]


class RecognitionAdjustmentCorrection(TenantModel):
    class Direction(models.TextChoices):
        INCREASE = "increase", "Aumenta"
        DECREASE = "decrease", "Disminuye"

    recognition_adjustment = models.ForeignKey(
        RecognitionAdjustment, on_delete=models.PROTECT, related_name="corrections"
    )
    direction = models.CharField(max_length=12, choices=Direction.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    economic_date = models.DateField()
    registration_period = models.ForeignKey(
        OperationalPeriod, on_delete=models.PROTECT, related_name="recognition_corrections"
    )
    reason = models.CharField(max_length=500)
    recorded_by_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        related_name="finance_recognition_corrections",
    )
    recorded_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_reccorr_org_id_uq"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_reccorr_amount_ck"),
        ]


class FinanceCommand(TenantModel):
    command_type = models.CharField(max_length=48)
    idempotency_key = models.UUIDField()
    payload_sha256 = models.CharField(max_length=64)
    result_type = models.CharField(max_length=48)
    result_reference = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="finance_command_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "command_type", "idempotency_key"],
                name="finance_command_idempotency_uq",
            ),
        ]
