"""Enrutamiento reservado a los endpoints técnicos de plataforma."""

from django.urls import path
from django.urls.resolvers import URLPattern, URLResolver

from .health import health, ready

urlpatterns: list[URLPattern | URLResolver] = [
    path("health", health, name="health"),
    path("ready", ready, name="ready"),
]
