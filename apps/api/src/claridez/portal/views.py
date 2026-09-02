from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from claridez.commercial.public import CommercialError
from claridez.communications.public import CommunicationsError
from claridez.documents.public import DocumentsPortError
from claridez.identity.models import User
from claridez.organizations.capabilities import Capability, capabilities_for_role
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.tenant_scope import authorized_tenant_scope
from claridez.people.public import PeopleError
from claridez.receivables.public import ReceivablesError
from claridez.scheduling.public import SchedulingError

from .errors import PortalError
from .security import consume_rate_limit, random_token, verify_antiabuse
from .serializers import (
    AvailabilitySerializer,
    ChallengeStartSerializer,
    ChallengeVerifySerializer,
    DocumentAcceptSerializer,
    FormCreateSerializer,
    FormVersionCreateSerializer,
    GrantIssueSerializer,
    GrantRevokeSerializer,
    PreferenceSerializer,
    SubmissionSerializer,
    WebhookLocatorSerializer,
)
from .services import (
    accept_document_for_grant,
    create_form,
    create_form_version,
    create_webhook_locator_internal,
    download_document_for_grant,
    issue_grant,
    list_forms,
    list_grants,
    portal_documents_for_grant,
    portal_event,
    portal_events,
    public_availability,
    publish_form,
    read_public_form,
    retire_form,
    revoke_grant,
    revoke_session,
    rotate_form_locator,
    rotate_session,
    start_challenge,
    submit_public_form,
    update_client_preference,
    verify_challenge,
)

SUCCESS = OpenApiResponse(description="Respuesta minimizada y tenant-aware.")
ERROR = OpenApiResponse(description="Error JSON seguro.")
PORTAL_COOKIE = "claridez_portal_session"


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _error(code: str, message: str, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)


def _safe(operation: Any, *, created: bool = False) -> Response:
    try:
        value = operation()
    except PortalError as error:
        return _error(error.code, error.message, error.status)
    except DocumentsPortError as error:
        return _error(error.code, error.detail, error.status_code)
    except (CommercialError, CommunicationsError, PeopleError, ReceivablesError) as error:
        return _error(error.code, error.message, error.status)
    except SchedulingError as error:
        return _error(error.code, error.message, error.status)
    except AuthorizationDenied:
        return _error("resource_not_available", "El recurso no está disponible.", 404)
    return Response(_json(value), status=201 if created else 200)


def _client_ip(request: Request) -> str:
    return str(request.META.get("REMOTE_ADDR", ""))


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("Origin", "")
    if not origin:
        return True
    return urlparse(origin).netloc.lower() == request.get_host().lower()


def _antiabuse_hostname(request: Request, claimed: object) -> str:
    server_hostname = urlparse(f"//{request.get_host()}").hostname or ""
    if not server_hostname or str(claimed).strip().lower() != server_hostname.lower():
        raise PortalError("antiabuse_failed", "No fue posible validar la solicitud.", status=400)
    return server_hostname


def _rate_limited(operation: Any) -> Response | None:
    try:
        operation()
    except PortalError as error:
        return _error(error.code, error.message, error.status)
    return None


class ExternalAPIView(APIView):
    authentication_classes: list[type[Any]] = []
    permission_classes: list[type[Any]] = []

    def finalize_response(self, request: Any, response: Any, *args: Any, **kwargs: Any) -> Any:
        finalized = super().finalize_response(request, response, *args, **kwargs)
        finalized["Cache-Control"] = "private, no-store"
        finalized["Referrer-Policy"] = "no-referrer"
        return finalized


@method_decorator(ensure_csrf_cookie, name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
class PublicFormView(ExternalAPIView):
    @extend_schema(responses={200: SUCCESS, 404: ERROR}, tags=["Captación pública"])
    def get(self, request: Request, locator: str) -> Response:
        limited = _rate_limited(
            lambda: consume_rate_limit(
                action="form_read",
                key=f"{_client_ip(request)}:{locator}",
                limit=60,
                window_seconds=60,
            )
        )
        if limited:
            return limited
        return _safe(lambda: read_public_form(locator))

    @extend_schema(
        request=SubmissionSerializer,
        responses={201: SUCCESS, 400: ERROR, 404: ERROR, 409: ERROR, 429: ERROR},
        tags=["Captación pública"],
    )
    def post(self, request: Request, locator: str) -> Response:
        if not _origin_allowed(request):
            return _error("invalid_origin", "El origen no está autorizado.", 403)
        serializer = SubmissionSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        data = dict(serializer.validated_data)
        limited = _rate_limited(
            lambda: consume_rate_limit(
                action="form_submit", key=_client_ip(request), limit=10, window_seconds=300
            )
        )
        if limited:
            return limited
        try:
            verify_antiabuse(
                str(data.pop("antiabuse_token")),
                action="public_form_submit",
                hostname=_antiabuse_hostname(request, data.pop("antiabuse_hostname")),
                remote_ip=_client_ip(request),
            )
        except PortalError as error:
            return _error(error.code, error.message, error.status)
        idempotency_key = str(data.pop("idempotency_key"))
        return _safe(
            lambda: submit_public_form(locator, idempotency_key=idempotency_key, data=data),
            created=True,
        )


class PublicSecurityConfigView(ExternalAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["Captación pública"])
    def get(self, request: Request) -> Response:
        del request
        return Response(
            {
                "antiabuse_provider": settings.PORTAL_ANTIABUSE_PROVIDER,
                "turnstile_site_key": (
                    settings.PORTAL_TURNSTILE_SITE_KEY
                    if settings.PORTAL_ANTIABUSE_PROVIDER == "turnstile"
                    else ""
                ),
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class PublicAvailabilityView(ExternalAPIView):
    @extend_schema(
        request=AvailabilitySerializer, responses={200: SUCCESS}, tags=["Captación pública"]
    )
    def post(self, request: Request, locator: str) -> Response:
        serializer = AvailabilitySerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        data = serializer.validated_data
        limited = _rate_limited(
            lambda: consume_rate_limit(
                action="availability", key=_client_ip(request), limit=30, window_seconds=60
            )
        )
        if limited:
            return limited
        return _safe(
            lambda: public_availability(
                locator,
                event_type_id=data["event_type_id"],
                space_id=data["space_id"],
                starts_at_local=str(data["starts_at_local"]),
                duration_minutes=int(data["duration_minutes"]),
            )
        )


@method_decorator(csrf_protect, name="dispatch")
class ChallengeStartView(ExternalAPIView):
    @extend_schema(
        request=ChallengeStartSerializer, responses={202: SUCCESS}, tags=["Portal cliente"]
    )
    def post(self, request: Request) -> Response:
        if not _origin_allowed(request):
            return _error("invalid_origin", "El origen no está autorizado.", 403)
        serializer = ChallengeStartSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        data = serializer.validated_data
        limited = _rate_limited(
            lambda: consume_rate_limit(
                action="portal_challenge", key=_client_ip(request), limit=8, window_seconds=300
            )
        )
        if limited:
            return limited
        limited = _rate_limited(
            lambda: consume_rate_limit(
                action="portal_challenge_contact",
                key=(
                    f"{data['form_locator']}:{data['channel']}:"
                    f"{str(data['contact']).strip().casefold()}"
                ),
                limit=5,
                window_seconds=900,
            )
        )
        if limited:
            return limited
        try:
            verify_antiabuse(
                str(data["antiabuse_token"]),
                action="portal_challenge",
                hostname=_antiabuse_hostname(request, data["antiabuse_hostname"]),
                remote_ip=_client_ip(request),
            )
            locator, _ = start_challenge(
                str(data["form_locator"]),
                channel=str(data["channel"]),
                contact_value=str(data["contact"]),
                kind=str(data["kind"]),
            )
        except (PortalError, AuthorizationDenied):
            locator = None
        shaped = locator or random_token()
        return Response(
            {
                "status": "accepted",
                "challenge": shaped,
                "message": "Si el acceso existe, recibirás instrucciones.",
            },
            status=202,
        )


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
class ChallengeVerifyView(ExternalAPIView):
    @extend_schema(
        request=ChallengeVerifySerializer, responses={200: SUCCESS}, tags=["Portal cliente"]
    )
    def post(self, request: Request) -> Response:
        if not _origin_allowed(request):
            return _error("invalid_origin", "El origen no está autorizado.", 403)
        serializer = ChallengeVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        limited = _rate_limited(
            lambda: consume_rate_limit(
                action="portal_verify", key=_client_ip(request), limit=20, window_seconds=300
            )
        )
        if limited:
            return limited
        response = _safe(lambda: verify_challenge(str(serializer.validated_data["challenge"])))
        if response.status_code == 200:
            token, session = response.data
            response.data = {
                "authenticated": True,
                "idle_expires_at": session.idle_expires_at,
                "absolute_expires_at": session.absolute_expires_at,
            }
            response.set_cookie(
                PORTAL_COOKIE,
                token,
                httponly=True,
                secure=settings.SESSION_COOKIE_SECURE,
                samesite="Lax",
                max_age=None,
                path="/api/v1/portal/",
            )
        return response


class PortalAPIView(ExternalAPIView):
    def token(self, request: Request) -> str | Response:
        token = request.COOKIES.get(PORTAL_COOKIE, "")
        if not token:
            return _error("authentication_required", "Se requiere una sesión válida.", 401)
        return token


@method_decorator(csrf_protect, name="dispatch")
class PortalSessionView(PortalAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["Portal cliente"])
    def get(self, request: Request) -> Response:
        token = self.token(request)
        if isinstance(token, Response):
            return token
        return _safe(lambda: {"authenticated": True, "events": portal_events(token)})

    @extend_schema(request=None, responses={200: SUCCESS}, tags=["Portal cliente"])
    def post(self, request: Request) -> Response:
        token = self.token(request)
        if isinstance(token, Response):
            return token
        response = _safe(lambda: rotate_session(token))
        if response.status_code == 200:
            new_token, session = response.data
            response.data = {
                "authenticated": True,
                "idle_expires_at": session.idle_expires_at,
                "absolute_expires_at": session.absolute_expires_at,
                "rotation": session.rotation,
            }
            response.set_cookie(
                PORTAL_COOKIE,
                new_token,
                httponly=True,
                secure=settings.SESSION_COOKIE_SECURE,
                samesite="Lax",
                max_age=None,
                path="/api/v1/portal/",
            )
        return response

    @extend_schema(request=None, responses={200: SUCCESS}, tags=["Portal cliente"])
    def delete(self, request: Request) -> Response:
        token = self.token(request)
        if isinstance(token, Response):
            return token
        response = _safe(lambda: revoke_session(token))
        response.delete_cookie(PORTAL_COOKIE, path="/api/v1/portal/")
        return response


class PortalEventsView(PortalAPIView):
    @extend_schema(
        operation_id="portal_event_list", responses={200: SUCCESS}, tags=["Portal cliente"]
    )
    def get(self, request: Request) -> Response:
        token = self.token(request)
        if isinstance(token, Response):
            return token
        return _safe(lambda: {"events": portal_events(token)})


class PortalEventView(PortalAPIView):
    @extend_schema(
        operation_id="portal_event_detail", responses={200: SUCCESS}, tags=["Portal cliente"]
    )
    def get(self, request: Request, grant_id: UUID) -> Response:
        token = self.token(request)
        if isinstance(token, Response):
            return token
        return _safe(lambda: portal_event(token, grant_id=grant_id))


class PortalDocumentsView(PortalAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["Portal cliente"])
    def get(self, request: Request, grant_id: UUID) -> Response:
        token = self.token(request)
        if isinstance(token, Response):
            return token
        return _safe(lambda: {"documents": portal_documents_for_grant(token, grant_id=grant_id)})


class PortalDocumentDownloadView(PortalAPIView):
    @extend_schema(
        responses={200: OpenApiResponse(response=OpenApiTypes.BINARY)},
        tags=["Portal cliente"],
    )
    def get(
        self, request: Request, grant_id: UUID, issued_version_id: UUID, artifact_id: UUID
    ) -> HttpResponse:
        token = self.token(request)
        if isinstance(token, Response):
            return HttpResponse(status=token.status_code)
        try:
            content, media_type, filename = download_document_for_grant(
                token,
                grant_id=grant_id,
                issued_version_id=issued_version_id,
                artifact_id=artifact_id,
                expected_sha256=str(request.query_params.get("sha256", "")),
            )
        except (PortalError, DocumentsPortError, AuthorizationDenied):
            return HttpResponse(status=404)
        response = HttpResponse(content, content_type=media_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


@method_decorator(csrf_protect, name="dispatch")
class PortalDocumentAcceptView(PortalAPIView):
    @extend_schema(
        request=DocumentAcceptSerializer,
        responses={201: SUCCESS},
        tags=["Portal cliente"],
    )
    def post(self, request: Request, grant_id: UUID) -> Response:
        token = self.token(request)
        if isinstance(token, Response):
            return token
        serializer = DocumentAcceptSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        data = serializer.validated_data
        return _safe(
            lambda: {
                "acceptance_id": accept_document_for_grant(
                    token,
                    grant_id=grant_id,
                    issued_version_id=data["issued_version_id"],
                    artifact_id=data["artifact_id"],
                    expected_sha256=str(data["artifact_sha256"]),
                    manifestation_text=str(data["manifestation_text"]),
                    manifestation_version=str(data["manifestation_version"]),
                    idempotency_key=data["idempotency_key"],
                    request_id=request.headers.get("X-Request-ID", ""),
                    correlation_id=request.headers.get("X-Correlation-ID", ""),
                    ip_address=_client_ip(request) or None,
                    user_agent=request.headers.get("User-Agent"),
                )
            },
            created=True,
        )


@method_decorator(csrf_protect, name="dispatch")
class PortalPreferenceView(PortalAPIView):
    @extend_schema(
        request=PreferenceSerializer,
        responses={200: SUCCESS},
        tags=["Portal cliente"],
    )
    def post(self, request: Request) -> Response:
        token = self.token(request)
        if isinstance(token, Response):
            return token
        serializer = PreferenceSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        data = serializer.validated_data
        return _safe(
            lambda: update_client_preference(
                token,
                grant_id=data["grant_id"],
                channel=str(data["channel"]),
                purpose=str(data["purpose"]),
                allow=bool(data["allow"]),
            )
        )


@method_decorator(csrf_protect, name="dispatch")
class InternalAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[Any]] = []

    def actor(self, request: Request) -> User | Response:
        actor = request._request.user
        if not isinstance(actor, User) or not actor.is_authenticated:
            return _error("authentication_required", "Se requiere una sesión válida.", 401)
        return actor


class FormListCreateView(InternalAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["P14 workspace"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        return _safe(lambda: {"forms": list_forms(actor, organization_id)})

    @extend_schema(request=FormCreateSerializer, responses={201: SUCCESS}, tags=["P14 workspace"])
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = FormCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: create_form(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class P14CapabilitiesView(InternalAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["P14 workspace"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor

        def materialize() -> dict[str, list[str]]:
            with authorized_tenant_scope(
                actor, organization_id, Capability.ORGANIZATION_ACCESS
            ) as authorization:
                return {
                    "capabilities": sorted(
                        value.value
                        for value in capabilities_for_role(authorization.role)
                        if value.value.startswith(
                            ("public_form:", "communication_", "portal_grant:")
                        )
                    )
                }

        return _safe(materialize)


class FormPublishView(InternalAPIView):
    @extend_schema(request=None, responses={200: SUCCESS}, tags=["P14 workspace"])
    def post(self, request: Request, organization_id: UUID, version_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        return _safe(lambda: publish_form(actor, organization_id, version_id=version_id))


class FormLocatorRotateView(InternalAPIView):
    @extend_schema(request=None, responses={200: SUCCESS}, tags=["P14 workspace"])
    def post(self, request: Request, organization_id: UUID, form_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        return _safe(lambda: rotate_form_locator(actor, organization_id, form_id=form_id))


class FormRetireView(InternalAPIView):
    @extend_schema(request=None, responses={200: SUCCESS}, tags=["P14 workspace"])
    def post(self, request: Request, organization_id: UUID, form_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        return _safe(lambda: retire_form(actor, organization_id, form_id=form_id))


class FormVersionCreateView(InternalAPIView):
    @extend_schema(
        request=FormVersionCreateSerializer,
        responses={201: SUCCESS},
        tags=["P14 workspace"],
    )
    def post(self, request: Request, organization_id: UUID, form_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = FormVersionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: create_form_version(
                actor,
                organization_id,
                form_id=form_id,
                **serializer.validated_data,
            ),
            created=True,
        )


class GrantListCreateView(InternalAPIView):
    @extend_schema(responses={200: SUCCESS}, tags=["P14 workspace"])
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        return _safe(lambda: {"grants": list_grants(actor, organization_id)})

    @extend_schema(request=GrantIssueSerializer, responses={201: SUCCESS}, tags=["P14 workspace"])
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = GrantIssueSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: issue_grant(actor, organization_id, **serializer.validated_data),
            created=True,
        )


class GrantRevokeView(InternalAPIView):
    @extend_schema(
        request=GrantRevokeSerializer,
        responses={200: SUCCESS},
        tags=["P14 workspace"],
    )
    def post(self, request: Request, organization_id: UUID, grant_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = GrantRevokeSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: revoke_grant(
                actor,
                organization_id,
                grant_id=grant_id,
                revision=int(serializer.validated_data["revision"]),
            )
        )


class WebhookLocatorCreateView(InternalAPIView):
    @extend_schema(
        request=WebhookLocatorSerializer,
        responses={201: SUCCESS},
        tags=["P14 workspace"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = self.actor(request)
        if isinstance(actor, Response):
            return actor
        serializer = WebhookLocatorSerializer(data=request.data)
        if not serializer.is_valid():
            return _error("invalid_request", "La solicitud no es válida.", 400)
        return _safe(
            lambda: create_webhook_locator_internal(
                actor,
                organization_id,
                sender_identity_id=serializer.validated_data["sender_identity_id"],
            ),
            created=True,
        )
