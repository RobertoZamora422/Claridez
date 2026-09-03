from __future__ import annotations

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
from claridez.organizations.exceptions import AuthorizationDenied

from .errors import CommunicationsError
from .serializers import (
    CommunicationTemplateVersionCreateSerializer,
    PolicySerializer,
    PreferenceActionSerializer,
    SenderSerializer,
    TemplateCreateSerializer,
)
from .services import (
    configure_policy,
    configure_sender,
    create_template,
    create_template_version,
    internal_preference_action,
    list_deliveries,
    list_preferences,
    list_templates,
    publish_template,
)

SUCCESS = OpenApiResponse(description="Respuesta tenant-aware de Communications.")


def _error(code: str, message: str, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _safe(operation: Any, *, created: bool = False) -> Response:
    try:
        value = operation()
    except CommunicationsError as error:
        return _error(error.code, error.message, error.status)
    except AuthorizationDenied:
        return _error("forbidden", "La operación no está autorizada.", 403)
    return Response(value, status=201 if created else 200)


@method_decorator(csrf_protect, name="dispatch")
class CommunicationsAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor(self, request: Request) -> User | Response:
        actor = request._request.user
        if not isinstance(actor, User) or not actor.is_authenticated:
            return _error("authentication_required", "Se requiere una sesión válida.", 401)
        return actor


class TemplateListCreateView(CommunicationsAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["Comunicaciones"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        return _safe(lambda: {"templates": list_templates(actor, organization_id)})

    @extend_schema(
        request=TemplateCreateSerializer, responses={201: SUCCESS}, tags=["Comunicaciones"]
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = TemplateCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: create_template(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class TemplatePublishView(CommunicationsAPIView):
    @extend_schema(request=None, responses={200: SUCCESS}, tags=["Comunicaciones"])
    def post(self, request: Request, organization_id: UUID, version_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        return _safe(lambda: publish_template(actor, organization_id, version_id=version_id))


class TemplateVersionCreateView(CommunicationsAPIView):
    @extend_schema(
        request=CommunicationTemplateVersionCreateSerializer,
        responses={201: SUCCESS},
        tags=["Comunicaciones"],
    )
    def post(self, request: Request, organization_id: UUID, template_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = CommunicationTemplateVersionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: create_template_version(
                actor,
                organization_id,
                template_id=template_id,
                **serializer.validated_data,
            ),
            created=True,
        )


class DeliveryListView(CommunicationsAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["Comunicaciones"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        return _safe(lambda: {"deliveries": list_deliveries(actor, organization_id)})


class PolicyCreateView(CommunicationsAPIView):
    @extend_schema(request=PolicySerializer, responses={201: SUCCESS}, tags=["Comunicaciones"])
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = PolicySerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: configure_policy(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class SenderCreateView(CommunicationsAPIView):
    @extend_schema(request=SenderSerializer, responses={201: SUCCESS}, tags=["Comunicaciones"])
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = SenderSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: configure_sender(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class PreferenceActionView(CommunicationsAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["Comunicaciones"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        return _safe(lambda: {"preferences": list_preferences(actor, organization_id)})

    @extend_schema(
        request=PreferenceActionSerializer, responses={200: SUCCESS}, tags=["Comunicaciones"]
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = PreferenceActionSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        data = serializer.validated_data
        return _safe(
            lambda: internal_preference_action(
                actor,
                organization_id,
                person_id=data["person_id"],
                channel=str(data["channel"]),
                purpose=str(data["purpose"]),
                suppress=data["action"] == "suppress",
                reason=str(data["reason"]),
            )
        )
