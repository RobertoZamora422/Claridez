from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied

from .errors import CommercialError
from .serializers import (
    AvailabilityQuerySerializer,
    EventRequestCreateSerializer,
    EventRequestUpdateSerializer,
    PersonCreateSerializer,
    PersonUpdateSerializer,
    QuotationAcceptSerializer,
    QuotationCreateSerializer,
    QuotationDraftSerializer,
    ReasonSerializer,
    ReservationConfirmSerializer,
)
from .services import (
    accept_quotation_version,
    cancel_reservation,
    close_event_request,
    commercial_capabilities,
    confirm_reservation,
    create_event_request,
    create_person,
    create_quotation,
    create_quotation_version,
    issue_quotation_version,
    list_availability,
    list_event_requests,
    list_people,
    list_person_revisions,
    read_event_request,
    read_person,
    read_quotation,
    read_reservation,
    replace_quotation_draft,
    update_event_request,
    update_person,
)

SUCCESS = OpenApiResponse(description="Respuesta materializada dentro del tenant autorizado.")
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
    except CommercialError as error:
        return _error(error.code, error.message, status=error.status)
    return Response(_json_safe(result), status=201 if created else 200)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _validated(serializer: Any) -> Response | None:
    if serializer.is_valid():
        return None
    return _error("invalid_request", "La solicitud no es válida.", status=400)


@method_decorator(csrf_protect, name="dispatch")
class CommercialAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        actor = _actor(request)
        if actor is None:
            return _error("authentication_required", "Se requiere una sesión válida.", status=401)
        return actor


class CommercialCapabilitiesView(CommercialAPIView):
    @extend_schema(responses={200: SUCCESS, 401: ERROR, 404: ERROR}, tags=["Comercial"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"capabilities": commercial_capabilities(actor, organization_id)})


class PersonListCreateView(CommercialAPIView):
    @extend_schema(
        operation_id="commercial_people_list",
        parameters=[OpenApiParameter("q", str, required=False)],
        responses={200: SUCCESS, 401: ERROR, 403: ERROR, 404: ERROR},
        tags=["Personas"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: {
                "people": list_people(
                    actor, organization_id, query=request.query_params.get("q", "")
                )
            }
        )

    @extend_schema(
        request=PersonCreateSerializer,
        responses={201: SUCCESS, 400: ERROR, 409: ERROR},
        tags=["Personas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = PersonCreateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: create_person(
                actor,
                organization_id,
                full_name=str(data["full_name"]),
                phone=str(data["phone"]),
                email=data.get("email"),
                origin=str(data["origin"]),
                origin_detail=data.get("origin_detail"),
            ),
            created=True,
        )


class PersonDetailView(CommercialAPIView):
    @extend_schema(
        operation_id="commercial_people_retrieve",
        responses={200: SUCCESS, 404: ERROR},
        tags=["Personas"],
    )
    def get(self, request: Request, organization_id: UUID, person_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: read_person(actor, organization_id, person_id=person_id))

    @extend_schema(
        request=PersonUpdateSerializer,
        responses={200: SUCCESS, 400: ERROR, 409: ERROR},
        tags=["Personas"],
    )
    def patch(self, request: Request, organization_id: UUID, person_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = PersonUpdateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = dict(serializer.validated_data)
        revision = int(data.pop("revision"))
        return _respond(
            lambda: update_person(
                actor,
                organization_id,
                person_id=person_id,
                revision=revision,
                changes=data,
            )
        )


class PersonRevisionListView(CommercialAPIView):
    @extend_schema(responses={200: SUCCESS, 404: ERROR}, tags=["Personas"])
    def get(self, request: Request, organization_id: UUID, person_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: {
                "revisions": list_person_revisions(actor, organization_id, person_id=person_id)
            }
        )


class EventRequestListCreateView(CommercialAPIView):
    @extend_schema(
        operation_id="commercial_event_requests_list",
        parameters=[OpenApiParameter("status", str, required=False)],
        responses={200: SUCCESS, 401: ERROR, 403: ERROR},
        tags=["Solicitudes"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: {
                "event_requests": list_event_requests(
                    actor, organization_id, status=request.query_params.get("status", "")
                )
            }
        )

    @extend_schema(
        request=EventRequestCreateSerializer,
        responses={201: SUCCESS, 400: ERROR},
        tags=["Solicitudes"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = EventRequestCreateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: create_event_request(
                actor,
                organization_id,
                person_id=data["person_id"],
                event_type=str(data["event_type"]),
                starts_at=data["starts_at"],
                ends_at=data["ends_at"],
                estimated_guests=int(data["estimated_guests"]),
                general_need=str(data["general_need"]),
                notes=str(data.get("notes", "")),
                origin=str(data["origin"]),
                origin_detail=data.get("origin_detail"),
                responsible_membership_id=data.get("responsible_membership_id"),
            ),
            created=True,
        )


class EventRequestDetailView(CommercialAPIView):
    @extend_schema(
        operation_id="commercial_event_requests_retrieve",
        responses={200: SUCCESS, 404: ERROR},
        tags=["Solicitudes"],
    )
    def get(self, request: Request, organization_id: UUID, event_request_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: read_event_request(actor, organization_id, request_id=event_request_id)
        )

    @extend_schema(
        request=EventRequestUpdateSerializer,
        responses={200: SUCCESS, 400: ERROR, 409: ERROR},
        tags=["Solicitudes"],
    )
    def patch(self, request: Request, organization_id: UUID, event_request_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = EventRequestUpdateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = dict(serializer.validated_data)
        revision = int(data.pop("revision"))
        return _respond(
            lambda: update_event_request(
                actor,
                organization_id,
                request_id=event_request_id,
                revision=revision,
                changes=data,
            )
        )


class EventRequestCloseView(CommercialAPIView):
    @extend_schema(
        request=ReasonSerializer,
        responses={200: SUCCESS, 400: ERROR, 409: ERROR},
        tags=["Solicitudes"],
    )
    def post(self, request: Request, organization_id: UUID, event_request_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = ReasonSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        return _respond(
            lambda: close_event_request(
                actor,
                organization_id,
                request_id=event_request_id,
                reason=serializer.validated_data["reason"],
            )
        )


class AvailabilityView(CommercialAPIView):
    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, required=True),
            OpenApiParameter("to", str, required=True),
        ],
        responses={200: SUCCESS, 400: ERROR},
        tags=["Disponibilidad"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = AvailabilityQuerySerializer(
            data={
                "starts_at": request.query_params.get("from"),
                "ends_at": request.query_params.get("to"),
            }
        )
        if (error := _validated(serializer)) is not None:
            return error
        return _respond(
            lambda: list_availability(
                actor,
                organization_id,
                starts_at=serializer.validated_data["starts_at"],
                ends_at=serializer.validated_data["ends_at"],
            )
        )


class RequestQuotationCreateView(CommercialAPIView):
    @extend_schema(
        request=QuotationCreateSerializer,
        responses={201: SUCCESS, 400: ERROR, 409: ERROR},
        tags=["Cotizaciones"],
    )
    def post(self, request: Request, organization_id: UUID, event_request_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = QuotationCreateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        return _respond(
            lambda: create_quotation(
                actor,
                organization_id,
                request_id=event_request_id,
                valid_until=serializer.validated_data["valid_until"],
            ),
            created=True,
        )


class QuotationDetailView(CommercialAPIView):
    @extend_schema(responses={200: SUCCESS, 404: ERROR}, tags=["Cotizaciones"])
    def get(self, request: Request, organization_id: UUID, quotation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: read_quotation(actor, organization_id, quotation_id=quotation_id))


class QuotationVersionCreateView(CommercialAPIView):
    @extend_schema(
        request=QuotationCreateSerializer,
        responses={201: SUCCESS, 400: ERROR, 409: ERROR},
        tags=["Cotizaciones"],
    )
    def post(self, request: Request, organization_id: UUID, quotation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = QuotationCreateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        return _respond(
            lambda: create_quotation_version(
                actor,
                organization_id,
                quotation_id=quotation_id,
                valid_until=serializer.validated_data["valid_until"],
            ),
            created=True,
        )


class QuotationVersionDetailView(CommercialAPIView):
    @extend_schema(
        request=QuotationDraftSerializer,
        responses={200: SUCCESS, 400: ERROR, 409: ERROR},
        tags=["Cotizaciones"],
    )
    def put(
        self, request: Request, organization_id: UUID, quotation_id: UUID, version: int
    ) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = QuotationDraftSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: replace_quotation_draft(
                actor,
                organization_id,
                quotation_id=quotation_id,
                version=version,
                revision=int(data["revision"]),
                valid_until=data["valid_until"],
                notes=str(data.get("notes", "")),
                lines=data["lines"],
            )
        )


class QuotationIssueView(CommercialAPIView):
    @extend_schema(request=None, responses={200: SUCCESS, 409: ERROR}, tags=["Cotizaciones"])
    def post(
        self, request: Request, organization_id: UUID, quotation_id: UUID, version: int
    ) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: issue_quotation_version(
                actor, organization_id, quotation_id=quotation_id, version=version
            )
        )


class QuotationAcceptView(CommercialAPIView):
    @extend_schema(
        request=QuotationAcceptSerializer,
        responses={200: SUCCESS, 400: ERROR, 409: ERROR},
        tags=["Cotizaciones"],
    )
    def post(
        self, request: Request, organization_id: UUID, quotation_id: UUID, version: int
    ) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = QuotationAcceptSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        return _respond(
            lambda: accept_quotation_version(
                actor,
                organization_id,
                quotation_id=quotation_id,
                version=version,
                channel=serializer.validated_data["channel"],
                note=serializer.validated_data.get("note", ""),
            )
        )


class ReservationDetailView(CommercialAPIView):
    @extend_schema(responses={200: SUCCESS, 404: ERROR}, tags=["Reservas"])
    def get(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: read_reservation(actor, organization_id, reservation_id=reservation_id)
        )


class ReservationConfirmView(CommercialAPIView):
    @extend_schema(
        request=ReservationConfirmSerializer,
        responses={200: SUCCESS, 400: ERROR, 403: ERROR, 409: ERROR},
        tags=["Reservas"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = ReservationConfirmSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: confirm_reservation(
                actor,
                organization_id,
                reservation_id=reservation_id,
                kind=str(data["kind"]),
                recognized_amount=data.get("recognized_amount"),
                reported_at=data.get("reported_at"),
                reference=str(data.get("reference", "")),
                waiver_reason=str(data.get("waiver_reason", "")),
            )
        )


class ReservationCancelView(CommercialAPIView):
    @extend_schema(
        request=ReasonSerializer,
        responses={200: SUCCESS, 400: ERROR, 409: ERROR},
        tags=["Reservas"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = ReasonSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        return _respond(
            lambda: cancel_reservation(
                actor,
                organization_id,
                reservation_id=reservation_id,
                reason=serializer.validated_data["reason"],
            )
        )
