from __future__ import annotations

from rest_framework import serializers

from claridez.organizations.models import Membership

from .models import EventPreparation, PreparationItem

ELIGIBLE_ROLE_CHOICES = [
    Membership.Role.OWNER,
    Membership.Role.ADMINISTRATOR,
    Membership.Role.OPERATIONS,
]
ERROR_CODE_CHOICES = [
    "authentication_required",
    "resource_not_available",
    "forbidden",
    "invalid_request",
    "stale_revision",
    "invalid_transition",
    "invalid_item_transition",
    "idempotency_conflict",
    "operation_integrity_conflict",
    "operation_already_started",
    "operation_already_completed",
    "reservation_cancelled",
    "responsible_required",
    "baseline_incomplete",
    "blocked_items",
    "required_items_pending",
]


class HistoricalActorSerializer(serializers.Serializer[dict[str, object]]):
    membership_id = serializers.UUIDField()
    display_name = serializers.CharField()
    available = serializers.BooleanField()


class ResponsibleMembershipSerializer(HistoricalActorSerializer):
    role = serializers.ChoiceField(choices=ELIGIBLE_ROLE_CHOICES)


class AssigneeSerializer(serializers.Serializer[dict[str, object]]):
    membership_id = serializers.UUIDField()
    display_name = serializers.CharField()
    role = serializers.ChoiceField(choices=ELIGIBLE_ROLE_CHOICES)


class EventSnapshotSerializer(serializers.Serializer[dict[str, object]]):
    event_type = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    timezone = serializers.CharField()
    estimated_guests = serializers.IntegerField(min_value=1)
    general_need = serializers.CharField()


class OperationalContactSerializer(serializers.Serializer[dict[str, object]]):
    display_name = serializers.CharField()
    phone_e164 = serializers.CharField(required=False)


class AttentionSerializer(serializers.Serializer[dict[str, object]]):
    pending_count = serializers.IntegerField(min_value=0)
    overdue_count = serializers.IntegerField(min_value=0)
    blocked_count = serializers.IntegerField(min_value=0)
    is_overdue = serializers.BooleanField()
    is_upcoming = serializers.BooleanField()
    is_ready = serializers.BooleanField()
    has_blockers = serializers.BooleanField()
    responsible_unavailable = serializers.BooleanField()


class PreparationItemResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    client_request_id = serializers.UUIDField()
    baseline_key = serializers.CharField(allow_null=True)
    section = serializers.ChoiceField(choices=PreparationItem.Section.choices)
    position = serializers.IntegerField(min_value=1)
    title = serializers.CharField()
    is_required = serializers.BooleanField()
    responsible = ResponsibleMembershipSerializer(allow_null=True)
    due_on = serializers.DateField(allow_null=True)
    status = serializers.ChoiceField(choices=PreparationItem.Status.choices)
    notes = serializers.CharField(allow_blank=True)
    status_note = serializers.CharField(allow_blank=True)
    revision = serializers.IntegerField(min_value=1)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    resolved_at = serializers.DateTimeField(required=False)
    resolved_by = HistoricalActorSerializer(required=False)


class PreparationSummarySerializer(serializers.Serializer[dict[str, object]]):
    status = serializers.ChoiceField(choices=EventPreparation.Status.choices)
    revision = serializers.IntegerField(min_value=1)
    responsible = ResponsibleMembershipSerializer(allow_null=True)
    baseline_version = serializers.CharField()
    ready_at = serializers.DateTimeField(allow_null=True)
    ready_by = HistoricalActorSerializer(allow_null=True)
    started_at = serializers.DateTimeField(allow_null=True)
    started_by = HistoricalActorSerializer(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    completed_by = HistoricalActorSerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    attention = AttentionSerializer()


class PreparationDetailSerializer(PreparationSummarySerializer):
    operational_notes = serializers.CharField(allow_blank=True)
    items = PreparationItemResponseSerializer(many=True)


class OperationEventSummarySerializer(serializers.Serializer[dict[str, object]]):
    reservation_id = serializers.UUIDField()
    event = EventSnapshotSerializer()
    contact = OperationalContactSerializer()
    preparation = PreparationSummarySerializer()


class OperationEventDetailSerializer(serializers.Serializer[dict[str, object]]):
    reservation_id = serializers.UUIDField()
    event = EventSnapshotSerializer()
    contact = OperationalContactSerializer()
    preparation = PreparationDetailSerializer()


class EventListResponseSerializer(serializers.Serializer[dict[str, object]]):
    results = OperationEventSummarySerializer(many=True)
    next_cursor = serializers.CharField(allow_null=True)


class CapabilitiesResponseSerializer(serializers.Serializer[dict[str, object]]):
    capabilities = serializers.ListField(child=serializers.CharField())


class AssigneeListResponseSerializer(serializers.Serializer[dict[str, object]]):
    assignees = AssigneeSerializer(many=True)


class ItemPreparationReferenceSerializer(serializers.Serializer[dict[str, object]]):
    status = serializers.ChoiceField(choices=EventPreparation.Status.choices)
    revision = serializers.IntegerField(min_value=1)


class ItemMutationResponseSerializer(serializers.Serializer[dict[str, object]]):
    item = PreparationItemResponseSerializer()
    preparation_revision = serializers.IntegerField(min_value=1)
    preparation = ItemPreparationReferenceSerializer(required=False)


class ErrorDetailSerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.ChoiceField(choices=ERROR_CODE_CHOICES)
    message = serializers.CharField()
    fields = serializers.DictField(  # type: ignore[assignment]
        child=serializers.ListField(child=serializers.CharField()), required=False
    )

    class Meta:
        ref_name = "OperationsErrorDetail"


class ErrorResponseSerializer(serializers.Serializer[dict[str, object]]):
    error = ErrorDetailSerializer()

    class Meta:
        ref_name = "OperationsErrorResponse"
