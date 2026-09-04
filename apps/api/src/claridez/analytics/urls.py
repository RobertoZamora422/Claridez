from django.urls import path

from .views import (
    CatalogView,
    DashboardQueryView,
    ExecutionDetailView,
    ExecutionListCreateView,
    ExportDownloadView,
    ExportListCreateView,
    ExportStatusView,
    ReportArchiveView,
    ReportListCreateView,
    ReportRevisionView,
)

app_name = "analytics"
urlpatterns = [
    path("<uuid:organization_id>/analytics/catalog/", CatalogView.as_view(), name="catalog"),
    path(
        "<uuid:organization_id>/analytics/dashboards/query/",
        DashboardQueryView.as_view(),
        name="dashboard-query",
    ),
    path(
        "<uuid:organization_id>/analytics/reports/", ReportListCreateView.as_view(), name="reports"
    ),
    path(
        "<uuid:organization_id>/analytics/reports/<uuid:report_id>/revisions/",
        ReportRevisionView.as_view(),
        name="report-revisions",
    ),
    path(
        "<uuid:organization_id>/analytics/reports/<uuid:report_id>/archive/",
        ReportArchiveView.as_view(),
        name="report-archive",
    ),
    path(
        "<uuid:organization_id>/analytics/executions/",
        ExecutionListCreateView.as_view(),
        name="executions",
    ),
    path(
        "<uuid:organization_id>/analytics/executions/<uuid:execution_id>/",
        ExecutionDetailView.as_view(),
        name="execution-detail",
    ),
    path(
        "<uuid:organization_id>/analytics/exports/", ExportListCreateView.as_view(), name="exports"
    ),
    path(
        "<uuid:organization_id>/analytics/exports/<uuid:job_id>/",
        ExportStatusView.as_view(),
        name="export-status",
    ),
    path(
        "<uuid:organization_id>/analytics/exports/<uuid:job_id>/download/",
        ExportDownloadView.as_view(),
        name="export-download",
    ),
]
