"""Enrutamiento técnico sin endpoints funcionales."""

from django.urls.resolvers import URLPattern, URLResolver

urlpatterns: list[URLPattern | URLResolver] = []
