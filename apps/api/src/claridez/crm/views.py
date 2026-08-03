from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from claridez.commercial.errors import CommercialError
from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied
from claridez.people.errors import PeopleError

from .errors import CrmError
from .serializers import InteractionCreateSerializer, TaskCreateSerializer, TaskUpdateSerializer
from .services import (
    create_task,
    crm_capabilities,
    indicators,
    list_interactions,
    list_opportunities,
    list_tasks,
    person_overview,
    read_opportunity,
    read_opportunity_history,
    record_interaction,
    update_task,
)

SUCCESS = OpenApiResponse(description="Respuesta CRM materializada dentro del tenant autorizado.")
ERROR = OpenApiResponse(description="Error JSON seguro.")


def _error(code: str, message: str, *, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _actor(request: Request) -> User | None:
    user = request._request.user
    return user if isinstance(user, User) and user.is_authenticated else None


def _respond(operation: Callable[[], Any], *, created: bool = False) -> Response:
    try:
        result = operation()
    except TenantAccessDenied:
        return _error("resource_not_available", "El recurso no está disponible.", status=404)
    except AuthorizationDenied:
        return _error("forbidden", "La operación no está autorizada.", status=403)
    except (CrmError, PeopleError, CommercialError) as error:
        return _error(error.code, error.message, status=error.status)
    return Response(result, status=201 if created else 200)


@method_decorator(csrf_protect, name="dispatch")
class CrmAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        actor = _actor(request)
        if actor is None:
            return _error("authentication_required", "Se requiere una sesión válida.", status=401)
        return actor


class CrmCapabilitiesView(CrmAPIView):
    @extend_schema(responses={200: SUCCESS, 401: ERROR, 404: ERROR}, tags=["CRM"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"capabilities": crm_capabilities(actor, organization_id)})


class OpportunityListView(CrmAPIView):
    @extend_schema(
        operation_id="crm_opportunities_list",
        parameters=[OpenApiParameter("status", str, required=False)],
        responses={200: SUCCESS, 403: ERROR, 404: ERROR},
        tags=["CRM"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: {
                "opportunities": list_opportunities(
                    actor, organization_id, status=request.query_params.get("status", "")
                )
            }
        )


class OpportunityDetailView(CrmAPIView):
    @extend_schema(
        operation_id="crm_opportunity_retrieve",
        responses={200: SUCCESS, 403: ERROR, 404: ERROR},
        tags=["CRM"],
    )
    def get(self, request: Request, organization_id: UUID, event_request_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: read_opportunity(actor, organization_id, request_id=event_request_id)
        )


class OpportunityHistoryView(CrmAPIView):
    @extend_schema(
        operation_id="crm_opportunity_history",
        responses={200: SUCCESS, 403: ERROR, 404: ERROR},
        tags=["CRM"],
    )
    def get(self, request: Request, organization_id: UUID, event_request_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: {
                "history": read_opportunity_history(
                    actor, organization_id, request_id=event_request_id
                )
            }
        )


class InteractionListCreateView(CrmAPIView):
    @extend_schema(
        operation_id="crm_interactions_list",
        parameters=[
            OpenApiParameter("person_id", str, required=False),
            OpenApiParameter("event_request_id", str, required=False),
        ],
        responses={200: SUCCESS, 403: ERROR, 404: ERROR},
        tags=["CRM"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: {
                "interactions": list_interactions(
                    actor,
                    organization_id,
                    person_id=request.query_params.get("person_id"),
                    event_request_id=request.query_params.get("event_request_id"),
                )
            }
        )

    @extend_schema(
        operation_id="crm_interactions_record",
        request=InteractionCreateSerializer,
        responses={201: SUCCESS, 400: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["CRM"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = InteractionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        return _respond(
            lambda: record_interaction(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class TaskListCreateView(CrmAPIView):
    @extend_schema(
        operation_id="crm_tasks_list",
        parameters=[
            OpenApiParameter("person_id", str, required=False),
            OpenApiParameter("event_request_id", str, required=False),
            OpenApiParameter("status", str, required=False),
        ],
        responses={200: SUCCESS, 403: ERROR, 404: ERROR},
        tags=["CRM"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: {
                "tasks": list_tasks(
                    actor,
                    organization_id,
                    person_id=request.query_params.get("person_id"),
                    event_request_id=request.query_params.get("event_request_id"),
                    status=request.query_params.get("status", ""),
                )
            }
        )

    @extend_schema(
        operation_id="crm_tasks_create",
        request=TaskCreateSerializer,
        responses={201: SUCCESS, 400: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["CRM"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = TaskCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        return _respond(
            lambda: create_task(actor, organization_id, **serializer.validated_data), created=True
        )


class TaskDetailView(CrmAPIView):
    @extend_schema(
        operation_id="crm_tasks_update",
        request=TaskUpdateSerializer,
        responses={200: SUCCESS, 400: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["CRM"],
    )
    def patch(self, request: Request, organization_id: UUID, task_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = TaskUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        data = dict(serializer.validated_data)
        revision = int(data.pop("revision"))
        return _respond(
            lambda: update_task(
                actor, organization_id, task_id=task_id, revision=revision, changes=data
            )
        )


class CrmIndicatorsView(CrmAPIView):
    @extend_schema(
        operation_id="crm_indicators", responses={200: SUCCESS, 403: ERROR}, tags=["CRM"]
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"indicators": indicators(actor, organization_id)})


class PersonOverviewView(CrmAPIView):
    @extend_schema(
        operation_id="crm_people_overview",
        responses={200: SUCCESS, 403: ERROR, 404: ERROR},
        tags=["CRM"],
    )
    def get(self, request: Request, organization_id: UUID, person_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: person_overview(actor, organization_id, person_id=person_id))
