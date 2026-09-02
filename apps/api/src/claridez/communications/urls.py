from django.urls import path

from .views import (
    DeliveryListView,
    DeliveryRetryView,
    IntentCreateView,
    PolicyCreateView,
    PreferenceActionView,
    SenderCreateView,
    TemplateListCreateView,
    TemplatePublishView,
    TemplateVersionCreateView,
)

urlpatterns = [
    path("<uuid:organization_id>/communications/templates/", TemplateListCreateView.as_view()),
    path(
        "<uuid:organization_id>/communications/templates/<uuid:template_id>/versions/",
        TemplateVersionCreateView.as_view(),
    ),
    path(
        "<uuid:organization_id>/communications/templates/versions/<uuid:version_id>/publish/",
        TemplatePublishView.as_view(),
    ),
    path("<uuid:organization_id>/communications/intents/", IntentCreateView.as_view()),
    path("<uuid:organization_id>/communications/deliveries/", DeliveryListView.as_view()),
    path(
        "<uuid:organization_id>/communications/deliveries/<uuid:message_id>/retry/",
        DeliveryRetryView.as_view(),
    ),
    path("<uuid:organization_id>/communications/policies/", PolicyCreateView.as_view()),
    path("<uuid:organization_id>/communications/senders/", SenderCreateView.as_view()),
    path("<uuid:organization_id>/communications/preferences/", PreferenceActionView.as_view()),
]
