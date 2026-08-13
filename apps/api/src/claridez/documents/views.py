from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
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

from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied

from .errors import DocumentsError
from .serializers import (
    DocumentCapabilitiesResponseSerializer,
    DocumentDomainErrorSerializer,
    ExternalUploadSerializer,
    GenericDocumentResponseSerializer,
    GrantCreateSerializer,
    InstrumentCreateSerializer,
    IssueSerializer,
    LegalHoldCreateSerializer,
    LegalHoldReleaseSerializer,
    PreviewSerializer,
    RecordCreateSerializer,
    RetentionAssignmentCreateSerializer,
    RetentionEligibilitySerializer,
    RetentionPolicyCreateSerializer,
    TemplateActiveSerializer,
    TemplateVersionWriteSerializer,
    TemplateWriteSerializer,
)
from .services import (
    activate_retention_policy,
    assign_retention_policy,
    create_external_grant,
    create_instrument,
    create_record,
    create_retention_policy,
    create_template,
    create_template_version,
    document_capabilities,
    download_artifact,
    download_external_file,
    evaluate_retention_eligibility,
    inactivate_template_version,
    issue_instrument,
    list_retention,
    list_templates,
    place_legal_hold,
    preview_document,
    publish_template_version,
    read_record_state,
    release_legal_hold,
    revoke_external_grant,
    set_template_active,
    update_template_version,
    upload_external_file,
)

ERROR = OpenApiResponse(
    response=DocumentDomainErrorSerializer, description="Error JSON fail-closed."
)
SUCCESS = OpenApiResponse(
    response=GenericDocumentResponseSerializer,
    description="Respuesta documental materializada dentro del tenant autorizado.",
)
IDEMPOTENCY_HEADER = OpenApiParameter(
    name="Idempotency-Key",
    type=UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    description="UUID estable para reintentos de emisión sin duplicar evidencia.",
)


def _error(code: str, message: str, *, status: int) -> Response:
    response = Response({"error": {"code": code, "message": message}}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _actor(request: Request) -> User | None:
    actor = request._request.user
    return actor if isinstance(actor, User) and actor.is_authenticated else None


def _respond(operation: Callable[[], Any], *, created: bool = False) -> Response:
    try:
        result = operation()
    except TenantAccessDenied:
        return _error("resource_not_available", "El recurso no está disponible.", status=404)
    except AuthorizationDenied:
        return _error("forbidden", "La operación no está autorizada.", status=403)
    except ObjectDoesNotExist:
        return _error("resource_not_available", "El recurso no está disponible.", status=404)
    except IntegrityError:
        return _error("concurrent_conflict", "La operación entró en conflicto.", status=409)
    except DocumentsError as error:
        return _error(error.code, error.detail, status=error.status_code)
    response = Response(result, status=201 if created else 200)
    response["Cache-Control"] = "no-store"
    return response


def _validated(serializer: Any) -> Response | None:
    if serializer.is_valid():
        return None
    return _error("invalid_request", "La solicitud no es válida.", status=400)


@method_decorator(csrf_protect, name="dispatch")
class DocumentAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor_or_response(self, request: Request) -> User | Response:
        actor = _actor(request)
        if actor is None:
            return _error("authentication_required", "Se requiere una sesión válida.", status=401)
        return actor


class DocumentCapabilitiesView(DocumentAPIView):
    @extend_schema(
        tags=["Documentos"],
        responses={200: DocumentCapabilitiesResponseSerializer, 401: ERROR},
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"capabilities": document_capabilities(actor, organization_id)})


class TemplateListCreateView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], responses={200: SUCCESS, 403: ERROR})
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: {"templates": list_templates(actor, organization_id)})

    @extend_schema(
        tags=["Documentos"], request=TemplateWriteSerializer, responses={201: SUCCESS, 400: ERROR}
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = TemplateWriteSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: create_template(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class TemplateVersionCreateView(DocumentAPIView):
    @extend_schema(
        tags=["Documentos"],
        request=TemplateVersionWriteSerializer,
        responses={201: SUCCESS, 409: ERROR},
    )
    def post(self, request: Request, organization_id: UUID, template_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = TemplateVersionWriteSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: create_template_version(
                actor, organization_id, template_id=template_id, **serializer.validated_data
            ),
            created=True,
        )


class TemplateVersionDetailView(DocumentAPIView):
    @extend_schema(
        tags=["Documentos"], request=TemplateVersionWriteSerializer, responses={200: SUCCESS}
    )
    def patch(self, request: Request, organization_id: UUID, version_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = TemplateVersionWriteSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: update_template_version(
                actor, organization_id, version_id=version_id, **serializer.validated_data
            )
        )


class TemplateVersionPublishView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], request=None, responses={200: SUCCESS, 409: ERROR})
    def post(self, request: Request, organization_id: UUID, version_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: publish_template_version(actor, organization_id, version_id=version_id)
        )


class TemplateVersionInactivateView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], request=None, responses={200: SUCCESS, 409: ERROR})
    def post(self, request: Request, organization_id: UUID, version_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: inactivate_template_version(actor, organization_id, version_id=version_id)
        )


class TemplateActiveView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], request=TemplateActiveSerializer, responses={200: SUCCESS})
    def patch(self, request: Request, organization_id: UUID, template_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = TemplateActiveSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: set_template_active(
                actor,
                organization_id,
                template_id=template_id,
                active=serializer.validated_data["active"],
            )
        )


class PreviewView(DocumentAPIView):
    @extend_schema(
        tags=["Documentos"], request=PreviewSerializer, responses={200: SUCCESS, 409: ERROR}
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = PreviewSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: preview_document(actor, organization_id, **serializer.validated_data)
        )


class RecordListCreateView(DocumentAPIView):
    @extend_schema(
        tags=["Documentos"],
        parameters=[OpenApiParameter("root_reservation_id", UUID, required=True)],
        responses={200: SUCCESS, 403: ERROR, 404: ERROR},
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        try:
            root_id = UUID(str(request.query_params.get("root_reservation_id", "")))
        except ValueError:
            return _error("invalid_request", "La solicitud no es válida.", status=400)
        return _respond(
            lambda: read_record_state(actor, organization_id, root_reservation_id=root_id)
        )

    @extend_schema(tags=["Documentos"], request=RecordCreateSerializer, responses={201: SUCCESS})
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = RecordCreateSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: create_record(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class InstrumentCreateView(DocumentAPIView):
    @extend_schema(
        tags=["Documentos"], request=InstrumentCreateSerializer, responses={201: SUCCESS}
    )
    def post(self, request: Request, organization_id: UUID, record_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = InstrumentCreateSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: create_instrument(
                actor, organization_id, record_id=record_id, **serializer.validated_data
            ),
            created=True,
        )


class InstrumentIssueView(DocumentAPIView):
    @extend_schema(
        tags=["Documentos"],
        request=IssueSerializer,
        parameters=[IDEMPOTENCY_HEADER],
        responses={202: SUCCESS, 409: ERROR},
    )
    def post(self, request: Request, organization_id: UUID, instrument_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = IssueSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        try:
            key = UUID(request.headers.get("Idempotency-Key", ""))
        except ValueError:
            return _error(
                "invalid_idempotency_key", "Idempotency-Key debe ser un UUID.", status=400
            )
        response = _respond(
            lambda: issue_instrument(
                actor,
                organization_id,
                instrument_id=instrument_id,
                idempotency_key=key,
                correlation_id=request.headers.get("X-Correlation-ID", str(key))[:128],
                **serializer.validated_data,
            )
        )
        if response.status_code == 200:
            response.status_code = 202
        return response


class ArtifactDownloadView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], responses={(200, "application/pdf"): bytes, 403: ERROR})
    def get(self, request: Request, organization_id: UUID, artifact_id: UUID) -> HttpResponse:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        try:
            content, media_type, filename = download_artifact(
                actor, organization_id, artifact_id=artifact_id
            )
        except (
            TenantAccessDenied,
            AuthorizationDenied,
            ObjectDoesNotExist,
            DocumentsError,
        ) as error:
            if isinstance(error, DocumentsError):
                return _error(error.code, error.detail, status=error.status_code)
            if isinstance(error, ObjectDoesNotExist):
                return _error(
                    "resource_not_available", "El recurso no está disponible.", status=404
                )
            return _error("forbidden", "La operación no está autorizada.", status=403)
        response = HttpResponse(content, content_type=media_type)
        disposition = content_disposition_header(True, filename)
        if disposition is not None:
            response["Content-Disposition"] = disposition
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class ExternalFileUploadView(DocumentAPIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(tags=["Documentos"], request=ExternalUploadSerializer, responses={202: SUCCESS})
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = ExternalUploadSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        upload = serializer.validated_data["file"]
        response = _respond(
            lambda: upload_external_file(
                actor,
                organization_id,
                record_id=serializer.validated_data["record_id"],
                display_name=upload.name,
                declared_media_type=upload.content_type or "application/octet-stream",
                source=upload,
                correlation_id=request.headers.get("X-Correlation-ID", str(UUID(int=0)))[:128],
            )
        )
        if response.status_code == 200:
            response.status_code = 202
        return response


class ExternalFileDownloadView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], responses={200: bytes, 403: ERROR})
    def get(self, request: Request, organization_id: UUID, external_file_id: UUID) -> HttpResponse:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        try:
            content, media_type, filename = download_external_file(
                actor, organization_id, external_file_id=external_file_id
            )
        except (
            TenantAccessDenied,
            AuthorizationDenied,
            ObjectDoesNotExist,
            DocumentsError,
        ) as error:
            if isinstance(error, DocumentsError):
                return _error(error.code, error.detail, status=error.status_code)
            if isinstance(error, ObjectDoesNotExist):
                return _error(
                    "resource_not_available", "El recurso no está disponible.", status=404
                )
            return _error("forbidden", "La operación no está autorizada.", status=403)
        response = HttpResponse(content, content_type=media_type)
        disposition = content_disposition_header(True, filename)
        if disposition is not None:
            response["Content-Disposition"] = disposition
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class GrantCreateView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], request=GrantCreateSerializer, responses={201: SUCCESS})
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = GrantCreateSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: create_external_grant(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class GrantRevokeView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], request=None, responses={200: SUCCESS})
    def post(self, request: Request, organization_id: UUID, grant_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: revoke_external_grant(actor, organization_id, grant_id=grant_id))


class RetentionView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], responses={200: SUCCESS})
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: list_retention(actor, organization_id))

    @extend_schema(
        tags=["Documentos"], request=RetentionPolicyCreateSerializer, responses={201: SUCCESS}
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = RetentionPolicyCreateSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: create_retention_policy(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class RetentionAssignmentView(DocumentAPIView):
    @extend_schema(
        tags=["Documentos"], request=RetentionAssignmentCreateSerializer, responses={201: SUCCESS}
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = RetentionAssignmentCreateSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: assign_retention_policy(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class RetentionEligibilityView(DocumentAPIView):
    @extend_schema(
        tags=["Documentos"], request=RetentionEligibilitySerializer, responses={200: SUCCESS}
    )
    def post(self, request: Request, organization_id: UUID, assignment_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = RetentionEligibilitySerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: evaluate_retention_eligibility(
                actor,
                organization_id,
                assignment_id=assignment_id,
                **serializer.validated_data,
            )
        )


class RetentionPolicyActivateView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], request=None, responses={200: SUCCESS, 409: ERROR})
    def post(self, request: Request, organization_id: UUID, policy_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: activate_retention_policy(actor, organization_id, policy_id=policy_id)
        )


class LegalHoldView(DocumentAPIView):
    @extend_schema(tags=["Documentos"], request=LegalHoldCreateSerializer, responses={201: SUCCESS})
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = LegalHoldCreateSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: place_legal_hold(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class LegalHoldReleaseView(DocumentAPIView):
    @extend_schema(
        tags=["Documentos"], request=LegalHoldReleaseSerializer, responses={200: SUCCESS}
    )
    def post(self, request: Request, organization_id: UUID, hold_id: UUID) -> Response:
        actor = self.actor_or_response(request)
        if isinstance(actor, Response):
            return actor
        serializer = LegalHoldReleaseSerializer(data=request.data)
        if error := _validated(serializer):
            return error
        return _respond(
            lambda: release_legal_hold(
                actor, organization_id, hold_id=hold_id, **serializer.validated_data
            )
        )
