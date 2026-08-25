from __future__ import annotations

from rest_framework import serializers

from .advanced_models import (
    OperationalChangeProposal,
    OperationalEvidence,
    OperationalIncident,
    OperationalPhaseFact,
    OperationalVerification,
)

VERIFICATION_RESOLUTION_STATUS_CHOICES = (
    OperationalVerification.Status.COMPLETED,
    OperationalVerification.Status.NOT_APPLICABLE,
)
INCIDENT_TRANSITION_STATUS_CHOICES = (
    OperationalIncident.Status.CONTAINED,
    OperationalIncident.Status.RESOLVED,
)


class IdempotentSerializer(serializers.Serializer[dict[str, object]]):
    idempotency_key = serializers.UUIDField()


class TemplateVersionCreateSerializer(IdempotentSerializer):
    event_type_id = serializers.UUIDField()
    name = serializers.CharField(max_length=160)
    definitions = serializers.DictField()


class TemplatePublishSerializer(IdempotentSerializer):
    pass


class LegacyAdoptionSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)


class VerificationUpdateSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=VERIFICATION_RESOLUTION_STATUS_CHOICES)
    reason = serializers.CharField(allow_blank=True, max_length=500)


class VerificationCorrectionSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=VERIFICATION_RESOLUTION_STATUS_CHOICES)
    status_reason = serializers.CharField(allow_blank=True, max_length=500)
    correction_reason = serializers.CharField(max_length=500)


class PhaseFactCreateSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)
    phase = serializers.ChoiceField(choices=OperationalPhaseFact.Phase.choices)
    fact_kind = serializers.ChoiceField(choices=OperationalPhaseFact.FactKind.choices)
    observed_at = serializers.DateTimeField(required=False, allow_null=True)


class PhaseFactCorrectionSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)
    observed_at = serializers.DateTimeField()
    reason = serializers.CharField(max_length=500)


class ResponsibilityCreateSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)
    role_key = serializers.CharField(max_length=64)
    phase = serializers.CharField(max_length=16, allow_blank=True)
    membership_id = serializers.UUIDField(required=False, allow_null=True)


class IncidentCreateSerializer(IdempotentSerializer):
    incident_type = serializers.ChoiceField(choices=OperationalIncident.Type.choices)
    severity = serializers.ChoiceField(choices=OperationalIncident.Severity.choices)
    description = serializers.CharField(max_length=1000)
    impact = serializers.CharField(max_length=1000)
    responsible_membership_id = serializers.UUIDField(required=False, allow_null=True)


class IncidentTransitionSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=INCIDENT_TRANSITION_STATUS_CHOICES)
    detail = serializers.CharField(max_length=1000)


class IncidentAmendSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)
    kind = serializers.ChoiceField(
        choices=[
            "reassigned",
            "impact_updated",
        ]
    )
    impact = serializers.CharField(max_length=1000)
    responsible_membership_id = serializers.UUIDField(required=False, allow_null=True)
    detail = serializers.CharField(max_length=1000)


class IncidentCorrectionSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)
    severity = serializers.ChoiceField(choices=OperationalIncident.Severity.choices)
    impact = serializers.CharField(max_length=1000)
    responsible_membership_id = serializers.UUIDField(required=False, allow_null=True)
    detail = serializers.CharField(max_length=1000)


class ChangeProposalSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)
    scope = serializers.ChoiceField(choices=OperationalChangeProposal.Scope.choices)
    target_id = serializers.UUIDField()
    proposed_payload = serializers.DictField()
    reason = serializers.CharField(max_length=1000)
    impact = serializers.CharField(max_length=1000)


class ChangeDecisionSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)
    approved = serializers.BooleanField()
    reason = serializers.CharField(max_length=1000)


class WindowReserveSerializer(IdempotentSerializer):
    reason = serializers.CharField(max_length=500)


class EvidenceCreateSerializer(IdempotentSerializer):
    target_kind = serializers.ChoiceField(choices=OperationalEvidence.TargetKind.choices)
    target_id = serializers.UUIDField()
    display_name = serializers.CharField(max_length=255)
    declared_media_type = serializers.CharField(max_length=120)
    correlation_id = serializers.CharField(max_length=128)
    file = serializers.FileField()


class PostEventCloseSerializer(IdempotentSerializer):
    revision = serializers.IntegerField(min_value=1)


class PostEventCloseCorrectionSerializer(IdempotentSerializer):
    reason = serializers.CharField(max_length=1000)
    correction_payload = serializers.DictField()


class TemplateVersionResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    template_id = serializers.UUIDField()
    event_type_id = serializers.UUIDField()
    name = serializers.CharField()
    version = serializers.IntegerField()
    status = serializers.CharField()
    content_sha256 = serializers.CharField()
    published_at = serializers.DateTimeField(allow_null=True)
    definitions = serializers.JSONField()


class SnapshotResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    source_kind = serializers.ChoiceField(choices=["organization", "system", "legacy_cutover"])
    source_version = serializers.CharField()
    event_type_id = serializers.UUIDField()
    event_type_label = serializers.CharField(required=False)
    content_sha256 = serializers.CharField()
    roles = serializers.ListField(child=serializers.DictField(), required=False)


class VerificationEventResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    from_status = serializers.CharField()
    to_status = serializers.CharField()
    reason = serializers.CharField()
    correction_reason = serializers.CharField()
    corrects_id = serializers.UUIDField(allow_null=True)
    occurred_at = serializers.DateTimeField()


class VerificationResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    source_key = serializers.CharField()
    phase = serializers.ChoiceField(choices=["setup", "execution", "teardown", "post_event"])
    title = serializers.CharField()
    is_required = serializers.BooleanField()
    role_key = serializers.CharField()
    position = serializers.IntegerField()
    status = serializers.CharField()
    status_reason = serializers.CharField()
    completed_at = serializers.DateTimeField(allow_null=True)
    completed_by_membership_id = serializers.UUIDField(allow_null=True)
    revision = serializers.IntegerField()
    events = VerificationEventResponseSerializer(many=True)


class PhaseFactResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    phase = serializers.ChoiceField(choices=["setup", "teardown"])
    fact_kind = serializers.ChoiceField(choices=["started", "completed"])
    observed_at = serializers.DateTimeField()
    actor_membership_id = serializers.UUIDField()
    preparation_revision = serializers.IntegerField()
    provenance = serializers.CharField()
    corrects_id = serializers.UUIDField(allow_null=True)
    correction_reason = serializers.CharField()


class ResponsibilityResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    role_key = serializers.CharField()
    phase = serializers.CharField()
    membership_id = serializers.UUIDField(allow_null=True)
    supersedes_id = serializers.UUIDField(allow_null=True)
    assigned_by_membership_id = serializers.UUIDField()
    preparation_revision = serializers.IntegerField()


class IncidentResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    incident_type = serializers.CharField()
    severity = serializers.ChoiceField(choices=OperationalIncident.Severity.choices)
    status = serializers.CharField()
    description = serializers.CharField()
    impact = serializers.CharField()
    responsible_membership_id = serializers.UUIDField(allow_null=True)
    reported_by_membership_id = serializers.UUIDField()
    reported_at = serializers.DateTimeField()
    revision = serializers.IntegerField()
    events = serializers.ListField(child=serializers.DictField())


class ChangeResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    scope = serializers.CharField()
    target_id = serializers.UUIDField()
    before = serializers.JSONField()
    proposed = serializers.JSONField()
    reason = serializers.CharField()
    impact = serializers.CharField()
    status = serializers.CharField()
    proposed_by_membership_id = serializers.UUIDField()
    decision = serializers.JSONField(allow_null=True)


class WindowResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    resource_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    window_revision = serializers.IntegerField()
    source_kind = serializers.CharField()
    source_version = serializers.CharField()
    schedule_allocation_id = serializers.UUIDField()
    schedule_event_id = serializers.UUIDField()
    schedule_reservation_revision = serializers.IntegerField()
    schedule_source_revision = serializers.IntegerField()
    predecessor_id = serializers.UUIDField(allow_null=True)


class RequirementResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    resource_id = serializers.UUIDField()
    resource_name = serializers.CharField()
    resource_nature = serializers.CharField()
    status = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    temporal_source = serializers.CharField()
    operational_window_id = serializers.UUIDField(allow_null=True)
    supplier_names = serializers.ListField(child=serializers.CharField())
    assignments = serializers.ListField(child=serializers.DictField())


class EvidenceResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    target_kind = serializers.CharField()
    target_id = serializers.UUIDField()
    document_file_id = serializers.UUIDField()
    linked_by_membership_id = serializers.UUIDField()
    created_at = serializers.DateTimeField()


class CloseResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    closed_at = serializers.DateTimeField()
    closed_by_membership_id = serializers.UUIDField()
    preparation_revision = serializers.IntegerField()
    source_sha256 = serializers.CharField()


class AdvancedEventResponseSerializer(serializers.Serializer[dict[str, object]]):
    snapshot = SnapshotResponseSerializer()
    verifications = VerificationResponseSerializer(many=True)
    phase_facts = PhaseFactResponseSerializer(many=True)
    responsibilities = ResponsibilityResponseSerializer(many=True)
    incidents = IncidentResponseSerializer(many=True)
    changes = ChangeResponseSerializer(many=True)
    resource_windows = WindowResponseSerializer(many=True)
    resources = RequirementResponseSerializer(many=True)
    evidence = EvidenceResponseSerializer(many=True)
    close = CloseResponseSerializer(allow_null=True)
    metrics = serializers.JSONField()


class WindowReservationResponseSerializer(serializers.Serializer[dict[str, object]]):
    requirement_id = serializers.UUIDField()
    window_id = serializers.UUIDField()


class CorrectionResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    close_id = serializers.UUIDField(required=False)
    created_at = serializers.DateTimeField(required=False)
