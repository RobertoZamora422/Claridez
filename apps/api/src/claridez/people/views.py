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
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied

from .errors import PeopleError
from .serializers import ConsentEventSerializer, PersonMergeSerializer
from .services import list_consents, merge_people, record_consent

SUCCESS = OpenApiResponse(description="Respuesta materializada dentro del tenant autorizado.")
ERROR = OpenApiResponse(description="Error JSON seguro.")


def _error(code: str, message: str, *, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _actor(request: Request) -> User | None:
    user = request._request.user
    return user if isinstance(user, User) and user.is_authenticated else None


def _respond(operation: Any, *, created: bool = False) -> Response:
    try:
        result = operation()
    except TenantAccessDenied:
        return _error("resource_not_available", "El recurso no está disponible.", status=404)
    except AuthorizationDenied:
        return _error("forbidden", "La operación no está autorizada.", status=403)
    except PeopleError as error:
        return _error(error.code, error.message, status=error.status)
    return Response(result, status=201 if created else 200)


@method_decorator(csrf_protect, name="dispatch")
class PeopleAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        actor = _actor(request)
        if actor is None:
            return _error("authentication_required", "Se requiere una sesión válida.", status=401)
        return actor


class PersonMergeView(PeopleAPIView):
    @extend_schema(
        operation_id="people_merge",
        request=PersonMergeSerializer,
        responses={200: SUCCESS, 400: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Personas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = PersonMergeSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        return _respond(lambda: merge_people(actor, organization_id, **serializer.validated_data))


class PersonConsentView(PeopleAPIView):
    @extend_schema(
        operation_id="people_consents_list",
        responses={200: SUCCESS, 403: ERROR, 404: ERROR},
        tags=["Consentimiento"],
    )
    def get(self, request: Request, organization_id: UUID, person_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: list_consents(actor, organization_id, person_id=person_id))

    @extend_schema(
        operation_id="people_consents_record",
        request=ConsentEventSerializer,
        responses={201: SUCCESS, 400: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Consentimiento"],
    )
    def post(self, request: Request, organization_id: UUID, person_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = ConsentEventSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        return _respond(
            lambda: record_consent(
                actor, organization_id, person_id=person_id, **serializer.validated_data
            ),
            created=True,
        )
