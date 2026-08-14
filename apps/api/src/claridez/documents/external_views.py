from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpResponse, HttpResponseBase
from django.utils.http import content_disposition_header
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .acceptance import AcceptanceRequestEvidence, accept
from .config import document_settings
from .errors import DocumentsError
from .external_access import (
    create_acceptance_challenge,
    enforce_rate_limit,
    exchange_grant,
)
from .external_services import download_external_artifact, read_external_document
from .serializers import (
    AcceptanceSerializer,
    DocumentDomainErrorSerializer,
    GenericDocumentResponseSerializer,
    GrantExchangeSerializer,
)

COOKIE_NAME = "claridez_document_session"
ERROR = OpenApiResponse(
    response=DocumentDomainErrorSerializer, description="Respuesta externa opaca."
)
SUCCESS = OpenApiResponse(response=GenericDocumentResponseSerializer)


def _error(error: DocumentsError) -> Response:
    response = Response(
        {"error": {"code": error.code, "message": error.detail}}, status=error.status_code
    )
    return _secure(response)


def _secure[ResponseT: HttpResponseBase](
    response: ResponseT, *, frame_ancestors: str = "'none'"
) -> ResponseT:
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = f"default-src 'none'; frame-ancestors {frame_ancestors}"
    return response


def _session_token(request: Request) -> str:
    token = request.COOKIES.get(COOKIE_NAME, "")
    if not token:
        raise DocumentsError(
            "invalid_session", "El acceso documental no está disponible.", status_code=404
        )
    return token


def _rate_limit(request: Request) -> str:
    return enforce_rate_limit(str(request.META.get("REMOTE_ADDR", "unknown")))


class ExternalAPIView(APIView):
    authentication_classes: list[type[Any]] = []
    permission_classes: list[type[Any]] = []


class GrantExchangeView(ExternalAPIView):
    @extend_schema(
        tags=["Documentos externos"],
        request=GrantExchangeSerializer,
        responses={200: SUCCESS, 404: ERROR, 429: ERROR},
    )
    def post(self, request: Request) -> Response:
        serializer = GrantExchangeSerializer(data=request.data)
        if not serializer.is_valid():
            return _error(
                DocumentsError("invalid_request", "La solicitud no es válida.", status_code=400)
            )
        try:
            ip_hash = _rate_limit(request)
            secret = exchange_grant(
                serializer.validated_data["token"],
                request_id=request.headers.get("X-Request-ID", "")[:128],
                ip_hash=ip_hash,
            )
        except DocumentsError as error:
            return _error(error)
        response = _secure(Response({"status": "session_created"}))
        response.set_cookie(
            COOKIE_NAME,
            secret.token,
            max_age=max(
                1, int((secret.session.expires_at - secret.session.created_at).total_seconds())
            ),
            secure=settings.SESSION_COOKIE_SECURE,
            httponly=True,
            samesite="Strict",
            path="/api/v1/external/documents/",
        )
        return response


class ExternalDocumentView(ExternalAPIView):
    @extend_schema(tags=["Documentos externos"], responses={200: SUCCESS, 404: ERROR, 429: ERROR})
    def get(self, request: Request) -> Response:
        try:
            ip_hash = _rate_limit(request)
            result = read_external_document(
                _session_token(request),
                request_id=request.headers.get("X-Request-ID", ""),
                ip_hash=ip_hash,
            )
        except DocumentsError as error:
            return _error(error)
        return _secure(Response(result))


class ExternalArtifactView(ExternalAPIView):
    @extend_schema(
        tags=["Documentos externos"],
        responses={(200, "application/pdf"): bytes, 403: ERROR, 404: ERROR, 429: ERROR},
    )
    def get(self, request: Request) -> HttpResponse:
        try:
            ip_hash = _rate_limit(request)
            content, media_type, filename = download_external_artifact(
                _session_token(request),
                request_id=request.headers.get("X-Request-ID", ""),
                ip_hash=ip_hash,
            )
        except DocumentsError as error:
            return _error(error)
        response = HttpResponse(content, content_type=media_type)
        disposition = content_disposition_header(False, filename)
        if disposition is not None:
            response["Content-Disposition"] = disposition
        return _secure(response, frame_ancestors="'self'")


class ExternalChallengeView(ExternalAPIView):
    @extend_schema(
        tags=["Documentos externos"], request=None, responses={201: SUCCESS, 404: ERROR, 429: ERROR}
    )
    def post(self, request: Request) -> Response:
        try:
            ip_hash = _rate_limit(request)
            secret = create_acceptance_challenge(
                _session_token(request),
                request_id=request.headers.get("X-Request-ID", ""),
                ip_hash=ip_hash,
            )
        except DocumentsError as error:
            return _error(error)
        return _secure(
            Response(
                {
                    "challenge_token": secret.token,
                    "expires_at": secret.challenge.expires_at.isoformat(),
                },
                status=201,
            )
        )


class ExternalAcceptanceView(ExternalAPIView):
    @extend_schema(
        tags=["Documentos externos"],
        request=AcceptanceSerializer,
        responses={201: SUCCESS, 409: ERROR, 429: ERROR},
    )
    def post(self, request: Request) -> Response:
        serializer = AcceptanceSerializer(data=request.data)
        if not serializer.is_valid():
            return _error(
                DocumentsError("invalid_request", "La solicitud no es válida.", status_code=400)
            )
        try:
            _rate_limit(request)
            evidence_policy = document_settings()
            evidence = accept(
                _session_token(request),
                challenge_token=serializer.validated_data["challenge_token"],
                manifestation_version=serializer.validated_data["manifestation_version"],
                affirmative=serializer.validated_data["affirmative"],
                evidence=AcceptanceRequestEvidence(
                    asserted_name=serializer.validated_data["asserted_name"],
                    ip_address=(
                        request.META.get("REMOTE_ADDR")
                        if evidence_policy.capture_acceptance_ip_address
                        else None
                    ),
                    user_agent=(
                        request.headers.get("User-Agent", "")
                        if evidence_policy.capture_acceptance_user_agent
                        else None
                    ),
                    request_id=request.headers.get("X-Request-ID", ""),
                    correlation_id=request.headers.get("X-Correlation-ID", ""),
                    timezone_name=serializer.validated_data["timezone"],
                ),
            )
        except DocumentsError as error:
            return _error(error)
        return _secure(
            Response(
                {
                    "status": "accepted",
                    "acceptance_id": str(evidence.pk),
                    "accepted_at": evidence.accepted_at.isoformat(),
                    "artifact_sha256": evidence.artifact_sha256,
                },
                status=201,
            )
        )
