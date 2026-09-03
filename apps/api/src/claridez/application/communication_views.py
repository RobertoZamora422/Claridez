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

from claridez.communications.errors import CommunicationsError
from claridez.communications.serializers import IntentCreateSerializer, RetrySerializer
from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied

from .communications import request_event_intent, retry_delivery

SUCCESS = OpenApiResponse(description="Comunicación coordinada y tenant-aware.")


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
class CommunicationCoordinatorAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor(self, request: Request) -> User | Response:
        actor = request._request.user
        if not isinstance(actor, User) or not actor.is_authenticated:
            return _error("authentication_required", "Se requiere una sesión válida.", 401)
        return actor


class IntentCreateView(CommunicationCoordinatorAPIView):
    @extend_schema(
        request=IntentCreateSerializer, responses={201: SUCCESS}, tags=["Comunicaciones"]
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = IntentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: request_event_intent(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class DeliveryRetryView(CommunicationCoordinatorAPIView):
    @extend_schema(request=RetrySerializer, responses={200: SUCCESS}, tags=["Comunicaciones"])
    def post(self, request: Request, organization_id: UUID, message_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = RetrySerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: retry_delivery(
                actor,
                organization_id,
                message_id=message_id,
                reason=str(serializer.validated_data["reason"]),
            )
        )
