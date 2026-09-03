from django.urls import path

from .communication_views import DeliveryRetryView, IntentCreateView

urlpatterns = [
    path("<uuid:organization_id>/communications/intents/", IntentCreateView.as_view()),
    path(
        "<uuid:organization_id>/communications/deliveries/<uuid:message_id>/retry/",
        DeliveryRetryView.as_view(),
    ),
]
