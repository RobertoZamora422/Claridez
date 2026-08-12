from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from claridez.identity.models import User
from claridez.operations.errors import OperationsError
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied

from .errors import SchedulingError
from .serializers import (
    AdvancedAvailabilitySerializer,
    AvailabilityResponseSerializer,
    BlockCreateSerializer,
    BlockListResponseSerializer,
    BlockResponseSerializer,
    BlockTerminationSerializer,
    CalendarQuerySerializer,
    CalendarResponseSerializer,
    DomainErrorSerializer,
    PolicyResponseSerializer,
    PolicySerializer,
    RescheduleResponseSerializer,
    RescheduleSerializer,
    ScheduleHistoryResponseSerializer,
    SchedulingCapabilitiesResponseSerializer,
)
from .services import (
    availability,
    calendar_entries,
    create_block,
    export_icalendar,
    list_blocks,
    read_policy,
    reschedule_reservation,
    schedule_history,
    scheduling_capabilities,
    terminate_block,
    update_policy,
)

ERROR = OpenApiResponse(response=DomainErrorSerializer, description="Error de dominio JSON seguro.")


def _error(code: str, message: str, *, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _actor(request: Request) -> User | None:
    user = request._request.user
    return user if isinstance(user, User) and user.is_authenticated else None


def _json_safe(value: Any) -> Any:
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
    except (SchedulingError, OperationsError) as error:
        return _error(error.code, error.message, status=error.status)
    return Response(_json_safe(result), status=201 if created else 200)


def _validated(serializer: Any) -> Response | None:
    if serializer.is_valid():
        return None
    return _error("invalid_request", "La solicitud no es válida.", status=400)


@method_decorator(csrf_protect, name="dispatch")
class SchedulingAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        actor = _actor(request)
        if actor is None:
            return _error("authentication_required", "Se requiere una sesión válida.", status=401)
        return actor


class SchedulingCapabilitiesView(SchedulingAPIView):
    @extend_schema(
        tags=["Agenda"],
        responses={200: SchedulingCapabilitiesResponseSerializer, 401: ERROR, 404: ERROR},
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"capabilities": scheduling_capabilities(actor, organization_id)})


class CalendarView(SchedulingAPIView):
    @extend_schema(
        tags=["Agenda"],
        parameters=[CalendarQuerySerializer],
        responses={200: CalendarResponseSerializer, 400: ERROR, 403: ERROR},
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = CalendarQuerySerializer(data=request.query_params)
        error = _validated(serializer)
        if error:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: calendar_entries(
                actor,
                organization_id,
                view=data["view"],
                anchor_date=data["anchor_date"],
                venue_id=data.get("venue_id"),
                space_id=data.get("space_id"),
                types=tuple(data.get("types", ())),
            )
        )


class AvailabilityView(SchedulingAPIView):
    @extend_schema(
        tags=["Agenda"],
        request=AdvancedAvailabilitySerializer,
        responses={200: AvailabilityResponseSerializer, 400: ERROR, 409: ERROR},
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = AdvancedAvailabilitySerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: availability(
                actor,
                organization_id,
                starts_at_local=data["starts_at_local"],
                ends_at_local=data["ends_at_local"],
                timezone_name=data["timezone"],
                space_ids=tuple(data["space_ids"]),
            )
        )


class PolicyView(SchedulingAPIView):
    @extend_schema(tags=["Agenda"], responses={200: PolicyResponseSerializer, 404: ERROR})
    def get(self, request: Request, organization_id: UUID, space_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: read_policy(actor, organization_id, space_id=space_id))

    @extend_schema(
        tags=["Agenda"],
        request=PolicySerializer,
        responses={200: PolicyResponseSerializer, 409: ERROR},
    )
    def patch(self, request: Request, organization_id: UUID, space_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = PolicySerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: update_policy(
                actor, organization_id, space_id=space_id, **serializer.validated_data
            )
        )


class BlockListCreateView(SchedulingAPIView):
    @extend_schema(tags=["Agenda"], responses={200: BlockListResponseSerializer})
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"results": list_blocks(actor, organization_id)})

    @extend_schema(
        tags=["Agenda"],
        request=BlockCreateSerializer,
        responses={200: BlockResponseSerializer, 201: BlockResponseSerializer, 409: ERROR},
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = BlockCreateSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        try:
            data = serializer.validated_data
            result, created = create_block(
                actor,
                organization_id,
                idempotency_key=data["idempotency_key"],
                scope=data["scope"],
                venue_id=data["venue_id"],
                space_ids=tuple(data.get("space_ids", ())),
                starts_at_local=data["starts_at_local"],
                ends_at_local=data["ends_at_local"],
                timezone_name=data["timezone"],
                reason=data["reason"],
            )
        except (TenantAccessDenied, AuthorizationDenied, SchedulingError) as domain_error:
            if isinstance(domain_error, TenantAccessDenied):
                return _error(
                    "resource_not_available", "El recurso no está disponible.", status=404
                )
            if isinstance(domain_error, AuthorizationDenied):
                return _error("forbidden", "La operación no está autorizada.", status=403)
            return _error(domain_error.code, domain_error.message, status=domain_error.status)
        return Response(_json_safe(result), status=201 if created else 200)


class BlockTerminationView(SchedulingAPIView):
    action = "release"

    @extend_schema(
        tags=["Agenda"],
        request=BlockTerminationSerializer,
        responses={200: BlockResponseSerializer, 409: ERROR},
    )
    def post(self, request: Request, organization_id: UUID, block_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = BlockTerminationSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: terminate_block(
                actor,
                organization_id,
                block_id=block_id,
                action=self.action,
                **serializer.validated_data,
            )
        )


class BlockReleaseView(BlockTerminationView):
    action = "release"


class BlockCancelView(BlockTerminationView):
    action = "cancel"


class RescheduleView(SchedulingAPIView):
    @extend_schema(
        tags=["Agenda"],
        request=RescheduleSerializer,
        responses={200: RescheduleResponseSerializer, 409: ERROR},
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = RescheduleSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: reschedule_reservation(
                actor,
                organization_id,
                reservation_id=reservation_id,
                revision=data["revision"],
                idempotency_key=data["idempotency_key"],
                space_id=data["space_id"],
                starts_at_local=data["starts_at_local"],
                ends_at_local=data["ends_at_local"],
                timezone_name=data["timezone"],
                reason=data["reason"],
                commercial_terms_unchanged=data["commercial_terms_unchanged"],
                carry_free_item_ids=tuple(data.get("carry_free_item_ids", ())),
            )
        )


class ScheduleHistoryView(SchedulingAPIView):
    @extend_schema(tags=["Agenda"], responses={200: ScheduleHistoryResponseSerializer, 404: ERROR})
    def get(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: {
                "results": schedule_history(actor, organization_id, reservation_id=reservation_id)
            }
        )


class CalendarExportView(SchedulingAPIView):
    @extend_schema(
        tags=["Agenda"],
        parameters=[CalendarQuerySerializer],
        responses={(200, "text/calendar"): OpenApiResponse(description="iCalendar")},
    )
    def get(self, request: Request, organization_id: UUID) -> Response | HttpResponse:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = CalendarQuerySerializer(data=request.query_params)
        error = _validated(serializer)
        if error:
            return error
        data = serializer.validated_data
        try:
            body = export_icalendar(
                actor,
                organization_id,
                view=data["view"],
                anchor_date=data["anchor_date"],
                venue_id=data.get("venue_id"),
                space_id=data.get("space_id"),
            )
        except SchedulingError as domain_error:
            return _error(domain_error.code, domain_error.message, status=domain_error.status)
        response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="claridez-agenda.ics"'
        return response
