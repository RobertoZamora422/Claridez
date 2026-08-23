from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied

from .errors import ResourcesError
from .serializers import (
    ActiveSerializer,
    AssignmentActionSerializer,
    AssignmentCreateSerializer,
    CapabilitiesSerializer,
    ContactInactivateSerializer,
    ConversionCreateSerializer,
    EntitySerializer,
    ErrorSerializer,
    FinancialMaterializationSerializer,
    LocationCreateSerializer,
    MovementCreateSerializer,
    OverviewSerializer,
    PurchaseCreateSerializer,
    ReceiptLineCreateSerializer,
    RequirementCreateSerializer,
    ResourceCreateSerializer,
    SupplierContactCreateSerializer,
    SupplierCreateSerializer,
    SupplierOfferingCreateSerializer,
    SupplierTermCreateSerializer,
    UnavailabilityCreateSerializer,
    UnitCreateSerializer,
)
from .services import (
    add_supplier_offering,
    add_supplier_term,
    close_unavailability,
    confirm_receipt_line,
    create_conversion,
    create_location,
    create_purchase,
    create_requirement,
    create_resource,
    create_supplier,
    create_unit,
    execute_assignment,
    inactivate_supplier_contact,
    link_supplier_contact,
    record_movement,
    record_unavailability,
    reserve_resource,
    resources_capabilities,
    resources_overview,
    set_resource_active,
    set_supplier_active,
    set_supplier_offering_active,
)

ERROR = OpenApiResponse(response=ErrorSerializer, description="Error JSON fail-closed.")
SUCCESS = OpenApiResponse(response=EntitySerializer, description="Entidad o hecho P12 creado.")
IDEMPOTENCY_HEADER = OpenApiParameter(
    name="Idempotency-Key",
    type=UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    description="UUID estable para reintentos sin duplicar hechos P12.",
)


def _error(code: str, message: str, *, status: int) -> Response:
    response = Response({"error": {"code": code, "message": message}}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _actor(request: Request) -> User | None:
    actor = request._request.user
    return actor if isinstance(actor, User) and actor.is_authenticated else None


def _safe(value: Any) -> Any:
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def _respond(operation: Callable[[], Any], *, created: bool = False) -> Response:
    try:
        value = operation()
    except TenantAccessDenied:
        return _error("resource_not_available", "El recurso no está disponible.", status=404)
    except AuthorizationDenied:
        return _error("forbidden", "La operación no está autorizada.", status=403)
    except ResourcesError as error:
        return _error(error.code, error.message, status=error.status)
    except IntegrityError:
        return _error("concurrent_conflict", "La operación entró en conflicto.", status=409)
    response = Response(_safe(value), status=201 if created else 200)
    response["Cache-Control"] = "no-store"
    return response


def _validated(serializer: Any) -> Response | None:
    if serializer.is_valid():
        return None
    return _error("invalid_request", "La solicitud no es válida.", status=400)


def _key(request: Request) -> UUID | Response:
    try:
        return UUID(request.headers.get("Idempotency-Key", ""))
    except (ValueError, AttributeError):
        return _error(
            "invalid_idempotency_key", "Se requiere una Idempotency-Key UUID válida.", status=400
        )


def _entity(row: Any) -> dict[str, UUID]:
    return {"id": cast(UUID, row.pk)}


@method_decorator(csrf_protect, name="dispatch")
class ResourcesAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        return _actor(request) or _error(
            "authentication_required", "Se requiere una sesión válida.", status=401
        )


class CapabilitiesView(ResourcesAPIView):
    @extend_schema(
        responses={200: CapabilitiesSerializer, 401: ERROR, 404: ERROR}, tags=["Recursos"]
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(lambda: {"capabilities": resources_capabilities(actor, organization_id)})
        )


class OverviewView(ResourcesAPIView):
    @extend_schema(
        responses={200: OverviewSerializer, 401: ERROR, 403: ERROR, 404: ERROR}, tags=["Recursos"]
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(lambda: resources_overview(actor, organization_id))
        )


class CommandView(ResourcesAPIView):
    serializer_class: type[Any]
    operation: Callable[..., Any]

    @extend_schema(
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Recursos"],
    )
    def post(self, request: Request, organization_id: UUID, **path: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        key = _key(request)
        if isinstance(key, Response):
            return key
        serializer = self.serializer_class(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        values = dict(serializer.validated_data)
        values.update(path)
        return _respond(
            lambda: _entity(self.operation(actor, organization_id, **values, idempotency_key=key)),
            created=True,
        )


class UnitCreateView(CommandView):
    serializer_class = UnitCreateSerializer
    operation = staticmethod(create_unit)


class ConversionCreateView(CommandView):
    serializer_class = ConversionCreateSerializer
    operation = staticmethod(create_conversion)


class SupplierCreateView(CommandView):
    serializer_class = SupplierCreateSerializer
    operation = staticmethod(create_supplier)


class SupplierStatusView(CommandView):
    serializer_class = ActiveSerializer
    operation = staticmethod(set_supplier_active)


class SupplierContactView(CommandView):
    serializer_class = SupplierContactCreateSerializer
    operation = staticmethod(link_supplier_contact)


class SupplierContactInactivateView(CommandView):
    serializer_class = ContactInactivateSerializer
    operation = staticmethod(inactivate_supplier_contact)


class SupplierTermView(CommandView):
    serializer_class = SupplierTermCreateSerializer
    operation = staticmethod(add_supplier_term)


class SupplierOfferingView(CommandView):
    serializer_class = SupplierOfferingCreateSerializer
    operation = staticmethod(add_supplier_offering)


class SupplierOfferingStatusView(CommandView):
    serializer_class = ActiveSerializer
    operation = staticmethod(set_supplier_offering_active)


class ResourceCreateView(CommandView):
    serializer_class = ResourceCreateSerializer
    operation = staticmethod(create_resource)


class ResourceStatusView(CommandView):
    serializer_class = ActiveSerializer
    operation = staticmethod(set_resource_active)


class LocationCreateView(CommandView):
    serializer_class = LocationCreateSerializer
    operation = staticmethod(create_location)


class PurchaseCreateView(CommandView):
    serializer_class = PurchaseCreateSerializer
    operation = staticmethod(create_purchase)


class ReceiptLineView(CommandView):
    serializer_class = ReceiptLineCreateSerializer
    operation = staticmethod(confirm_receipt_line)


class MovementView(CommandView):
    serializer_class = MovementCreateSerializer
    operation = staticmethod(record_movement)


class RequirementView(CommandView):
    serializer_class = RequirementCreateSerializer
    operation = staticmethod(create_requirement)


class AssignmentView(CommandView):
    serializer_class = AssignmentCreateSerializer
    operation = staticmethod(reserve_resource)


class AssignmentActionView(CommandView):
    serializer_class = AssignmentActionSerializer
    operation = staticmethod(execute_assignment)


class UnavailabilityView(CommandView):
    serializer_class = UnavailabilityCreateSerializer
    operation = staticmethod(record_unavailability)


class EmptySerializer(serializers.Serializer[dict[str, object]]):
    pass


class UnavailabilityCloseView(CommandView):
    serializer_class = EmptySerializer
    operation = staticmethod(close_unavailability)


class FinancialMaterializationView(ResourcesAPIView):
    @extend_schema(
        parameters=[IDEMPOTENCY_HEADER],
        request=FinancialMaterializationSerializer,
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Recursos"],
    )
    def post(self, request: Request, organization_id: UUID, receipt_line_id: UUID) -> Response:
        from claridez.application.resources_finance import materialize_resources_receipt

        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        key = _key(request)
        if isinstance(key, Response):
            return key
        serializer = FinancialMaterializationSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        values = dict(serializer.validated_data)
        values["allocations"] = tuple(values.get("allocations", ()))
        return _respond(
            lambda: materialize_resources_receipt(
                actor,
                organization_id,
                receipt_line_id=receipt_line_id,
                idempotency_key=key,
                **values,
            ),
            created=True,
        )
