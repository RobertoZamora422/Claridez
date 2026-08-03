from django.urls import path

from .views import (
    CrmCapabilitiesView,
    CrmIndicatorsView,
    InteractionListCreateView,
    OpportunityDetailView,
    OpportunityHistoryView,
    OpportunityListView,
    PersonOverviewView,
    TaskDetailView,
    TaskListCreateView,
)

app_name = "crm"

urlpatterns = [
    path("crm/capabilities/", CrmCapabilitiesView.as_view(), name="capabilities"),
    path("crm/opportunities/", OpportunityListView.as_view(), name="opportunities"),
    path(
        "crm/opportunities/<uuid:event_request_id>/",
        OpportunityDetailView.as_view(),
        name="opportunity-detail",
    ),
    path(
        "crm/opportunities/<uuid:event_request_id>/history/",
        OpportunityHistoryView.as_view(),
        name="opportunity-history",
    ),
    path("crm/interactions/", InteractionListCreateView.as_view(), name="interactions"),
    path("crm/tasks/", TaskListCreateView.as_view(), name="tasks"),
    path("crm/tasks/<uuid:task_id>/", TaskDetailView.as_view(), name="task-detail"),
    path("crm/indicators/", CrmIndicatorsView.as_view(), name="indicators"),
    path("crm/people/<uuid:person_id>/", PersonOverviewView.as_view(), name="person-overview"),
]
