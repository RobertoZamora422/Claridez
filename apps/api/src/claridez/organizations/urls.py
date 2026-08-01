"""Rutas organizacionales aprobadas para el cierre de la Iteración 4."""

from django.urls import path

from .views import (
    MembershipListView,
    OrganizationContextView,
    OrganizationListView,
    OrganizationSettingsView,
)

app_name = "organizations"

urlpatterns = [
    path("", OrganizationListView.as_view(), name="list"),
    path("context/", OrganizationContextView.as_view(), name="context"),
    path(
        "<uuid:organization_id>/settings/",
        OrganizationSettingsView.as_view(),
        name="settings",
    ),
    path(
        "<uuid:organization_id>/memberships/",
        MembershipListView.as_view(),
        name="memberships",
    ),
]
