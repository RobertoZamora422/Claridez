from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from claridez.identity.models import User

from .configuration_serializers import (
    BusinessConfigurationSerializer,
    SpaceCreateSerializer,
    SpaceUpdateSerializer,
    VenueCreateSerializer,
    VenueUpdateSerializer,
)
from .configuration_services import (
    ConfigurationError,
    configuration_capabilities,
    create_space,
    create_venue,
    list_venues,
    read_business_configuration,
    update_business_configuration,
    update_space,
    update_venue,
)
from .exceptions import AuthorizationDenied, TenantAccessDenied

SUCCESS = OpenApiResponse(description="Respuesta materializada dentro del tenant autorizado.")
ERROR = OpenApiResponse(description="Error JSON seguro.")


def _error(code: str, message: str, *, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _respond(operation: Callable[[], Any], *, created: bool = False) -> Response:
    try:
        result = operation()
    except TenantAccessDenied:
        return _error("resource_not_available", "El recurso no está disponible.", status=404)
    except AuthorizationDenied:
        return _error("forbidden", "La operación no está autorizada.", status=403)
    except ConfigurationError as error:
        return _error(error.code, error.message, status=error.status)
    return Response(result, status=201 if created else 200)


@method_decorator(csrf_protect, name="dispatch")
class ConfigurationAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        actor = request._request.user
        if not isinstance(actor, User) or not actor.is_authenticated:
            return _error("authentication_required", "Se requiere una sesión válida.", status=401)
        return actor


class ConfigurationCapabilitiesView(ConfigurationAPIView):
    @extend_schema(responses={200: SUCCESS, 401: ERROR, 404: ERROR}, tags=["Configuración"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: {"capabilities": configuration_capabilities(actor, organization_id)}
        )


class BusinessConfigurationView(ConfigurationAPIView):
    @extend_schema(responses={200: SUCCESS, 401: ERROR, 404: ERROR}, tags=["Configuración"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: read_business_configuration(actor, organization_id))

    @extend_schema(
        request=BusinessConfigurationSerializer, responses={200: SUCCESS}, tags=["Configuración"]
    )
    def patch(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = BusinessConfigurationSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        data = serializer.validated_data
        return _respond(
            lambda: update_business_configuration(
                actor,
                organization_id,
                name=str(data["name"]),
                currency=str(data["currency"]),
                timezone=str(data["timezone"]),
            )
        )


class VenueListCreateView(ConfigurationAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["Sedes y espacios"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"venues": list_venues(actor, organization_id)})

    @extend_schema(
        request=VenueCreateSerializer, responses={201: SUCCESS}, tags=["Sedes y espacios"]
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = VenueCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        data = serializer.validated_data
        return _respond(
            lambda: create_venue(
                actor,
                organization_id,
                name=str(data["name"]),
                location_reference=str(data.get("location_reference", "")),
                is_primary=bool(data.get("is_primary", False)),
            ),
            created=True,
        )


class VenueDetailView(ConfigurationAPIView):
    @extend_schema(
        request=VenueUpdateSerializer, responses={200: SUCCESS}, tags=["Sedes y espacios"]
    )
    def patch(self, request: Request, organization_id: UUID, venue_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = VenueUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        data = dict(serializer.validated_data)
        revision = int(data.pop("revision"))
        return _respond(
            lambda: update_venue(
                actor, organization_id, venue_id=venue_id, revision=revision, changes=data
            )
        )


class SpaceListCreateView(ConfigurationAPIView):
    @extend_schema(
        request=SpaceCreateSerializer, responses={201: SUCCESS}, tags=["Sedes y espacios"]
    )
    def post(self, request: Request, organization_id: UUID, venue_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = SpaceCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        data = serializer.validated_data
        return _respond(
            lambda: create_space(
                actor,
                organization_id,
                venue_id=venue_id,
                name=str(data["name"]),
                is_primary=bool(data.get("is_primary", False)),
            ),
            created=True,
        )


class SpaceDetailView(ConfigurationAPIView):
    @extend_schema(
        request=SpaceUpdateSerializer, responses={200: SUCCESS}, tags=["Sedes y espacios"]
    )
    def patch(self, request: Request, organization_id: UUID, space_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = SpaceUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        data = dict(serializer.validated_data)
        revision = int(data.pop("revision"))
        return _respond(
            lambda: update_space(
                actor, organization_id, space_id=space_id, revision=revision, changes=data
            )
        )
