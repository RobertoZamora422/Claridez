from django.urls import path

from .external_views import (
    ExternalAcceptanceView,
    ExternalArtifactView,
    ExternalChallengeView,
    ExternalDocumentView,
    GrantExchangeView,
)

app_name = "external-documents"

urlpatterns = [
    path("exchange/", GrantExchangeView.as_view(), name="exchange"),
    path("session/", ExternalDocumentView.as_view(), name="session"),
    path("artifact/", ExternalArtifactView.as_view(), name="artifact"),
    path("challenge/", ExternalChallengeView.as_view(), name="challenge"),
    path("accept/", ExternalAcceptanceView.as_view(), name="accept"),
]
