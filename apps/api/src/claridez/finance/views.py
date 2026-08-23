from __future__ import annotations

import csv
from collections.abc import Callable
from decimal import Decimal
from io import StringIO
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied

from .errors import FinanceError
from .serializers import (
    BudgetCreateSerializer,
    CashCorrectionCreateSerializer,
    CashMovementCreateSerializer,
    CategoryCreateSerializer,
    CorrectionCreateSerializer,
    CostEvidenceCreateSerializer,
    DirectCostCreateSerializer,
    DirectCostPlanCreateSerializer,
    EntityResponseSerializer,
    EvidenceContextResponseSerializer,
    EvidenceDecisionCreateSerializer,
    ExpenseCorrectionCreateSerializer,
    ExpenseCreateSerializer,
    FinanceCapabilitiesResponseSerializer,
    FinanceErrorSerializer,
    FinanceOverviewResponseSerializer,
    PeriodCreateSerializer,
    RecognitionAdjustmentCreateSerializer,
    RecognitionCorrectionCreateSerializer,
    RecurringOccurrenceCreateSerializer,
    RecurringRuleCreateSerializer,
)
from .services import (
    close_period,
    correct_cash_movement,
    correct_direct_cost,
    correct_expense,
    correct_recognition_adjustment,
    create_category,
    create_period,
    create_recurring_rule,
    decide_cost_evidence,
    evidence_context,
    export_rows,
    finance_capabilities,
    finance_overview,
    materialize_recurring_expense,
    publish_budget,
    publish_direct_cost_plan,
    record_actual_direct_cost,
    record_cash_movement,
    record_expense,
    record_recognition_adjustment,
    submit_cost_evidence,
)

ERROR = OpenApiResponse(response=FinanceErrorSerializer, description="Error JSON fail-closed.")
SUCCESS = OpenApiResponse(response=EntityResponseSerializer, description="Hecho P11 creado.")
IDEMPOTENCY_HEADER = OpenApiParameter(
    name="Idempotency-Key",
    type=UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    description="UUID estable para reintentos sin duplicar hechos financieros.",
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
    except FinanceError as error:
        return _error(error.code, error.message, status=error.status)
    except IntegrityError:
        return _error("concurrent_conflict", "La operación entró en conflicto.", status=409)
    response = Response(_json_safe(result), status=201 if created else 200)
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
class FinanceAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        actor = _actor(request)
        return (
            actor
            if actor is not None
            else _error("authentication_required", "Se requiere una sesión válida.", status=401)
        )


class CapabilitiesView(FinanceAPIView):
    @extend_schema(
        responses={200: FinanceCapabilitiesResponseSerializer, 401: ERROR, 404: ERROR},
        tags=["Finanzas"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(lambda: {"capabilities": finance_capabilities(actor, organization_id)})
        )


class OverviewView(FinanceAPIView):
    @extend_schema(
        parameters=[
            OpenApiParameter("period_id", UUID, OpenApiParameter.QUERY),
            OpenApiParameter("root_reservation_id", UUID, OpenApiParameter.QUERY),
            OpenApiParameter("venue_id", UUID, OpenApiParameter.QUERY),
        ],
        responses={200: FinanceOverviewResponseSerializer, 401: ERROR, 403: ERROR, 404: ERROR},
        tags=["Finanzas"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(
                lambda: finance_overview(
                    actor,
                    organization_id,
                    period_id=request.query_params.get("period_id"),
                    root_reservation_id=request.query_params.get("root_reservation_id"),
                    venue_id=request.query_params.get("venue_id"),
                )
            )
        )


class EvidenceContextView(FinanceAPIView):
    @extend_schema(
        responses={200: EvidenceContextResponseSerializer, 401: ERROR, 403: ERROR, 404: ERROR},
        tags=["Finanzas"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        return (
            actor
            if isinstance(actor, Response)
            else _respond(lambda: evidence_context(actor, organization_id))
        )


def _post(
    view: FinanceAPIView,
    request: Request,
    serializer_type: type[Any],
    operation: Callable[[User, dict[str, Any], UUID], Any],
) -> Response:
    actor = view.actor_or_response(request)
    if isinstance(actor, Response):
        return actor
    key = _key(request)
    if isinstance(key, Response):
        return key
    serializer = serializer_type(data=request.data)
    if (error := _validated(serializer)) is not None:
        return error
    return _respond(lambda: _entity(operation(actor, serializer.validated_data, key)), created=True)


class CategoriesView(FinanceAPIView):
    @extend_schema(
        request=CategoryCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        return _post(
            self,
            request,
            CategoryCreateSerializer,
            lambda actor, data, key: create_category(
                actor, organization_id, kind=data["kind"], name=data["name"], idempotency_key=key
            ),
        )


class PeriodsView(FinanceAPIView):
    @extend_schema(
        request=PeriodCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        return _post(
            self,
            request,
            PeriodCreateSerializer,
            lambda actor, data, key: create_period(
                actor,
                organization_id,
                starts_on=data["starts_on"],
                ends_on=data["ends_on"],
                label=data["label"],
                idempotency_key=key,
            ),
        )


class PeriodCloseView(FinanceAPIView):
    @extend_schema(
        request=None,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID, period_id: UUID) -> Response:
        return _post(
            self,
            request,
            serializers_empty(),
            lambda actor, _data, key: close_period(
                actor, organization_id, period_id=period_id, idempotency_key=key
            ),
        )


def serializers_empty() -> type[Any]:
    from rest_framework import serializers

    class EmptySerializer(serializers.Serializer[dict[str, object]]):
        pass

    return EmptySerializer


class CostPlansView(FinanceAPIView):
    @extend_schema(
        request=DirectCostPlanCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        return _post(
            self,
            request,
            DirectCostPlanCreateSerializer,
            lambda actor, data, key: publish_direct_cost_plan(
                actor,
                organization_id,
                root_reservation_id=data["root_reservation_id"],
                venue_id=data["venue_id"],
                currency_value=data["currency"],
                reason=data["reason"],
                lines=data["lines"],
                idempotency_key=key,
            ),
        )


class CostEvidenceView(FinanceAPIView):
    @extend_schema(
        request=CostEvidenceCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        return _post(
            self,
            request,
            CostEvidenceCreateSerializer,
            lambda actor, data, key: submit_cost_evidence(
                actor,
                organization_id,
                root_reservation_id=data["root_reservation_id"],
                venue_id=data["venue_id"],
                category_id=data["category_id"],
                amount_value=data["amount"],
                currency_value=data["currency"],
                economic_date=data["economic_date"],
                description=data["description"],
                evidence_reference=data["evidence_reference"],
                idempotency_key=key,
            ),
        )


class EvidenceDecisionView(FinanceAPIView):
    @extend_schema(
        request=EvidenceDecisionCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID, evidence_id: UUID) -> Response:
        return _post(
            self,
            request,
            EvidenceDecisionCreateSerializer,
            lambda actor, data, key: decide_cost_evidence(
                actor,
                organization_id,
                evidence_id=evidence_id,
                decision=data["decision"],
                reason=data["reason"],
                idempotency_key=key,
            ),
        )


class DirectCostsView(FinanceAPIView):
    @extend_schema(
        request=DirectCostCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        return _post(
            self,
            request,
            DirectCostCreateSerializer,
            lambda actor, data, key: record_actual_direct_cost(
                actor,
                organization_id,
                root_reservation_id=data["root_reservation_id"],
                venue_id=data["venue_id"],
                category_id=data["category_id"],
                amount_value=data["amount"],
                currency_value=data["currency"],
                economic_date=data["economic_date"],
                description=data["description"],
                evidence_reference=data["evidence_reference"],
                idempotency_key=key,
            ),
        )


class DirectCostCorrectionView(FinanceAPIView):
    @extend_schema(
        request=CorrectionCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID, direct_cost_id: UUID) -> Response:
        return _post(
            self,
            request,
            CorrectionCreateSerializer,
            lambda actor, data, key: correct_direct_cost(
                actor,
                organization_id,
                direct_cost_id=direct_cost_id,
                direction=data["direction"],
                amount_value=data["amount"],
                economic_date=data["economic_date"],
                reason=data["reason"],
                evidence_reference=data.get("evidence_reference", ""),
                idempotency_key=key,
            ),
        )


class RecurringRulesView(FinanceAPIView):
    @extend_schema(
        request=RecurringRuleCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        return _post(
            self,
            request,
            RecurringRuleCreateSerializer,
            lambda actor, data, key: create_recurring_rule(
                actor,
                organization_id,
                category_id=data["category_id"],
                name=data["name"],
                amount_value=data["amount"],
                currency_value=data["currency"],
                day_of_month=data["day_of_month"],
                valid_from=data["valid_from"],
                valid_until=data.get("valid_until"),
                default_venue_id=data.get("default_venue_id"),
                idempotency_key=key,
            ),
        )


class RecurringOccurrenceView(FinanceAPIView):
    @extend_schema(
        request=RecurringOccurrenceCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID, rule_id: UUID) -> Response:
        return _post(
            self,
            request,
            RecurringOccurrenceCreateSerializer,
            lambda actor, data, key: materialize_recurring_expense(
                actor,
                organization_id,
                rule_id=rule_id,
                economic_date=data["economic_date"],
                evidence_reference=data["evidence_reference"],
                idempotency_key=key,
            ),
        )


class ExpensesView(FinanceAPIView):
    @extend_schema(
        request=ExpenseCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        return _post(
            self,
            request,
            ExpenseCreateSerializer,
            lambda actor, data, key: record_expense(
                actor,
                organization_id,
                category_id=data["category_id"],
                expense_type=data["expense_type"],
                amount_value=data["amount"],
                currency_value=data["currency"],
                economic_date=data["economic_date"],
                description=data["description"],
                evidence_reference=data["evidence_reference"],
                allocations=data["allocations"],
                idempotency_key=key,
            ),
        )


class ExpenseCorrectionView(FinanceAPIView):
    @extend_schema(
        request=ExpenseCorrectionCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID, expense_id: UUID) -> Response:
        return _post(
            self,
            request,
            ExpenseCorrectionCreateSerializer,
            lambda actor, data, key: correct_expense(
                actor,
                organization_id,
                expense_id=expense_id,
                direction=data["direction"],
                amount_value=data["amount"],
                economic_date=data["economic_date"],
                scope=data["scope"],
                root_reservation_id=data.get("root_reservation_id"),
                venue_id=data.get("venue_id"),
                reason=data["reason"],
                evidence_reference=data.get("evidence_reference", ""),
                idempotency_key=key,
            ),
        )


class BudgetsView(FinanceAPIView):
    @extend_schema(
        request=BudgetCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        return _post(
            self,
            request,
            BudgetCreateSerializer,
            lambda actor, data, key: publish_budget(
                actor,
                organization_id,
                period_id=data["period_id"],
                venue_id=data.get("venue_id"),
                currency_value=data["currency"],
                reason=data["reason"],
                lines=data["lines"],
                idempotency_key=key,
            ),
        )


class CashMovementsView(FinanceAPIView):
    @extend_schema(
        request=CashMovementCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        return _post(
            self,
            request,
            CashMovementCreateSerializer,
            lambda actor, data, key: record_cash_movement(
                actor,
                organization_id,
                direction=data["direction"],
                source_kind=data["source_kind"],
                source_id=data["source_id"],
                original_outflow_id=data.get("original_outflow_id"),
                amount_value=data["amount"],
                economic_date=data["economic_date"],
                reason=data["reason"],
                evidence_reference=data["evidence_reference"],
                idempotency_key=key,
            ),
        )


class CashCorrectionView(FinanceAPIView):
    @extend_schema(
        request=CashCorrectionCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID, cash_movement_id: UUID) -> Response:
        return _post(
            self,
            request,
            CashCorrectionCreateSerializer,
            lambda actor, data, key: correct_cash_movement(
                actor,
                organization_id,
                cash_movement_id=cash_movement_id,
                direction=data["direction"],
                amount_value=data["amount"],
                economic_date=data["economic_date"],
                reason=data["reason"],
                idempotency_key=key,
            ),
        )


class RecognitionAdjustmentsView(FinanceAPIView):
    @extend_schema(
        request=RecognitionAdjustmentCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        return _post(
            self,
            request,
            RecognitionAdjustmentCreateSerializer,
            lambda actor, data, key: record_recognition_adjustment(
                actor,
                organization_id,
                root_reservation_id=data["root_reservation_id"],
                direction=data["direction"],
                amount_value=data["amount"],
                currency_value=data["currency"],
                economic_date=data["economic_date"],
                reason_code=data["reason_code"],
                reason=data["reason"],
                evidence_reference=data["evidence_reference"],
                idempotency_key=key,
            ),
        )


class RecognitionCorrectionView(FinanceAPIView):
    @extend_schema(
        request=RecognitionCorrectionCreateSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={201: SUCCESS, 400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR},
        tags=["Finanzas"],
    )
    def post(
        self, request: Request, organization_id: UUID, recognition_adjustment_id: UUID
    ) -> Response:
        return _post(
            self,
            request,
            RecognitionCorrectionCreateSerializer,
            lambda actor, data, key: correct_recognition_adjustment(
                actor,
                organization_id,
                recognition_adjustment_id=recognition_adjustment_id,
                direction=data["direction"],
                amount_value=data["amount"],
                economic_date=data["economic_date"],
                reason=data["reason"],
                idempotency_key=key,
            ),
        )


class ExportView(FinanceAPIView):
    @extend_schema(
        parameters=[OpenApiParameter("period_id", UUID, OpenApiParameter.QUERY)],
        responses={(200, "text/csv"): OpenApiResponse(description="CSV financiero operativo.")},
        tags=["Finanzas"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response | HttpResponse:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        try:
            rows = export_rows(
                actor, organization_id, period_id=request.query_params.get("period_id")
            )
        except TenantAccessDenied:
            return _error("resource_not_available", "El recurso no está disponible.", status=404)
        except AuthorizationDenied:
            return _error("forbidden", "La operación no está autorizada.", status=403)
        except FinanceError as error:
            return _error(error.code, error.message, status=error.status)
        stream = StringIO(newline="")
        csv.writer(stream).writerows(rows)
        response = HttpResponse(stream.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="claridez-finanzas.csv"'
        response["Cache-Control"] = "no-store"
        return response
