from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied

from .api_schemas import (
    AssigneeListResponseSerializer,
    CapabilitiesResponseSerializer,
    ErrorResponseSerializer,
    EventListResponseSerializer,
    ItemMutationResponseSerializer,
    OperationEventDetailSerializer,
)
from .errors import OperationsError
from .serializers import (
    AssignmentSerializer,
    EventListQuerySerializer,
    ItemCreateSerializer,
    ItemUpdateSerializer,
    PreparationUpdateSerializer,
    RevisionSerializer,
)
from .services import (
    assign_preparation,
    complete_event,
    create_item,
    list_assignees,
    list_events,
    mark_ready,
    operation_capabilities,
    read_event,
    start_event,
    update_item,
    update_preparation,
)


def _error(code: str, message: str, *, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _actor(request: Request) -> User | None:
    user = request._request.user
    return user if isinstance(user, User) and user.is_authenticated else None


def _respond(operation: Callable[[], Any], *, created: bool = False) -> Response:
    try:
        result = operation()
    except (TenantAccessDenied, AuthorizationDenied, OperationsError) as error:
        return _exception_response(error)
    return Response(result, status=201 if created else 200)


def _exception_response(error: Exception) -> Response:
    if isinstance(error, TenantAccessDenied):
        return _error("resource_not_available", "El recurso no está disponible.", status=404)
    if isinstance(error, AuthorizationDenied):
        return _error("forbidden", "La operación no está autorizada.", status=403)
    if isinstance(error, OperationsError):
        return _error(error.code, error.message, status=error.status)
    raise error


def _validated(serializer: Any) -> Response | None:
    if serializer.is_valid():
        return None
    return Response(
        {
            "error": {
                "code": "invalid_request",
                "message": "La solicitud no es válida.",
                "fields": _safe_field_errors(serializer.errors),
            }
        },
        status=400,
    )


def _safe_field_errors(errors: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for field, field_errors in errors.items():
        safe_field = "_schema" if field == "non_field_errors" else str(field)
        errors_list = field_errors if isinstance(field_errors, list) else [field_errors]
        result[safe_field] = [
            _safe_validation_message(str(getattr(error, "code", "invalid")))
            for error in errors_list
        ]
    return result


def _safe_validation_message(code: str) -> str:
    messages = {
        "required": "Este campo es obligatorio.",
        "blank": "Este campo no puede estar vacío.",
        "null": "Este campo no puede ser nulo.",
        "invalid_choice": "El valor no pertenece al catálogo permitido.",
        "min_value": "El valor está por debajo del mínimo permitido.",
        "max_value": "El valor supera el máximo permitido.",
        "min_length": "El texto es más corto de lo permitido.",
        "max_length": "El texto supera la longitud permitida.",
    }
    return messages.get(code, "El valor no es válido.")


@method_decorator(csrf_protect, name="dispatch")
class OperationsAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        actor = _actor(request)
        if actor is None:
            return _error("authentication_required", "Se requiere una sesión válida.", status=401)
        return actor


class OperationsCapabilitiesView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_capabilities_retrieve",
        responses={
            200: CapabilitiesResponseSerializer,
            401: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
        tags=["Operaciones"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"capabilities": operation_capabilities(actor, organization_id)})


class AssigneeListView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_assignees_list",
        responses={
            200: AssigneeListResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
        tags=["Operaciones"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"assignees": list_assignees(actor, organization_id)})


class EventListView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_events_list",
        parameters=[
            OpenApiParameter("from", str, required=False),
            OpenApiParameter("to", str, required=False),
            OpenApiParameter("status", str, many=True, required=False),
            OpenApiParameter("attention", str, required=False),
            OpenApiParameter("responsible_membership_id", UUID, required=False),
            OpenApiParameter("cursor", str, required=False),
            OpenApiParameter("page_size", int, required=False),
        ],
        responses={
            200: EventListResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
        tags=["Operaciones"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        raw = request.query_params.copy()
        if request.query_params.get("from"):
            raw["from_date"] = request.query_params["from"]
        if request.query_params.get("to"):
            raw["to_date"] = request.query_params["to"]
        raw.setlist("status", request.query_params.getlist("status"))
        serializer = EventListQuerySerializer(data=raw)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: list_events(
                actor,
                organization_id,
                from_date=data.get("from_date"),
                to_date=data.get("to_date"),
                statuses=data.get("status"),
                attention=data.get("attention"),
                responsible_membership_id=data.get("responsible_membership_id"),
                cursor=data.get("cursor"),
                page_size=data["page_size"],
            )
        )


class EventDetailView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_events_retrieve",
        responses={
            200: OperationEventDetailSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
        tags=["Operaciones"],
    )
    def get(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: read_event(actor, organization_id, reservation_id=reservation_id))


class PreparationUpdateView(OperationsAPIView):
    @extend_schema(
        request=PreparationUpdateSerializer,
        responses={
            200: OperationEventDetailSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones"],
    )
    def patch(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = PreparationUpdateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: update_preparation(
                actor,
                organization_id,
                reservation_id=reservation_id,
                revision=data["revision"],
                operational_notes=data["operational_notes"],
            )
        )


class AssignmentView(OperationsAPIView):
    @extend_schema(
        request=AssignmentSerializer,
        responses={
            200: OperationEventDetailSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = AssignmentSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: assign_preparation(
                actor,
                organization_id,
                reservation_id=reservation_id,
                revision=data["revision"],
                responsible_membership_id=data["responsible_membership_id"],
            )
        )


class ItemCreateView(OperationsAPIView):
    @extend_schema(
        request=ItemCreateSerializer,
        responses={
            200: ItemMutationResponseSerializer,
            201: ItemMutationResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = ItemCreateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = dict(serializer.validated_data)
        request_id = data.pop("client_request_id")
        place_before_item_id = data.pop("place_before_item_id", None)
        try:
            result, created = create_item(
                actor,
                organization_id,
                reservation_id=reservation_id,
                client_request_id=request_id,
                values=data,
                place_before_item_id=place_before_item_id,
            )
        except (TenantAccessDenied, AuthorizationDenied, OperationsError) as caught:
            return _exception_response(caught)
        return Response(result, status=201 if created else 200)


class ItemUpdateView(OperationsAPIView):
    @extend_schema(
        request=ItemUpdateSerializer,
        responses={
            200: ItemMutationResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones"],
    )
    def patch(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        item_id: UUID,
    ) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        if "resolved_at" in request.data or "resolved_by_membership_id" in request.data:
            return _error(
                "invalid_request", "La evidencia de resolución la asigna el servidor.", status=400
            )
        serializer = ItemUpdateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = dict(serializer.validated_data)
        revision = data.pop("revision")
        update_kwargs: dict[str, Any] = {}
        if "place_before_item_id" in data:
            update_kwargs["place_before_item_id"] = data.pop("place_before_item_id")
        return _respond(
            lambda: update_item(
                actor,
                organization_id,
                reservation_id=reservation_id,
                item_id=item_id,
                revision=revision,
                values=data,
                **update_kwargs,
            )
        )


class _TransitionView(OperationsAPIView):
    operation: Callable[..., dict[str, Any]]

    @extend_schema(
        request=RevisionSerializer,
        responses={
            200: OperationEventDetailSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = RevisionSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        return _respond(
            lambda: self.operation(
                actor,
                organization_id,
                reservation_id=reservation_id,
                revision=serializer.validated_data["revision"],
            )
        )


class ReadyView(_TransitionView):
    operation = staticmethod(mark_ready)


class StartView(_TransitionView):
    operation = staticmethod(start_event)


class CompleteView(_TransitionView):
    operation = staticmethod(complete_event)
