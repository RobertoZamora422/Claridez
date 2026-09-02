from django.urls import path

from .views import (
    ChallengeStartView,
    ChallengeVerifyView,
    PortalDocumentAcceptView,
    PortalDocumentDownloadView,
    PortalDocumentsView,
    PortalEventsView,
    PortalEventView,
    PortalPreferenceView,
    PortalSessionView,
)

urlpatterns = [
    path("auth/challenges/", ChallengeStartView.as_view(), name="portal-challenge"),
    path("auth/verify/", ChallengeVerifyView.as_view(), name="portal-verify"),
    path("session/", PortalSessionView.as_view(), name="portal-session"),
    path("events/", PortalEventsView.as_view(), name="portal-events"),
    path("events/<uuid:grant_id>/", PortalEventView.as_view(), name="portal-event"),
    path(
        "events/<uuid:grant_id>/documents/", PortalDocumentsView.as_view(), name="portal-documents"
    ),
    path(
        "events/<uuid:grant_id>/documents/<uuid:issued_version_id>/<uuid:artifact_id>/download/",
        PortalDocumentDownloadView.as_view(),
        name="portal-document-download",
    ),
    path(
        "events/<uuid:grant_id>/documents/accept/",
        PortalDocumentAcceptView.as_view(),
        name="portal-document-accept",
    ),
    path("preferences/", PortalPreferenceView.as_view(), name="portal-preferences"),
]
