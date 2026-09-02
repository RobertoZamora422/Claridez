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
from claridez.documents.public import DocumentsPortError
from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.receivables.public import ReceivablesError
from claridez.scheduling.public import SchedulingError

from .reminder_serializers import ReminderCancelSerializer, ReminderRequestSerializer
from .reminders import cancel_reminder, request_reminder

SUCCESS = OpenApiResponse(description="Recordatorio coordinado y tenant-aware.")


def _error(code: str, message: str, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _safe(operation: Any, *, created: bool = False) -> Response:
    try:
        value = operation()
    except CommunicationsError as error:
        return _error(error.code, error.message, error.status)
    except DocumentsPortError as error:
        return _error(error.code, error.detail, error.status_code)
    except (ReceivablesError, SchedulingError) as error:
        return _error(error.code, error.message, error.status)
    except (AuthorizationDenied, ValueError):
        return _error("forbidden", "La operación no está autorizada.", 403)
    return Response(value, status=201 if created else 200)


@method_decorator(csrf_protect, name="dispatch")
class ReminderAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor(self, request: Request) -> User | Response:
        actor = request._request.user
        if not isinstance(actor, User) or not actor.is_authenticated:
            return _error("authentication_required", "Se requiere una sesión válida.", 401)
        return actor


class ReminderRequestView(ReminderAPIView):
    @extend_schema(
        request=ReminderRequestSerializer,
        responses={201: SUCCESS},
        tags=["Recordatorios"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = ReminderRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: request_reminder(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class ReminderCancelView(ReminderAPIView):
    @extend_schema(
        request=ReminderCancelSerializer,
        responses={200: SUCCESS},
        tags=["Recordatorios"],
    )
    def post(self, request: Request, organization_id: UUID, intent_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = ReminderCancelSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: {
                "cancelled": cancel_reminder(
                    actor,
                    organization_id,
                    intent_id=intent_id,
                    **serializer.validated_data,
                )
            }
        )
