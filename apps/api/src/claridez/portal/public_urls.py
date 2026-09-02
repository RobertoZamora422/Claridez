from django.urls import path

from .views import PublicAvailabilityView, PublicFormView, PublicSecurityConfigView

urlpatterns = [
    path("security-config/", PublicSecurityConfigView.as_view(), name="public-security-config"),
    path("forms/<str:locator>/", PublicFormView.as_view(), name="public-form"),
    path(
        "forms/<str:locator>/availability/",
        PublicAvailabilityView.as_view(),
        name="public-form-availability",
    ),
]
