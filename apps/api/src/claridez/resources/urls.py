from django.urls import path

from .views import (
    AssignmentActionView,
    AssignmentView,
    CapabilitiesView,
    ContextualAvailabilityView,
    ConversionCreateView,
    FinancialMaterializationView,
    LocationCreateView,
    MovementView,
    OverviewView,
    PurchaseCreateView,
    ReceiptLineView,
    RequirementView,
    ResourceCreateView,
    ResourceStatusView,
    SupplierContactInactivateView,
    SupplierContactView,
    SupplierCreateView,
    SupplierOfferingStatusView,
    SupplierOfferingView,
    SupplierStatusView,
    SupplierTermView,
    UnavailabilityCloseView,
    UnavailabilityView,
    UnitCreateView,
)

app_name = "resources"
PREFIX = "<uuid:organization_id>/resources/"

urlpatterns = [
    path(f"{PREFIX}capabilities/", CapabilitiesView.as_view(), name="capabilities"),
    path(f"{PREFIX}overview/", OverviewView.as_view(), name="overview"),
    path(
        f"{PREFIX}event-requests/<uuid:event_request_id>/items/<uuid:resource_id>/availability/",
        ContextualAvailabilityView.as_view(),
        name="contextual-availability",
    ),
    path(f"{PREFIX}units/create/", UnitCreateView.as_view(), name="unit-create"),
    path(
        f"{PREFIX}unit-conversions/create/",
        ConversionCreateView.as_view(),
        name="conversion-create",
    ),
    path(f"{PREFIX}suppliers/create/", SupplierCreateView.as_view(), name="supplier-create"),
    path(
        f"{PREFIX}suppliers/<uuid:supplier_id>/status/",
        SupplierStatusView.as_view(),
        name="supplier-status",
    ),
    path(
        f"{PREFIX}suppliers/<uuid:supplier_id>/contacts/link/",
        SupplierContactView.as_view(),
        name="supplier-contact",
    ),
    path(
        f"{PREFIX}contacts/<uuid:contact_id>/inactivate/",
        SupplierContactInactivateView.as_view(),
        name="supplier-contact-inactivate",
    ),
    path(
        f"{PREFIX}suppliers/<uuid:supplier_id>/terms/add/",
        SupplierTermView.as_view(),
        name="supplier-term",
    ),
    path(
        f"{PREFIX}suppliers/<uuid:supplier_id>/offerings/add/",
        SupplierOfferingView.as_view(),
        name="supplier-offering",
    ),
    path(
        f"{PREFIX}offerings/<uuid:offering_id>/status/",
        SupplierOfferingStatusView.as_view(),
        name="supplier-offering-status",
    ),
    path(f"{PREFIX}items/create/", ResourceCreateView.as_view(), name="resource-create"),
    path(
        f"{PREFIX}items/<uuid:resource_id>/status/",
        ResourceStatusView.as_view(),
        name="resource-status",
    ),
    path(f"{PREFIX}locations/create/", LocationCreateView.as_view(), name="location-create"),
    path(f"{PREFIX}purchases/create/", PurchaseCreateView.as_view(), name="purchase-create"),
    path(f"{PREFIX}receipt-lines/confirm/", ReceiptLineView.as_view(), name="receipt-line"),
    path(
        f"{PREFIX}receipt-lines/<uuid:receipt_line_id>/materialize-finance/",
        FinancialMaterializationView.as_view(),
        name="receipt-finance",
    ),
    path(f"{PREFIX}movements/record/", MovementView.as_view(), name="movement"),
    path(f"{PREFIX}requirements/create/", RequirementView.as_view(), name="requirement"),
    path(f"{PREFIX}assignments/reserve/", AssignmentView.as_view(), name="assignment"),
    path(
        f"{PREFIX}assignments/<uuid:assignment_id>/execute/",
        AssignmentActionView.as_view(),
        name="assignment-action",
    ),
    path(f"{PREFIX}unavailability/record/", UnavailabilityView.as_view(), name="unavailability"),
    path(
        f"{PREFIX}unavailability/<uuid:unavailability_id>/close/",
        UnavailabilityCloseView.as_view(),
        name="unavailability-close",
    ),
]
