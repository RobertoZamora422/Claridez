from django.urls import path

from .webhook_views import CommunicationsWebhookView

urlpatterns = [
    path("<str:locator>/", CommunicationsWebhookView.as_view(), name="communications-webhook")
]
