from django.urls import path

from .views import (
    AvailabilityView,
    CommercialCapabilitiesView,
    EventRequestCloseView,
    EventRequestDetailView,
    EventRequestListCreateView,
    PersonDetailView,
    PersonListCreateView,
    PersonRevisionListView,
    QuotationAcceptView,
    QuotationDetailView,
    QuotationIssueView,
    QuotationVersionCreateView,
    QuotationVersionDetailView,
    RequestQuotationCreateView,
    ReservationCancelView,
    ReservationConfirmView,
    ReservationDetailView,
)

app_name = "commercial"

urlpatterns = [
    path("commercial/capabilities/", CommercialCapabilitiesView.as_view(), name="capabilities"),
    path("people/", PersonListCreateView.as_view(), name="people"),
    path("people/<uuid:person_id>/", PersonDetailView.as_view(), name="person-detail"),
    path(
        "people/<uuid:person_id>/revisions/",
        PersonRevisionListView.as_view(),
        name="person-revisions",
    ),
    path("event-requests/", EventRequestListCreateView.as_view(), name="event-requests"),
    path(
        "event-requests/<uuid:event_request_id>/",
        EventRequestDetailView.as_view(),
        name="event-request-detail",
    ),
    path(
        "event-requests/<uuid:event_request_id>/close/",
        EventRequestCloseView.as_view(),
        name="event-request-close",
    ),
    path("availability/", AvailabilityView.as_view(), name="availability"),
    path(
        "event-requests/<uuid:event_request_id>/quotations/",
        RequestQuotationCreateView.as_view(),
        name="quotation-create",
    ),
    path("quotations/<uuid:quotation_id>/", QuotationDetailView.as_view(), name="quotation-detail"),
    path(
        "quotations/<uuid:quotation_id>/versions/",
        QuotationVersionCreateView.as_view(),
        name="quotation-version-create",
    ),
    path(
        "quotations/<uuid:quotation_id>/versions/<int:version>/",
        QuotationVersionDetailView.as_view(),
        name="quotation-version-detail",
    ),
    path(
        "quotations/<uuid:quotation_id>/versions/<int:version>/issue/",
        QuotationIssueView.as_view(),
        name="quotation-issue",
    ),
    path(
        "quotations/<uuid:quotation_id>/versions/<int:version>/accept/",
        QuotationAcceptView.as_view(),
        name="quotation-accept",
    ),
    path(
        "reservations/<uuid:reservation_id>/",
        ReservationDetailView.as_view(),
        name="reservation-detail",
    ),
    path(
        "reservations/<uuid:reservation_id>/confirm/",
        ReservationConfirmView.as_view(),
        name="reservation-confirm",
    ),
    path(
        "reservations/<uuid:reservation_id>/cancel/",
        ReservationCancelView.as_view(),
        name="reservation-cancel",
    ),
]
