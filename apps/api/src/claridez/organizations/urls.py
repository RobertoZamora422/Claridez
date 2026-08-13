"""Rutas organizacionales aprobadas para el cierre de la Iteración 4."""

from django.urls import include, path

from .configuration_views import (
    BusinessConfigurationView,
    ConfigurationCapabilitiesView,
    SpaceDetailView,
    SpaceListCreateView,
    VenueDetailView,
    VenueListCreateView,
)
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
    path(
        "<uuid:organization_id>/configuration/capabilities/",
        ConfigurationCapabilitiesView.as_view(),
        name="configuration-capabilities",
    ),
    path(
        "<uuid:organization_id>/configuration/",
        BusinessConfigurationView.as_view(),
        name="business-configuration",
    ),
    path("<uuid:organization_id>/venues/", VenueListCreateView.as_view(), name="venues"),
    path(
        "<uuid:organization_id>/venues/<uuid:venue_id>/",
        VenueDetailView.as_view(),
        name="venue-detail",
    ),
    path(
        "<uuid:organization_id>/venues/<uuid:venue_id>/spaces/",
        SpaceListCreateView.as_view(),
        name="spaces",
    ),
    path(
        "<uuid:organization_id>/spaces/<uuid:space_id>/",
        SpaceDetailView.as_view(),
        name="space-detail",
    ),
    path("<uuid:organization_id>/", include("claridez.catalog.urls")),
    path("<uuid:organization_id>/", include("claridez.people.urls")),
    path("<uuid:organization_id>/", include("claridez.commercial.urls")),
    path("<uuid:organization_id>/", include("claridez.crm.urls")),
    path("<uuid:organization_id>/", include("claridez.scheduling.urls")),
    path("<uuid:organization_id>/", include("claridez.documents.urls")),
]
