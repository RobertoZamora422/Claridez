from django.urls import path

from .views import (
    FormListCreateView,
    FormLocatorRotateView,
    FormPublishView,
    FormRetireView,
    FormVersionCreateView,
    GrantListCreateView,
    GrantRevokeView,
    P14CapabilitiesView,
    WebhookLocatorCreateView,
)

urlpatterns = [
    path(
        "<uuid:organization_id>/p14/capabilities/",
        P14CapabilitiesView.as_view(),
        name="p14-capabilities",
    ),
    path("<uuid:organization_id>/public-forms/", FormListCreateView.as_view(), name="p14-forms"),
    path(
        "<uuid:organization_id>/public-forms/<uuid:form_id>/versions/",
        FormVersionCreateView.as_view(),
        name="p14-form-version",
    ),
    path(
        "<uuid:organization_id>/public-forms/<uuid:form_id>/locator/rotate/",
        FormLocatorRotateView.as_view(),
        name="p14-form-locator-rotate",
    ),
    path(
        "<uuid:organization_id>/public-forms/<uuid:form_id>/retire/",
        FormRetireView.as_view(),
        name="p14-form-retire",
    ),
    path(
        "<uuid:organization_id>/public-forms/versions/<uuid:version_id>/publish/",
        FormPublishView.as_view(),
        name="p14-form-publish",
    ),
    path(
        "<uuid:organization_id>/portal-grants/", GrantListCreateView.as_view(), name="portal-grants"
    ),
    path(
        "<uuid:organization_id>/portal-grants/<uuid:grant_id>/revoke/",
        GrantRevokeView.as_view(),
        name="portal-grant-revoke",
    ),
    path(
        "<uuid:organization_id>/communications/webhook-locators/",
        WebhookLocatorCreateView.as_view(),
        name="communications-webhook-locator",
    ),
]
