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
    path("api/v1/external/documents/", include("claridez.documents.external_urls")),
]
