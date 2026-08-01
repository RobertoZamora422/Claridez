"""Enrutamiento reservado a los endpoints técnicos de plataforma."""

from django.urls import include, path
from django.urls.resolvers import URLPattern, URLResolver

from .health import health, ready

urlpatterns: list[URLPattern | URLResolver] = [
    path("health", health, name="health"),
    path("ready", ready, name="ready"),
    path("api/v1/auth/", include("claridez.identity.urls")),
]
