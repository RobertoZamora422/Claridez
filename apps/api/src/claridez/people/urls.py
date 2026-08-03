from django.urls import path

from .views import PersonConsentView, PersonMergeView

app_name = "people"

urlpatterns = [
    path("people/merge/", PersonMergeView.as_view(), name="merge"),
    path(
        "people/<uuid:person_id>/consents/",
        PersonConsentView.as_view(),
        name="consents",
    ),
]
