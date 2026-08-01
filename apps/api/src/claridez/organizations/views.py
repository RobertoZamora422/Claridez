"""Endpoints organizacionales permitidos en el cierre de la Iteración 4."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from claridez.identity.models import User
from claridez.identity.serializers import ErrorResponseSerializer

from .application_services import (
    list_actor_organizations,
    read_memberships,
    read_organization_context,
    read_organization_settings,
)
from .exceptions import AuthorizationDenied, TenantAccessDenied
from .serializers import (
    MembershipListResponseSerializer,
    MembershipSerializer,
    OrganizationContextResponseSerializer,
    OrganizationContextSelectionSerializer,
    OrganizationListResponseSerializer,
    OrganizationSerializer,
    OrganizationSettingsResponseSerializer,
    OrganizationSettingsSerializer,
)

LAST_ORGANIZATION_SESSION_KEY = "last_organization_id"


def _error(code: str, message: str, *, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _actor(request: Request) -> User | None:
    actor = request._request.user
    return actor if isinstance(actor, User) and actor.is_authenticated else None


def _authentication_required() -> Response:
    return _error("authentication_required", "Se requiere una sesión válida.", status=401)


def _organization_unavailable() -> Response:
    return _error(
        "organization_not_available",
        "La organización no está disponible.",
        status=404,
    )


def _forbidden() -> Response:
    return _error("forbidden", "La operación no está autorizada.", status=403)


class OrganizationAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []


class OrganizationListView(OrganizationAPIView):
    @extend_schema(
        responses={200: OrganizationListResponseSerializer, 401: ErrorResponseSerializer},
        tags=["Organizaciones"],
    )
    def get(self, request: Request) -> Response:
        actor = _actor(request)
        if actor is None:
            return _authentication_required()
        try:
            organizations = list_actor_organizations(actor)
        except AuthorizationDenied:
            return _forbidden()
        return Response({"organizations": OrganizationSerializer(organizations, many=True).data})


class OrganizationContextView(OrganizationAPIView):
    @extend_schema(
        responses={200: OrganizationContextResponseSerializer, 401: ErrorResponseSerializer},
        tags=["Organizaciones"],
    )
    def get(self, request: Request) -> Response:
        actor = _actor(request)
        if actor is None:
            return _authentication_required()
        raw_reference = request._request.session.get(LAST_ORGANIZATION_SESSION_KEY)
        if not isinstance(raw_reference, str):
            request._request.session.pop(LAST_ORGANIZATION_SESSION_KEY, None)
            return Response({"organization": None})
        try:
            organization = read_organization_context(actor, raw_reference)
        except AuthorizationDenied:
            request._request.session.pop(LAST_ORGANIZATION_SESSION_KEY, None)
            return Response({"organization": None})
        return Response({"organization": OrganizationSerializer(organization).data})

    @extend_schema(
        request=OrganizationContextSelectionSerializer,
        responses={
            200: OrganizationContextResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
        tags=["Organizaciones"],
    )
    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        actor = _actor(request)
        if actor is None:
            return _authentication_required()
        serializer = OrganizationContextSelectionSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        reference = serializer.validated_data["organization_id"]
        try:
            organization = read_organization_context(actor, reference)
        except AuthorizationDenied:
            return _organization_unavailable()
        request._request.session[LAST_ORGANIZATION_SESSION_KEY] = str(organization.id)
        return Response({"organization": OrganizationSerializer(organization).data})


class OrganizationSettingsView(OrganizationAPIView):
    @extend_schema(
        responses={
            200: OrganizationSettingsResponseSerializer,
            401: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
        tags=["Organizaciones"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = _actor(request)
        if actor is None:
            return _authentication_required()
        try:
            settings = read_organization_settings(actor, organization_id)
        except TenantAccessDenied:
            return _organization_unavailable()
        except AuthorizationDenied:
            return _forbidden()
        return Response({"settings": OrganizationSettingsSerializer(settings).data})


class MembershipListView(OrganizationAPIView):
    @extend_schema(
        responses={
            200: MembershipListResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
        tags=["Organizaciones"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = _actor(request)
        if actor is None:
            return _authentication_required()
        try:
            memberships = read_memberships(actor, organization_id)
        except TenantAccessDenied:
            return _organization_unavailable()
        except AuthorizationDenied:
            return _forbidden()
        return Response({"memberships": MembershipSerializer(memberships, many=True).data})
