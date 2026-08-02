from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
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
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied

from .errors import CatalogError
from .serializers import (
    CatalogItemCreateSerializer,
    CatalogItemUpdateSerializer,
    CatalogPriceCreateSerializer,
    EventTypeCreateSerializer,
    EventTypeUpdateSerializer,
)
from .services import (
    create_catalog_item,
    create_catalog_price,
    create_event_type,
    list_catalog_items,
    list_event_types,
    update_catalog_item,
    update_event_type,
)

SUCCESS = OpenApiResponse(description="Respuesta materializada dentro del tenant autorizado.")
ERROR = OpenApiResponse(description="Error JSON seguro.")


def _error(code: str, message: str, *, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _respond(operation: Callable[[], Any], *, created: bool = False) -> Response:
    try:
        result = operation()
    except TenantAccessDenied:
        return _error("resource_not_available", "El recurso no está disponible.", status=404)
    except AuthorizationDenied:
        return _error("forbidden", "La operación no está autorizada.", status=403)
    except CatalogError as error:
        return _error(error.code, error.message, status=error.status)
    return Response(_json_safe(result), status=201 if created else 200)


@method_decorator(csrf_protect, name="dispatch")
class CatalogAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        actor = request._request.user
        if not isinstance(actor, User) or not actor.is_authenticated:
            return _error("authentication_required", "Se requiere una sesión válida.", status=401)
        return actor


class EventTypeListCreateView(CatalogAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["Catálogo"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"event_types": list_event_types(actor, organization_id)})

    @extend_schema(request=EventTypeCreateSerializer, responses={201: SUCCESS}, tags=["Catálogo"])
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = EventTypeCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        return _respond(
            lambda: create_event_type(
                actor, organization_id, name=str(serializer.validated_data["name"])
            ),
            created=True,
        )


class EventTypeDetailView(CatalogAPIView):
    @extend_schema(request=EventTypeUpdateSerializer, responses={200: SUCCESS}, tags=["Catálogo"])
    def patch(self, request: Request, organization_id: UUID, event_type_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = EventTypeUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        data = serializer.validated_data
        return _respond(
            lambda: update_event_type(
                actor,
                organization_id,
                event_type_id=event_type_id,
                revision=int(data["revision"]),
                name=str(data["name"]),
                is_active=bool(data["is_active"]),
            )
        )


class CatalogItemListCreateView(CatalogAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["Catálogo"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"items": list_catalog_items(actor, organization_id)})

    @extend_schema(request=CatalogItemCreateSerializer, responses={201: SUCCESS}, tags=["Catálogo"])
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = CatalogItemCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        data = serializer.validated_data
        return _respond(
            lambda: create_catalog_item(
                actor,
                organization_id,
                kind=str(data["kind"]),
                name=str(data["name"]),
                description=str(data.get("description", "")),
                unit_label=str(data["unit_label"]),
                components=list(data.get("components", [])),
            ),
            created=True,
        )


class CatalogItemDetailView(CatalogAPIView):
    @extend_schema(request=CatalogItemUpdateSerializer, responses={200: SUCCESS}, tags=["Catálogo"])
    def patch(self, request: Request, organization_id: UUID, item_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = CatalogItemUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        data = serializer.validated_data
        return _respond(
            lambda: update_catalog_item(
                actor,
                organization_id,
                item_id=item_id,
                revision=int(data["revision"]),
                name=str(data["name"]),
                description=str(data.get("description", "")),
                unit_label=str(data["unit_label"]),
                is_active=bool(data["is_active"]),
                components=list(data.get("components", [])),
            )
        )


class CatalogPriceCreateView(CatalogAPIView):
    @extend_schema(
        request=CatalogPriceCreateSerializer, responses={201: SUCCESS}, tags=["Catálogo"]
    )
    def post(self, request: Request, organization_id: UUID, item_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = CatalogPriceCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        data = serializer.validated_data
        return _respond(
            lambda: create_catalog_price(
                actor,
                organization_id,
                item_id=item_id,
                amount=Decimal(data["amount"]),
                valid_from=data["valid_from"],
                valid_until=data.get("valid_until"),
            ),
            created=True,
        )
