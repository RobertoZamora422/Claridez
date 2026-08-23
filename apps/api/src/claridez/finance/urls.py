from django.urls import path

from .views import (
    BudgetsView,
    CapabilitiesView,
    CashCorrectionView,
    CashMovementsView,
    CategoriesView,
    CostEvidenceView,
    CostPlansView,
    DirectCostCorrectionView,
    DirectCostsView,
    EvidenceContextView,
    EvidenceDecisionView,
    ExpenseCorrectionView,
    ExpensesView,
    ExportView,
    OverviewView,
    PeriodCloseView,
    PeriodsView,
    RecognitionAdjustmentsView,
    RecognitionCorrectionView,
    RecurringOccurrenceView,
    RecurringRulesView,
)

app_name = "finance"
PREFIX = "<uuid:organization_id>/finance/"

urlpatterns = [
    path(f"{PREFIX}capabilities/", CapabilitiesView.as_view(), name="capabilities"),
    path(f"{PREFIX}overview/", OverviewView.as_view(), name="overview"),
    path(f"{PREFIX}evidence-context/", EvidenceContextView.as_view(), name="evidence-context"),
    path(f"{PREFIX}categories/", CategoriesView.as_view(), name="categories"),
    path(f"{PREFIX}periods/", PeriodsView.as_view(), name="periods"),
    path(
        f"{PREFIX}periods/<uuid:period_id>/close/", PeriodCloseView.as_view(), name="period-close"
    ),
    path(f"{PREFIX}direct-cost-plans/", CostPlansView.as_view(), name="cost-plans"),
    path(f"{PREFIX}cost-evidence/", CostEvidenceView.as_view(), name="cost-evidence"),
    path(
        f"{PREFIX}cost-evidence/<uuid:evidence_id>/decision/",
        EvidenceDecisionView.as_view(),
        name="evidence-decision",
    ),
    path(f"{PREFIX}direct-costs/", DirectCostsView.as_view(), name="direct-costs"),
    path(
        f"{PREFIX}direct-costs/<uuid:direct_cost_id>/corrections/",
        DirectCostCorrectionView.as_view(),
        name="direct-cost-corrections",
    ),
    path(f"{PREFIX}recurring-rules/", RecurringRulesView.as_view(), name="recurring-rules"),
    path(
        f"{PREFIX}recurring-rules/<uuid:rule_id>/occurrences/",
        RecurringOccurrenceView.as_view(),
        name="recurring-occurrences",
    ),
    path(f"{PREFIX}expenses/", ExpensesView.as_view(), name="expenses"),
    path(
        f"{PREFIX}expenses/<uuid:expense_id>/corrections/",
        ExpenseCorrectionView.as_view(),
        name="expense-corrections",
    ),
    path(f"{PREFIX}budgets/", BudgetsView.as_view(), name="budgets"),
    path(f"{PREFIX}cash-movements/", CashMovementsView.as_view(), name="cash-movements"),
    path(
        f"{PREFIX}cash-movements/<uuid:cash_movement_id>/corrections/",
        CashCorrectionView.as_view(),
        name="cash-corrections",
    ),
    path(
        f"{PREFIX}recognition-adjustments/",
        RecognitionAdjustmentsView.as_view(),
        name="recognition-adjustments",
    ),
    path(
        f"{PREFIX}recognition-adjustments/<uuid:recognition_adjustment_id>/corrections/",
        RecognitionCorrectionView.as_view(),
        name="recognition-corrections",
    ),
    path(f"{PREFIX}export/", ExportView.as_view(), name="export"),
]
