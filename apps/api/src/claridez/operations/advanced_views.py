from __future__ import annotations

from typing import Any
from urllib.parse import quote
from uuid import UUID

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from claridez.identity.models import User
from claridez.organizations.exceptions import AuthorizationDenied, TenantAccessDenied

from .advanced import (
    adopt_legacy_preparation,
    advanced_event_detail,
    amend_incident,
    assign_operational_responsibility,
    attach_operational_evidence,
    close_post_event,
    correct_incident_event,
    correct_phase_fact,
    correct_post_event_close,
    correct_verification,
    create_template_version,
    decide_change,
    download_operational_evidence,
    list_template_versions,
    open_incident,
    propose_change,
    publish_template_version,
    record_phase_fact,
    reserve_operational_window,
    retire_template_version,
    transition_incident,
    update_verification,
)
from .advanced_serializers import (
    AdvancedEventResponseSerializer,
    ChangeDecisionSerializer,
    ChangeProposalSerializer,
    ChangeResponseSerializer,
    CloseResponseSerializer,
    CorrectionResponseSerializer,
    EvidenceCreateSerializer,
    EvidenceResponseSerializer,
    IncidentAmendSerializer,
    IncidentCorrectionSerializer,
    IncidentCreateSerializer,
    IncidentResponseSerializer,
    IncidentTransitionSerializer,
    LegacyAdoptionSerializer,
    PhaseFactCorrectionSerializer,
    PhaseFactCreateSerializer,
    PhaseFactResponseSerializer,
    PostEventCloseCorrectionSerializer,
    PostEventCloseSerializer,
    ResponsibilityCreateSerializer,
    ResponsibilityResponseSerializer,
    SnapshotResponseSerializer,
    TemplatePublishSerializer,
    TemplateVersionCreateSerializer,
    TemplateVersionResponseSerializer,
    VerificationCorrectionSerializer,
    VerificationResponseSerializer,
    VerificationUpdateSerializer,
    WindowReservationResponseSerializer,
    WindowReserveSerializer,
)
from .api_schemas import ErrorResponseSerializer
from .errors import OperationsError
from .views import OperationsAPIView, _exception_response, _respond, _validated


def _actor(view: OperationsAPIView, request: Request) -> User | Response:
    return view.actor_or_response(request)


def _data(serializer: serializers.Serializer[Any]) -> dict[str, Any]:
    return dict(serializer.validated_data)


class TemplateVersionListCreateView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_template_versions_list",
        responses={
            200: TemplateVersionResponseSerializer(many=True),
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def get(self, request: Request, organization_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        return _respond(lambda: list_template_versions(actor, organization_id))

    @extend_schema(
        operation_id="operations_template_versions_create",
        request=TemplateVersionCreateSerializer,
        responses={
            201: TemplateVersionResponseSerializer,
            400: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(self, request: Request, organization_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = TemplateVersionCreateSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        values = _data(serializer)
        return _respond(
            lambda: create_template_version(actor, organization_id, **values), created=True
        )


class TemplateVersionPublishView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_template_version_publish",
        request=TemplatePublishSerializer,
        responses={
            200: TemplateVersionResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(self, request: Request, organization_id: UUID, version_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = TemplatePublishSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: publish_template_version(
                actor, organization_id, version_id=version_id, **_data(serializer)
            )
        )


class TemplateVersionRetireView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_template_version_retire",
        request=TemplatePublishSerializer,
        responses={
            200: TemplateVersionResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(self, request: Request, organization_id: UUID, version_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = TemplatePublishSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: retire_template_version(
                actor, organization_id, version_id=version_id, **_data(serializer)
            )
        )


class AdvancedEventView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_advanced_event_retrieve",
        responses={
            200: AdvancedEventResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def get(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        return _respond(
            lambda: advanced_event_detail(actor, organization_id, reservation_id=reservation_id)
        )


class LegacyAdoptionView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_advanced_event_adopt_legacy",
        request=LegacyAdoptionSerializer,
        responses={
            201: SnapshotResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = LegacyAdoptionSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: adopt_legacy_preparation(
                actor, organization_id, reservation_id=reservation_id, **_data(serializer)
            ),
            created=True,
        )


class VerificationUpdateView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_verification_update",
        request=VerificationUpdateSerializer,
        responses={
            200: VerificationResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def put(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        verification_id: UUID,
    ) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = VerificationUpdateSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: update_verification(
                actor,
                organization_id,
                reservation_id=reservation_id,
                verification_id=verification_id,
                **_data(serializer),
            )
        )


class VerificationCorrectionView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_verification_correct",
        request=VerificationCorrectionSerializer,
        responses={
            201: VerificationResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        verification_id: UUID,
        event_id: UUID,
    ) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = VerificationCorrectionSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: correct_verification(
                actor,
                organization_id,
                reservation_id=reservation_id,
                verification_id=verification_id,
                event_id=event_id,
                **_data(serializer),
            ),
            created=True,
        )


class PhaseFactCreateView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_phase_fact_create",
        request=PhaseFactCreateSerializer,
        responses={
            201: PhaseFactResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = PhaseFactCreateSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: record_phase_fact(
                actor, organization_id, reservation_id=reservation_id, **_data(serializer)
            ),
            created=True,
        )


class PhaseFactCorrectionView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_phase_fact_correct",
        request=PhaseFactCorrectionSerializer,
        responses={
            201: PhaseFactResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        fact_id: UUID,
    ) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = PhaseFactCorrectionSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: correct_phase_fact(
                actor,
                organization_id,
                reservation_id=reservation_id,
                fact_id=fact_id,
                **_data(serializer),
            ),
            created=True,
        )


class ResponsibilityCreateView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_responsibility_assign",
        request=ResponsibilityCreateSerializer,
        responses={
            201: ResponsibilityResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = ResponsibilityCreateSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: assign_operational_responsibility(
                actor, organization_id, reservation_id=reservation_id, **_data(serializer)
            ),
            created=True,
        )


class IncidentCreateView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_incident_create",
        request=IncidentCreateSerializer,
        responses={
            201: IncidentResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = IncidentCreateSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: open_incident(
                actor, organization_id, reservation_id=reservation_id, **_data(serializer)
            ),
            created=True,
        )


class IncidentTransitionView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_incident_transition",
        request=IncidentTransitionSerializer,
        responses={
            200: IncidentResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        incident_id: UUID,
    ) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = IncidentTransitionSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: transition_incident(
                actor,
                organization_id,
                reservation_id=reservation_id,
                incident_id=incident_id,
                **_data(serializer),
            )
        )


class IncidentAmendView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_incident_amend",
        request=IncidentAmendSerializer,
        responses={
            200: IncidentResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        incident_id: UUID,
    ) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = IncidentAmendSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: amend_incident(
                actor,
                organization_id,
                reservation_id=reservation_id,
                incident_id=incident_id,
                **_data(serializer),
            )
        )


class IncidentCorrectionView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_incident_event_correct",
        request=IncidentCorrectionSerializer,
        responses={
            201: IncidentResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        incident_id: UUID,
        event_id: UUID,
    ) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = IncidentCorrectionSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: correct_incident_event(
                actor,
                organization_id,
                reservation_id=reservation_id,
                incident_id=incident_id,
                event_id=event_id,
                **_data(serializer),
            ),
            created=True,
        )


class ChangeProposalView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_change_propose",
        request=ChangeProposalSerializer,
        responses={
            201: ChangeResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = ChangeProposalSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: propose_change(
                actor, organization_id, reservation_id=reservation_id, **_data(serializer)
            ),
            created=True,
        )


class ChangeDecisionView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_change_decide",
        request=ChangeDecisionSerializer,
        responses={
            200: ChangeResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        proposal_id: UUID,
    ) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = ChangeDecisionSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: decide_change(
                actor,
                organization_id,
                reservation_id=reservation_id,
                proposal_id=proposal_id,
                **_data(serializer),
            )
        )


class WindowReserveView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_window_reserve",
        request=WindowReserveSerializer,
        responses={
            201: WindowReservationResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        window_id: UUID,
    ) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = WindowReserveSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: reserve_operational_window(
                actor,
                organization_id,
                reservation_id=reservation_id,
                window_id=window_id,
                **_data(serializer),
            ),
            created=True,
        )


class EvidenceCreateView(OperationsAPIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="operations_evidence_create",
        request=EvidenceCreateSerializer,
        responses={
            201: EvidenceResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = EvidenceCreateSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        values = _data(serializer)
        values["source"] = values.pop("file")
        return _respond(
            lambda: attach_operational_evidence(
                actor, organization_id, reservation_id=reservation_id, **values
            ),
            created=True,
        )


class EvidenceDownloadView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_evidence_download",
        responses={
            (200, "application/octet-stream"): OpenApiTypes.BINARY,
            404: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def get(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        file_id: UUID,
    ) -> Response | HttpResponse:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        try:
            content, media_type, filename = download_operational_evidence(
                actor,
                organization_id,
                reservation_id=reservation_id,
                file_id=file_id,
            )
        except (TenantAccessDenied, AuthorizationDenied, OperationsError) as error:
            return _exception_response(error)
        response = HttpResponse(content, content_type=media_type)
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class PostEventCloseView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_post_event_close",
        request=PostEventCloseSerializer,
        responses={
            201: CloseResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(self, request: Request, organization_id: UUID, reservation_id: UUID) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = PostEventCloseSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: close_post_event(
                actor, organization_id, reservation_id=reservation_id, **_data(serializer)
            ),
            created=True,
        )


class PostEventCloseCorrectionView(OperationsAPIView):
    @extend_schema(
        operation_id="operations_post_event_close_correct",
        request=PostEventCloseCorrectionSerializer,
        responses={
            201: CorrectionResponseSerializer,
            400: ErrorResponseSerializer,
            409: ErrorResponseSerializer,
        },
        tags=["Operaciones P13"],
    )
    def post(
        self,
        request: Request,
        organization_id: UUID,
        reservation_id: UUID,
        close_id: UUID,
    ) -> Response:
        actor = _actor(self, request)
        if isinstance(actor, Response):
            return actor
        serializer = PostEventCloseCorrectionSerializer(data=request.data)
        error = _validated(serializer)
        if error:
            return error
        return _respond(
            lambda: correct_post_event_close(
                actor,
                organization_id,
                reservation_id=reservation_id,
                close_id=close_id,
                **_data(serializer),
            ),
            created=True,
        )
