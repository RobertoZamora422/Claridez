from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

import claridez.documents.public as documents_port
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied
from claridez.organizations.tenant_scope import authorized_tenant_scope

from .errors import ReceivablesError
from .models import (
    FinancialEvidenceLink,
    Receipt,
    ReceivedPayment,
)
from .serializers import (
    AdjustmentCreateSerializer,
    AdjustmentProjectionSerializer,
    AgingResponseSerializer,
    ApplicationCreateSerializer,
    ApplicationProjectionSerializer,
    CommercialSummaryResponseSerializer,
    EvidenceListResponseSerializer,
    EvidenceProjectionSerializer,
    FinancialEvidenceUploadSerializer,
    ObligationProjectionSerializer,
    PaymentCreateSerializer,
    PaymentProjectionSerializer,
    PaymentsResponseSerializer,
    PortfolioResponseSerializer,
    ReceiptProjectionSerializer,
    ReceivablesCapabilitiesResponseSerializer,
    ReceivablesErrorSerializer,
    RefundCreateSerializer,
    RefundProjectionSerializer,
    ReversalCreateSerializer,
    ReversalProjectionSerializer,
    ScheduleCommandResponseSerializer,
    ScheduleRevisionSerializer,
    StatementResponseSerializer,
)
from .services import (
    aging,
    application_data,
    apply_payment_authorized,
    commercial_summary,
    issue_receipt_authorized,
    payment_data,
    payment_detail_authorized,
    payments_data_authorized,
    portfolio,
    read_obligation,
    read_statement,
    receivables_capabilities,
    record_adjustment_authorized,
    record_payment_authorized,
    record_refund_authorized,
    reverse_movement_authorized,
    revise_schedule_authorized,
)

ERROR = OpenApiResponse(response=ReceivablesErrorSerializer, description="Error JSON fail-closed.")


def _success(response: type[Any], description: str) -> OpenApiResponse:
    return OpenApiResponse(response=response, description=description)


IDEMPOTENCY_HEADER = OpenApiParameter(
    name="Idempotency-Key",
    type=UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    description="UUID estable para reintentos sin duplicar dinero ni evidencia.",
)


def _error(code: str, message: str, *, status: int) -> Response:
    response = Response({"error": {"code": code, "message": message}}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _actor(request: Request) -> User | None:
    actor = request._request.user
    return actor if isinstance(actor, User) and actor.is_authenticated else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, ".2f")
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
    except ReceivablesError as error:
        return _error(error.code, error.message, status=error.status)
    except documents_port.DocumentsPortError as error:
        return _error(error.code, error.detail, status=error.status_code)
    except IntegrityError:
        return _error("concurrent_conflict", "La operación entró en conflicto.", status=409)
    response = Response(_json_safe(result), status=201 if created else 200)
    response["Cache-Control"] = "no-store"
    return response


def _validated(serializer: Any) -> Response | None:
    if serializer.is_valid():
        return None
    return _error("invalid_request", "La solicitud no es válida.", status=400)


def _idempotency_key(request: Request) -> UUID | Response:
    raw = request.headers.get("Idempotency-Key", "")
    try:
        return UUID(raw)
    except (ValueError, AttributeError):
        return _error(
            "invalid_idempotency_key",
            "Se requiere una Idempotency-Key UUID válida.",
            status=400,
        )


@method_decorator(csrf_protect, name="dispatch")
class ReceivablesAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        actor = _actor(request)
        if actor is None:
            return _error("authentication_required", "Se requiere una sesión válida.", status=401)
        return actor


class CapabilitiesView(ReceivablesAPIView):
    @extend_schema(
        responses={
            200: _success(ReceivablesCapabilitiesResponseSerializer, "Capabilities P10 efectivas."),
            401: ERROR,
            404: ERROR,
        },
        tags=["Cartera"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"capabilities": receivables_capabilities(actor, organization_id)})


class PortfolioView(ReceivablesAPIView):
    @extend_schema(
        responses={
            200: _success(PortfolioResponseSerializer, "Cartera derivada por moneda."),
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Cartera"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(lambda: portfolio(actor, organization_id))
        )


class AgingView(ReceivablesAPIView):
    @extend_schema(
        responses={
            200: _success(AgingResponseSerializer, "Antigüedad con días exactos y buckets P10."),
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Cartera"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(lambda: aging(actor, organization_id))
        )


class ObligationView(ReceivablesAPIView):
    @extend_schema(
        responses={
            200: _success(ObligationProjectionSerializer, "Obligación y saldo derivados."),
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Cartera"],
    )
    def get(self, request: Request, organization_id: UUID, obligation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(
                lambda: read_obligation(actor, organization_id, obligation_id=obligation_id)
            )
        )


class StatementView(ReceivablesAPIView):
    @extend_schema(
        responses={
            200: _success(StatementResponseSerializer, "Estado de cuenta reconstruible."),
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Cartera"],
    )
    def get(self, request: Request, organization_id: UUID, obligation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(
                lambda: read_statement(actor, organization_id, obligation_id=obligation_id)
            )
        )


class CommercialSummaryView(ReceivablesAPIView):
    @extend_schema(
        responses={
            200: _success(
                CommercialSummaryResponseSerializer, "Resumen financiero mínimo para Comercial."
            ),
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Cartera"],
    )
    def get(self, request: Request, organization_id: UUID, root_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(
                lambda: commercial_summary(actor, organization_id, root_reservation_id=root_id)
            )
        )


class ScheduleView(ReceivablesAPIView):
    @extend_schema(
        responses={
            200: _success(ObligationProjectionSerializer, "Calendario vigente de la obligación."),
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Cartera"],
    )
    def get(self, request: Request, organization_id: UUID, obligation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(
                lambda: read_obligation(actor, organization_id, obligation_id=obligation_id)
            )
        )

    @extend_schema(
        request=ScheduleRevisionSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={
            201: _success(ScheduleCommandResponseSerializer, "Revisión append-only creada."),
            400: ERROR,
            401: ERROR,
            403: ERROR,
            404: ERROR,
            409: ERROR,
        },
        tags=["Cartera"],
    )
    def post(self, request: Request, organization_id: UUID, obligation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        key = _idempotency_key(request)
        if isinstance(key, Response):
            return key
        serializer = ScheduleRevisionSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data
        return _respond(
            lambda: _schedule_command(actor, organization_id, obligation_id, data, key),
            created=True,
        )


def _schedule_command(
    actor: User,
    organization_id: UUID,
    obligation_id: UUID,
    data: dict[str, object],
    key: UUID,
) -> dict[str, object]:
    with authorized_tenant_scope(
        actor, organization_id, Capability.RECEIVABLES_MANAGE_SCHEDULE
    ) as authorization:
        row = revise_schedule_authorized(
            authorization,
            obligation_id=obligation_id,
            dues=cast(list[dict[str, object]], data["dues"]),
            provenance=str(data["provenance"]),
            reason=str(data["reason"]),
            idempotency_key=key,
        )
        return {"id": row.pk, "obligation_id": row.obligation_id, "revision": row.revision}


class PaymentsView(ReceivablesAPIView):
    @extend_schema(
        operation_id="receivables_payments_list",
        responses={
            200: _success(PaymentsResponseSerializer, "Pagos externos y montos sin aplicar."),
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Pagos"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_READ
            ) as authorization:
                return payments_data_authorized(authorization)

        return _respond(operation)

    @extend_schema(
        operation_id="receivables_payments_record",
        request=PaymentCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={
            201: _success(PaymentProjectionSerializer, "Pago externo registrado."),
            400: ERROR,
            401: ERROR,
            403: ERROR,
            404: ERROR,
            409: ERROR,
        },
        tags=["Pagos"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        key = _idempotency_key(request)
        if isinstance(key, Response):
            return key
        serializer = PaymentCreateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_RECORD_PAYMENT
            ) as authorization:
                row = record_payment_authorized(
                    authorization,
                    counterparty_person_id=cast(UUID, data["counterparty_person_id"]),
                    root_reservation_id=cast(UUID | None, data.get("root_reservation_id")),
                    event_request_id=cast(UUID | None, data.get("event_request_id")),
                    amount_value=cast(Decimal, data["amount"]),
                    currency_value=str(data["currency"]),
                    reported_at=cast(Any, data["reported_at"]),
                    method=str(data["method"]),
                    reference=str(data.get("reference", "")),
                    observation=str(data.get("observation", "")),
                    provenance=ReceivedPayment.Provenance.MANUAL,
                    evidence_level=str(data["evidence_level"]),
                    duplicate_review_note=str(data.get("duplicate_review_note", "")),
                    idempotency_key=key,
                )
                return payment_data(row)

        return _respond(operation, created=True)


class PaymentView(ReceivablesAPIView):
    @extend_schema(
        operation_id="receivables_payments_retrieve",
        responses={
            200: _success(PaymentProjectionSerializer, "Pago con aplicaciones."),
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Pagos"],
    )
    def get(self, request: Request, organization_id: UUID, payment_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_READ
            ) as authorization:
                return payment_detail_authorized(authorization, payment_id)

        return _respond(operation)


class PaymentEvidenceView(ReceivablesAPIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="receivables_payment_evidence_list",
        responses={
            200: _success(EvidenceListResponseSerializer, "Evidencia privada vinculada al pago."),
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Pagos"],
    )
    def get(self, request: Request, organization_id: UUID, payment_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_READ
            ) as authorization:
                if not ReceivedPayment.objects.filter(
                    organization_id=organization_id, pk=payment_id
                ).exists():
                    raise ReceivablesError(
                        "resource_not_available", "El pago no está disponible.", status=404
                    )
                return {
                    "evidence": [
                        {
                            "id": item.id,
                            "display_name": item.display_name,
                            "media_type": item.media_type,
                            "sha256": item.sha256,
                            "size_bytes": item.size_bytes,
                            "state": item.state,
                        }
                        for item in documents_port.list_payment_supports(authorization, payment_id)
                    ]
                }

        return _respond(operation)

    @extend_schema(
        operation_id="receivables_payment_evidence_upload",
        request=FinancialEvidenceUploadSerializer,
        responses={
            202: _success(EvidenceProjectionSerializer, "Archivo recibido en cuarentena."),
            400: ERROR,
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Pagos"],
    )
    def post(self, request: Request, organization_id: UUID, payment_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = FinancialEvidenceUploadSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        upload = serializer.validated_data["file"]

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_RECORD_PAYMENT
            ) as authorization:
                try:
                    payment = ReceivedPayment.objects.get(
                        organization_id=organization_id, pk=payment_id
                    )
                except ReceivedPayment.DoesNotExist:
                    raise ReceivablesError(
                        "resource_not_available", "El pago no está disponible.", status=404
                    ) from None
                item = documents_port.receive_payment_support(
                    authorization,
                    payment_id=payment.pk,
                    display_name=upload.name,
                    declared_media_type=upload.content_type or "application/octet-stream",
                    source=upload,
                    correlation_id=request.headers.get("X-Correlation-ID", str(UUID(int=0))),
                )
                FinancialEvidenceLink.objects.create(
                    organization_id=organization_id,
                    owner_type="payment",
                    owner_id=payment.pk,
                    document_file_id=item.id,
                    evidence_purpose="external_support",
                    linked_by_membership_id=authorization.membership_id,
                )
                return {
                    "id": item.id,
                    "display_name": item.display_name,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                    "state": item.state,
                    "meaning": "evidencia adjunta; no verifica ni crea el pago",
                }

        response = _respond(operation, created=True)
        if response.status_code == 201:
            response.status_code = 202
        return response


class PaymentEvidenceDownloadView(ReceivablesAPIView):
    @extend_schema(
        operation_id="receivables_payment_evidence_download",
        responses={200: bytes, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Pagos"],
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        payment_id: UUID,
        evidence_id: UUID,
    ) -> HttpResponse:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        try:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_READ
            ) as authorization:
                linked = FinancialEvidenceLink.objects.filter(
                    organization_id=organization_id,
                    owner_type="payment",
                    owner_id=payment_id,
                    document_file_id=evidence_id,
                ).exists()
                if not linked:
                    raise ReceivablesError(
                        "resource_not_available", "La evidencia no está disponible.", status=404
                    )
                content, media_type, filename = documents_port.download_payment_support(
                    authorization, payment_id=payment_id, file_id=evidence_id
                )
        except (AuthorizationDenied, TenantAccessDenied):
            return _error("forbidden", "La operación no está autorizada.", status=403)
        except ReceivablesError as error:
            return _error(error.code, error.message, status=error.status)
        except documents_port.DocumentsPortError as error:
            return _error(error.code, error.detail, status=error.status_code)
        response = HttpResponse(content, content_type=media_type)
        response["Content-Disposition"] = content_disposition_header(True, filename) or "attachment"
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class ApplicationsView(ReceivablesAPIView):
    @extend_schema(
        request=ApplicationCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={
            201: _success(ApplicationProjectionSerializer, "Aplicación append-only creada."),
            400: ERROR,
            401: ERROR,
            403: ERROR,
            404: ERROR,
            409: ERROR,
        },
        tags=["Pagos"],
    )
    def post(self, request: Request, organization_id: UUID, payment_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        key = _idempotency_key(request)
        if isinstance(key, Response):
            return key
        serializer = ApplicationCreateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_APPLY_PAYMENT
            ) as authorization:
                row = apply_payment_authorized(
                    authorization,
                    payment_id=payment_id,
                    obligation_id=cast(UUID, data["obligation_id"]),
                    due_key=cast(UUID | None, data.get("due_key")),
                    amount_value=cast(Decimal, data["amount"]),
                    idempotency_key=key,
                )
                return application_data(row)

        return _respond(operation, created=True)


class AdjustmentsView(ReceivablesAPIView):
    @extend_schema(
        request=AdjustmentCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={
            201: _success(AdjustmentProjectionSerializer, "Ajuste append-only creado."),
            400: ERROR,
            401: ERROR,
            403: ERROR,
            404: ERROR,
            409: ERROR,
        },
        tags=["Cartera"],
    )
    def post(self, request: Request, organization_id: UUID, obligation_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        key = _idempotency_key(request)
        if isinstance(key, Response):
            return key
        serializer = AdjustmentCreateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_RECORD_ADJUSTMENT
            ) as authorization:
                row = record_adjustment_authorized(
                    authorization,
                    obligation_id=obligation_id,
                    direction=str(data["direction"]),
                    amount_value=cast(Decimal, data["amount"]),
                    currency_value=str(data["currency"]),
                    reason=str(data["reason"]),
                    correlation_reference=str(data.get("correlation_reference", "")),
                    evidence_reference=str(data.get("evidence_reference", "")),
                    idempotency_key=key,
                )
                return {
                    "id": row.pk,
                    "obligation_id": row.obligation_id,
                    "direction": row.direction,
                    "amount": row.amount,
                    "currency": row.currency,
                    "reason": row.reason,
                    "occurred_at": row.occurred_at,
                }

        return _respond(operation, created=True)


class ReversalView(ReceivablesAPIView):
    @extend_schema(
        request=ReversalCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={
            201: _success(ReversalProjectionSerializer, "Reverso completo creado."),
            400: ERROR,
            401: ERROR,
            403: ERROR,
            404: ERROR,
            409: ERROR,
        },
        tags=["Cartera"],
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        target_kind: str,
        target_id: UUID,
    ) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        key = _idempotency_key(request)
        if isinstance(key, Response):
            return key
        serializer = ReversalCreateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_REVERSE_MOVEMENT
            ) as authorization:
                row = reverse_movement_authorized(
                    authorization,
                    target_kind=target_kind,
                    target_id=target_id,
                    reason=str(serializer.validated_data["reason"]),
                    idempotency_key=key,
                )
                return {
                    "id": row.pk,
                    "target_kind": row.target_kind,
                    "target_id": row.target_id,
                    "amount": row.amount,
                    "currency": row.currency,
                    "reason": row.reason,
                    "reversed_at": row.reversed_at,
                }

        return _respond(operation, created=True)


class RefundsView(ReceivablesAPIView):
    @extend_schema(
        request=RefundCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={
            201: _success(RefundProjectionSerializer, "Devolución externa registrada."),
            400: ERROR,
            401: ERROR,
            403: ERROR,
            404: ERROR,
            409: ERROR,
        },
        tags=["Pagos"],
    )
    def post(self, request: Request, organization_id: UUID, payment_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        key = _idempotency_key(request)
        if isinstance(key, Response):
            return key
        serializer = RefundCreateSerializer(data=request.data)
        if (error := _validated(serializer)) is not None:
            return error
        data = serializer.validated_data

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_RECORD_REFUND
            ) as authorization:
                row = record_refund_authorized(
                    authorization,
                    payment_id=payment_id,
                    obligation_id=cast(UUID | None, data.get("obligation_id")),
                    amount_value=cast(Decimal, data["amount"]),
                    currency_value=str(data["currency"]),
                    refunded_at=cast(Any, data["refunded_at"]),
                    method=str(data["method"]),
                    reference=str(data.get("reference", "")),
                    reason=str(data["reason"]),
                    evidence_reference=str(data.get("evidence_reference", "")),
                    allocations=cast(list[dict[str, object]], data["allocations"]),
                    idempotency_key=key,
                )
                return {
                    "id": row.pk,
                    "payment_id": row.payment_id,
                    "obligation_id": row.obligation_id,
                    "amount": row.amount,
                    "currency": row.currency,
                    "refunded_at": row.refunded_at,
                    "reason": row.reason,
                }

        return _respond(operation, created=True)


class ReceiptsView(ReceivablesAPIView):
    @extend_schema(
        request=None,
        parameters=[IDEMPOTENCY_HEADER],
        responses={
            201: _success(ReceiptProjectionSerializer, "Recibo lógico emitido; no factura."),
            400: ERROR,
            401: ERROR,
            403: ERROR,
            404: ERROR,
            409: ERROR,
        },
        tags=["Recibos"],
    )
    def post(self, request: Request, organization_id: UUID, payment_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        key = _idempotency_key(request)
        if isinstance(key, Response):
            return key

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_ISSUE_RECEIPT
            ) as authorization:
                row = issue_receipt_authorized(
                    authorization, payment_id=payment_id, idempotency_key=key
                )
                return receipt_data(row)

        return _respond(operation, created=True)


def receipt_data(row: Receipt) -> dict[str, object]:
    return {
        "id": row.pk,
        "visible_number": row.visible_number,
        "year": row.year,
        "sequence": row.sequence,
        "payment_id": row.payment_id,
        "obligation_id": row.obligation_id,
        "snapshot": row.snapshot,
        "snapshot_sha256": row.snapshot_sha256,
        "issued_at": row.issued_at,
        "document_artifact_id": row.document_artifact_id,
        "label": "recibo/comprobante de cobro — no factura",
    }


class ReceiptView(ReceivablesAPIView):
    @extend_schema(
        responses={
            200: _success(ReceiptProjectionSerializer, "Recibo lógico inmutable; no factura."),
            401: ERROR,
            403: ERROR,
            404: ERROR,
        },
        tags=["Recibos"],
    )
    def get(self, request: Request, organization_id: UUID, receipt_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor

        def operation() -> dict[str, object]:
            with authorized_tenant_scope(actor, organization_id, Capability.RECEIVABLES_READ):
                try:
                    row = Receipt.objects.get(organization_id=organization_id, pk=receipt_id)
                except Receipt.DoesNotExist:
                    raise ReceivablesError(
                        "resource_not_available", "El recibo no está disponible.", status=404
                    ) from None
                return receipt_data(row)

        return _respond(operation)


class ReceiptPdfView(ReceivablesAPIView):
    @extend_schema(
        operation_id="receivables_receipt_pdf_download",
        responses={200: bytes, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Recibos"],
    )
    def get(self, request: Request, organization_id: UUID, receipt_id: UUID) -> HttpResponse:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        try:
            with authorized_tenant_scope(
                actor, organization_id, Capability.RECEIVABLES_READ
            ) as authorization:
                try:
                    row = Receipt.objects.get(organization_id=organization_id, pk=receipt_id)
                except Receipt.DoesNotExist:
                    raise ReceivablesError(
                        "resource_not_available", "El recibo no está disponible.", status=404
                    ) from None
                if row.document_artifact_id is None:
                    raise ReceivablesError(
                        "artifact_not_available", "El PDF todavía no está disponible.", status=409
                    )
                content, media_type, filename = documents_port.download_receipt_pdf(
                    authorization,
                    receipt_id=row.pk,
                    artifact_id=row.document_artifact_id,
                )
        except (AuthorizationDenied, TenantAccessDenied):
            return _error("forbidden", "La operación no está autorizada.", status=403)
        except ReceivablesError as error:
            return _error(error.code, error.message, status=error.status)
        except documents_port.DocumentsPortError as error:
            return _error(error.code, error.detail, status=error.status_code)
        response = HttpResponse(content, content_type=media_type)
        response["Content-Disposition"] = content_disposition_header(True, filename) or "attachment"
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
