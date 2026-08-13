from django.urls import path

from .views import (
    ArtifactDownloadView,
    DocumentCapabilitiesView,
    ExternalFileDownloadView,
    ExternalFileUploadView,
    GrantCreateView,
    GrantRevokeView,
    InstrumentCreateView,
    InstrumentIssueView,
    LegalHoldReleaseView,
    LegalHoldView,
    PreviewView,
    RecordListCreateView,
    RetentionAssignmentView,
    RetentionEligibilityView,
    RetentionPolicyActivateView,
    RetentionView,
    TemplateActiveView,
    TemplateListCreateView,
    TemplateVersionCreateView,
    TemplateVersionDetailView,
    TemplateVersionInactivateView,
    TemplateVersionPublishView,
)

app_name = "documents"

urlpatterns = [
    path("documents/capabilities/", DocumentCapabilitiesView.as_view(), name="capabilities"),
    path("documents/templates/", TemplateListCreateView.as_view(), name="templates"),
    path(
        "documents/templates/<uuid:template_id>/versions/",
        TemplateVersionCreateView.as_view(),
        name="template-version-create",
    ),
    path(
        "documents/templates/<uuid:template_id>/active/",
        TemplateActiveView.as_view(),
        name="template-active",
    ),
    path(
        "documents/template-versions/<uuid:version_id>/",
        TemplateVersionDetailView.as_view(),
        name="template-version-detail",
    ),
    path(
        "documents/template-versions/<uuid:version_id>/publish/",
        TemplateVersionPublishView.as_view(),
        name="template-version-publish",
    ),
    path(
        "documents/template-versions/<uuid:version_id>/inactivate/",
        TemplateVersionInactivateView.as_view(),
        name="template-version-inactivate",
    ),
    path("documents/preview/", PreviewView.as_view(), name="preview"),
    path("documents/records/", RecordListCreateView.as_view(), name="records"),
    path(
        "documents/records/<uuid:record_id>/instruments/",
        InstrumentCreateView.as_view(),
        name="instruments",
    ),
    path(
        "documents/instruments/<uuid:instrument_id>/issue/",
        InstrumentIssueView.as_view(),
        name="instrument-issue",
    ),
    path(
        "documents/artifacts/<uuid:artifact_id>/download/",
        ArtifactDownloadView.as_view(),
        name="artifact-download",
    ),
    path("documents/external-files/", ExternalFileUploadView.as_view(), name="external-files"),
    path(
        "documents/external-files/<uuid:external_file_id>/download/",
        ExternalFileDownloadView.as_view(),
        name="external-file-download",
    ),
    path("documents/grants/", GrantCreateView.as_view(), name="grants"),
    path(
        "documents/grants/<uuid:grant_id>/revoke/",
        GrantRevokeView.as_view(),
        name="grant-revoke",
    ),
    path("documents/retention/", RetentionView.as_view(), name="retention"),
    path(
        "documents/retention/assignments/",
        RetentionAssignmentView.as_view(),
        name="retention-assignments",
    ),
    path(
        "documents/retention/assignments/<uuid:assignment_id>/eligibility/",
        RetentionEligibilityView.as_view(),
        name="retention-eligibility",
    ),
    path(
        "documents/retention/policies/<uuid:policy_id>/activate/",
        RetentionPolicyActivateView.as_view(),
        name="retention-policy-activate",
    ),
    path("documents/retention/holds/", LegalHoldView.as_view(), name="legal-holds"),
    path(
        "documents/retention/holds/<uuid:hold_id>/release/",
        LegalHoldReleaseView.as_view(),
        name="legal-hold-release",
    ),
]
