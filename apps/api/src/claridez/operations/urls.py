from django.urls import path

from .views import (
    AssigneeListView,
    AssignmentView,
    CompleteView,
    EventDetailView,
    EventListView,
    ItemCreateView,
    ItemUpdateView,
    OperationsCapabilitiesView,
    PreparationUpdateView,
    ReadyView,
    StartView,
)

app_name = "operations"

urlpatterns = [
    path("<uuid:organization_id>/operations/capabilities/", OperationsCapabilitiesView.as_view()),
    path("<uuid:organization_id>/operations/assignees/", AssigneeListView.as_view()),
    path("<uuid:organization_id>/operations/events/", EventListView.as_view()),
    path(
        "<uuid:organization_id>/operations/events/<uuid:reservation_id>/",
        EventDetailView.as_view(),
    ),
    path(
        "<uuid:organization_id>/operations/events/<uuid:reservation_id>/preparation/",
        PreparationUpdateView.as_view(),
    ),
    path(
        "<uuid:organization_id>/operations/events/<uuid:reservation_id>/assign/",
        AssignmentView.as_view(),
    ),
    path(
        "<uuid:organization_id>/operations/events/<uuid:reservation_id>/items/",
        ItemCreateView.as_view(),
    ),
    path(
        "<uuid:organization_id>/operations/events/<uuid:reservation_id>/items/<uuid:item_id>/",
        ItemUpdateView.as_view(),
    ),
    path(
        "<uuid:organization_id>/operations/events/<uuid:reservation_id>/ready/",
        ReadyView.as_view(),
    ),
    path(
        "<uuid:organization_id>/operations/events/<uuid:reservation_id>/start/",
        StartView.as_view(),
    ),
    path(
        "<uuid:organization_id>/operations/events/<uuid:reservation_id>/complete/",
        CompleteView.as_view(),
    ),
]
