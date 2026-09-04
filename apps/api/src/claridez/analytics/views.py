from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import IntegrityError
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied

from . import services
from .errors import AnalyticsError
from .serializers import (
    CatalogSerializer,
    ErrorSerializer,
    ExecutionCreateSerializer,
    ExecutionPageSerializer,
    ExecutionSerializer,
    ExportCreateSerializer,
    ExportJobSerializer,
    ExportPageSerializer,
    HistoryQuerySerializer,
    QueryResultSerializer,
    QuerySerializer,
    ReportArchiveSerializer,
    ReportCreateSerializer,
    ReportPageSerializer,
    ReportReviseSerializer,
    ReportSerializer,
    StrictSerializer,
    selections,
)
from .storage import StorageIntegrityError

ERROR = OpenApiResponse(response=ErrorSerializer, description="Error JSON fail-closed.")
ERRORS = {400: ERROR, 401: ERROR, 403: ERROR, 404: ERROR, 409: ERROR}
KEY = OpenApiParameter(
    name="Idempotency-Key",
    type=UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    description="UUID estable para reintentos de ejecución/exportación.",
)
HISTORY_PARAMETERS = [
    OpenApiParameter(
        "cursor",
        str,
        OpenApiParameter.QUERY,
        description="Cursor firmado de esta colección; no concede acceso.",
    ),
    OpenApiParameter(
        "limit", int, OpenApiParameter.QUERY, description="Entre 1 y 50; por defecto 50."
    ),
]


def _error(code: str, message: str, status: int) -> Response:
    result = Response({"error": {"code": code, "message": message}}, status=status)
    result["Cache-Control"] = "no-store"
    return result


def _key(request: Request) -> UUID:
    try:
        return UUID(request.headers.get("Idempotency-Key", ""))
    except (ValueError, AttributeError):
        raise AnalyticsError(
            "invalid_idempotency_key", "Se requiere una Idempotency-Key UUID válida."
        ) from None


def _respond(
    request: Request,
    operation: Callable[[User, dict[str, Any]], object],
    *,
    serializer: type[StrictSerializer] | None = None,
    query_serializer: type[StrictSerializer] | None = None,
    created: bool = False,
) -> Response | HttpResponse:
    actor = request._request.user
    if not isinstance(actor, User) or not actor.is_authenticated:
        return _error("authentication_required", "Se requiere una sesión activa.", 401)
    data: dict[str, Any] = {}
    if serializer is not None:
        if request.query_params:
            return _error("invalid_request", "La consulta contiene parámetros no permitidos.", 400)
        form = serializer(data=request.data)
        if not form.is_valid():
            return _error(
                "invalid_request", "La solicitud o el contrato temporal no son válidos.", 400
            )
        data = form.validated_data
    elif query_serializer is not None:
        if any(len(values) != 1 for _, values in request.query_params.lists()):
            return _error("invalid_request", "La consulta contiene parámetros duplicados.", 400)
        form = query_serializer(data=request.query_params.dict())
        if not form.is_valid():
            return _error("invalid_request", "Los parámetros de paginación no son válidos.", 400)
        data = form.validated_data
    elif request.query_params:
        return _error("invalid_request", "La consulta contiene parámetros no permitidos.", 400)
    try:
        payload = operation(actor, data)
    except TenantAccessDenied:
        return _error("resource_not_available", "El recurso no está disponible.", 404)
    except AuthorizationDenied:
        return _error("forbidden", "La operación no está autorizada.", 403)
    except AnalyticsError as error:
        return _error(error.code, error.message, error.status)
    except (ValueError, KeyError):
        return _error(
            "invalid_request", "El contrato métrico o sus parámetros no son válidos.", 400
        )
    except StorageIntegrityError:
        return _error(
            "integrity_failure", "No se pudo verificar la integridad de la exportación.", 409
        )
    except IntegrityError:
        return _error("concurrent_conflict", "La operación entró en conflicto.", 409)
    if isinstance(payload, HttpResponse):
        return payload
    response = Response(payload, status=201 if created else 200)
    response["Cache-Control"] = "no-store"
    return response


@method_decorator(csrf_protect, name="dispatch")
class AnalyticsView(APIView):
    authentication_classes = [SessionAuthentication]


class CatalogView(AnalyticsView):
    @extend_schema(operation_id="analytics_catalog", responses={200: CatalogSerializer, **ERRORS})
    def get(self, request: Request, organization_id: UUID) -> Response | HttpResponse:
        return _respond(
            request, lambda actor, data: services.catalog_metadata(actor, organization_id)
        )


class DashboardQueryView(AnalyticsView):
    @extend_schema(
        operation_id="analytics_dashboard_query",
        request=QuerySerializer,
        responses={200: QueryResultSerializer, **ERRORS},
    )
    def post(self, request: Request, organization_id: UUID) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.dashboard_query(
                actor,
                organization_id,
                timezone_name=data["timezone"],
                selections=selections(data["metrics"]),
            ),
            serializer=QuerySerializer,
        )


class ReportListCreateView(AnalyticsView):
    @extend_schema(
        operation_id="analytics_report_list",
        parameters=HISTORY_PARAMETERS,
        responses={200: ReportPageSerializer, **ERRORS},
    )
    def get(self, request: Request, organization_id: UUID) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.history_page(actor, organization_id, "reports", **data),
            query_serializer=HistoryQuerySerializer,
        )

    @extend_schema(
        operation_id="analytics_report_create",
        request=ReportCreateSerializer,
        responses={201: ReportSerializer, **ERRORS},
    )
    def post(self, request: Request, organization_id: UUID) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.create_report(
                actor,
                organization_id,
                title=data["title"],
                visibility=data["visibility"],
                timezone_name=data["timezone"],
                selections=selections(data["metrics"]),
            ),
            serializer=ReportCreateSerializer,
            created=True,
        )


class ReportRevisionView(AnalyticsView):
    @extend_schema(
        operation_id="analytics_report_revision_list",
        parameters=HISTORY_PARAMETERS,
        responses={200: ReportPageSerializer, **ERRORS},
    )
    def get(
        self, request: Request, organization_id: UUID, report_id: UUID
    ) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.history_page(
                actor, organization_id, "revisions", report_id=report_id, **data
            ),
            query_serializer=HistoryQuerySerializer,
        )

    @extend_schema(
        operation_id="analytics_report_revise",
        request=ReportReviseSerializer,
        responses={201: ReportSerializer, **ERRORS},
    )
    def post(
        self, request: Request, organization_id: UUID, report_id: UUID
    ) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.revise_report(
                actor,
                organization_id,
                report_id,
                expected_revision=data["expected_revision"],
                title=data["title"],
                visibility=data["visibility"],
                timezone_name=data["timezone"],
                selections=selections(data["metrics"]),
            ),
            serializer=ReportReviseSerializer,
            created=True,
        )


class ReportArchiveView(AnalyticsView):
    @extend_schema(
        operation_id="analytics_report_archive",
        request=ReportArchiveSerializer,
        responses={200: ReportSerializer, **ERRORS},
    )
    def post(
        self, request: Request, organization_id: UUID, report_id: UUID
    ) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.archive_report(
                actor,
                organization_id,
                report_id,
                expected_revision=data["expected_revision"],
                archived=data["archived"],
            ),
            serializer=ReportArchiveSerializer,
        )


class ExecutionListCreateView(AnalyticsView):
    @extend_schema(
        operation_id="analytics_execution_list",
        parameters=HISTORY_PARAMETERS,
        responses={200: ExecutionPageSerializer, **ERRORS},
    )
    def get(self, request: Request, organization_id: UUID) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.history_page(actor, organization_id, "executions", **data),
            query_serializer=HistoryQuerySerializer,
        )

    @extend_schema(
        operation_id="analytics_execution_create",
        request=ExecutionCreateSerializer,
        parameters=[KEY],
        responses={201: ExecutionSerializer, **ERRORS},
    )
    def post(self, request: Request, organization_id: UUID) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.run_report(
                actor,
                organization_id,
                idempotency_key=_key(request),
                report_revision_id=data.get("report_revision_id"),
                timezone_name=data.get("timezone"),
                selections=selections(data["metrics"]) if "metrics" in data else (),
            ),
            serializer=ExecutionCreateSerializer,
            created=True,
        )


class ExecutionDetailView(AnalyticsView):
    @extend_schema(
        operation_id="analytics_execution_detail", responses={200: ExecutionSerializer, **ERRORS}
    )
    def get(
        self, request: Request, organization_id: UUID, execution_id: UUID
    ) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.execution_detail(actor, organization_id, execution_id),
        )


class ExportListCreateView(AnalyticsView):
    @extend_schema(
        operation_id="analytics_export_list",
        parameters=HISTORY_PARAMETERS,
        responses={200: ExportPageSerializer, **ERRORS},
    )
    def get(self, request: Request, organization_id: UUID) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.history_page(actor, organization_id, "exports", **data),
            query_serializer=HistoryQuerySerializer,
        )

    @extend_schema(
        operation_id="analytics_export_create",
        request=ExportCreateSerializer,
        parameters=[KEY],
        responses={201: ExportJobSerializer, **ERRORS},
    )
    def post(self, request: Request, organization_id: UUID) -> Response | HttpResponse:
        return _respond(
            request,
            lambda actor, data: services.create_export(
                actor,
                organization_id,
                data["execution_id"],
                format=data["format"],
                idempotency_key=_key(request),
            ),
            serializer=ExportCreateSerializer,
            created=True,
        )


class ExportStatusView(AnalyticsView):
    @extend_schema(
        operation_id="analytics_export_status", responses={200: ExportJobSerializer, **ERRORS}
    )
    def get(self, request: Request, organization_id: UUID, job_id: UUID) -> Response | HttpResponse:
        return _respond(
            request, lambda actor, data: services.export_status(actor, organization_id, job_id)
        )


class ExportDownloadView(AnalyticsView):
    @extend_schema(
        operation_id="analytics_export_download",
        responses={
            (200, "text/csv"): OpenApiTypes.BINARY,
            (
                200,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ): OpenApiTypes.BINARY,
            (200, "application/pdf"): OpenApiTypes.BINARY,
            **ERRORS,
        },
    )
    def get(self, request: Request, organization_id: UUID, job_id: UUID) -> Response | HttpResponse:
        def download(actor: User, data: dict[str, Any]) -> HttpResponse:
            content, format, digest = services.download_export(actor, organization_id, job_id)
            media = {
                "csv": "text/csv; charset=utf-8",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pdf": "application/pdf",
            }
            response = HttpResponse(content, content_type=media[format])
            response["Content-Disposition"] = (
                f'attachment; filename="claridez-report-{job_id}.{format}"'
            )
            response["Cache-Control"] = "no-store, private"
            response["X-Content-Type-Options"] = "nosniff"
            response["X-Artifact-SHA256"] = digest
            return response

        return _respond(request, download)
