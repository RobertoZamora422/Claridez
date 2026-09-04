"""Enrutamiento reservado a los endpoints técnicos de plataforma."""

from django.urls import include, path
from django.urls.resolvers import URLPattern, URLResolver

from .health import health, ready

urlpatterns: list[URLPattern | URLResolver] = [
    path("health", health, name="health"),
    path("ready", ready, name="ready"),
    path("api/v1/auth/", include("claridez.identity.urls")),
    path("api/v1/organizations/", include("claridez.organizations.urls")),
    path("api/v1/organizations/", include("claridez.operations.urls")),
    path("api/v1/organizations/", include("claridez.receivables.urls")),
    path("api/v1/organizations/", include("claridez.resources.urls")),
    path("api/v1/organizations/", include("claridez.finance.urls")),
    path("api/v1/organizations/", include("claridez.analytics.urls")),
    path("api/v1/external/documents/", include("claridez.documents.external_urls")),
    path("api/v1/public/", include("claridez.portal.public_urls")),
    path("api/v1/portal/", include("claridez.portal.urls")),
    path("api/v1/organizations/", include("claridez.portal.internal_urls")),
    path("api/v1/organizations/", include("claridez.application.communication_urls")),
    path("api/v1/organizations/", include("claridez.communications.urls")),
    path("api/v1/organizations/", include("claridez.application.reminder_urls")),
    path("api/v1/webhooks/communications/", include("claridez.portal.webhook_urls")),
]
