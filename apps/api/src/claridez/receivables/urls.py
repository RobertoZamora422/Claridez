from django.urls import path

from .views import (
    AdjustmentsView,
    AgingView,
    ApplicationsView,
    CapabilitiesView,
    CommercialSummaryView,
    ObligationView,
    PaymentEvidenceDownloadView,
    PaymentEvidenceView,
    PaymentsView,
    PaymentView,
    PortfolioView,
    ReceiptPdfView,
    ReceiptsView,
    ReceiptView,
    RefundsView,
    ReversalView,
    ScheduleView,
    StatementView,
)

app_name = "receivables"
PREFIX = "<uuid:organization_id>/receivables/"

urlpatterns = [
    path(f"{PREFIX}capabilities/", CapabilitiesView.as_view(), name="capabilities"),
    path(f"{PREFIX}portfolio/", PortfolioView.as_view(), name="portfolio"),
    path(f"{PREFIX}aging/", AgingView.as_view(), name="aging"),
    path(
        f"{PREFIX}roots/<uuid:root_id>/summary/",
        CommercialSummaryView.as_view(),
        name="commercial-summary",
    ),
    path(
        f"{PREFIX}obligations/<uuid:obligation_id>/",
        ObligationView.as_view(),
        name="obligation",
    ),
    path(
        f"{PREFIX}obligations/<uuid:obligation_id>/schedule/",
        ScheduleView.as_view(),
        name="schedule",
    ),
    path(
        f"{PREFIX}obligations/<uuid:obligation_id>/statement/",
        StatementView.as_view(),
        name="statement",
    ),
    path(
        f"{PREFIX}obligations/<uuid:obligation_id>/movements/",
        StatementView.as_view(),
        name="movements",
    ),
    path(
        f"{PREFIX}obligations/<uuid:obligation_id>/adjustments/",
        AdjustmentsView.as_view(),
        name="adjustments",
    ),
    path(f"{PREFIX}payments/", PaymentsView.as_view(), name="payments"),
    path(f"{PREFIX}payments/<uuid:payment_id>/", PaymentView.as_view(), name="payment"),
    path(
        f"{PREFIX}payments/<uuid:payment_id>/evidence/",
        PaymentEvidenceView.as_view(),
        name="payment-evidence",
    ),
    path(
        f"{PREFIX}payments/<uuid:payment_id>/evidence/<uuid:evidence_id>/download/",
        PaymentEvidenceDownloadView.as_view(),
        name="payment-evidence-download",
    ),
    path(
        f"{PREFIX}payments/<uuid:payment_id>/applications/",
        ApplicationsView.as_view(),
        name="applications",
    ),
    path(
        f"{PREFIX}payments/<uuid:payment_id>/refunds/",
        RefundsView.as_view(),
        name="refunds",
    ),
    path(
        f"{PREFIX}payments/<uuid:payment_id>/receipts/",
        ReceiptsView.as_view(),
        name="receipt-issue",
    ),
    path(
        f"{PREFIX}movements/<str:target_kind>/<uuid:target_id>/reverse/",
        ReversalView.as_view(),
        name="movement-reverse",
    ),
    path(f"{PREFIX}receipts/<uuid:receipt_id>/", ReceiptView.as_view(), name="receipt"),
    path(
        f"{PREFIX}receipts/<uuid:receipt_id>/pdf/",
        ReceiptPdfView.as_view(),
        name="receipt-pdf",
    ),
]
