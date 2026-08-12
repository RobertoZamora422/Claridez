from __future__ import annotations

from datetime import datetime
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import ScheduleBlock


@extend_schema_field(
    {
        "type": "string",
        "format": "date-time",
        "description": "Fecha y hora local ISO sin offset; la zona se envía por separado.",
        "example": "2026-08-15T18:30",
    }
)
class NaiveLocalDateTimeField(serializers.Field[datetime, object, str, Any]):
    def to_internal_value(self, data: object) -> datetime:
        if not isinstance(data, str):
            raise serializers.ValidationError("Debe ser una fecha y hora local ISO.")
        try:
            value = datetime.fromisoformat(data)
        except ValueError:
            raise serializers.ValidationError("Debe ser una fecha y hora local ISO.") from None
        if value.tzinfo is not None:
            raise serializers.ValidationError("La hora local no debe incluir offset.")
        return value

    def to_representation(self, value: datetime) -> str:
        return value.isoformat(timespec="minutes")


class CalendarQuerySerializer(serializers.Serializer[dict[str, object]]):
    view = serializers.ChoiceField(choices=["day", "week", "month"])
    anchor_date = serializers.DateField()
    venue_id = serializers.UUIDField(required=False)
    space_id = serializers.UUIDField(required=False)
    types = serializers.ListField(
        child=serializers.ChoiceField(choices=["reservation", "hold", "block"]),
        required=False,
    )


class AdvancedAvailabilitySerializer(serializers.Serializer[dict[str, object]]):
    starts_at_local = NaiveLocalDateTimeField()
    ends_at_local = NaiveLocalDateTimeField()
    timezone = serializers.CharField(max_length=64)
    space_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, allow_empty=False
    )


class PolicySerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=0)
    setup_minutes = serializers.IntegerField(min_value=0)
    teardown_minutes = serializers.IntegerField(min_value=0)
    buffer_before_minutes = serializers.IntegerField(min_value=0)
    buffer_after_minutes = serializers.IntegerField(min_value=0)


class BlockCreateSerializer(serializers.Serializer[dict[str, object]]):
    idempotency_key = serializers.UUIDField()
    scope = serializers.ChoiceField(choices=ScheduleBlock.Scope.choices)
    venue_id = serializers.UUIDField()
    space_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )
    starts_at_local = NaiveLocalDateTimeField()
    ends_at_local = NaiveLocalDateTimeField()
    timezone = serializers.CharField(max_length=64)
    reason = serializers.CharField(max_length=500)


class BlockTerminationSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=500)


class RescheduleSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.UUIDField()
    space_id = serializers.UUIDField()
    starts_at_local = NaiveLocalDateTimeField()
    ends_at_local = NaiveLocalDateTimeField()
    timezone = serializers.CharField(max_length=64)
    reason = serializers.CharField(max_length=500)
    commercial_terms_unchanged = serializers.BooleanField()
    carry_free_item_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )


class DomainErrorDetailSerializer(serializers.Serializer[dict[str, object]]):
    code = serializers.CharField()
    message = serializers.CharField()


class DomainErrorSerializer(serializers.Serializer[dict[str, object]]):
    error = DomainErrorDetailSerializer()


class SchedulingCapabilitiesResponseSerializer(serializers.Serializer[dict[str, object]]):
    capabilities = serializers.ListField(child=serializers.CharField())


class IntervalSerializer(serializers.Serializer[dict[str, object]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class PolicyResponseSerializer(serializers.Serializer[dict[str, object]]):
    space_id = serializers.UUIDField()
    setup_minutes = serializers.IntegerField()
    teardown_minutes = serializers.IntegerField()
    buffer_before_minutes = serializers.IntegerField()
    buffer_after_minutes = serializers.IntegerField()
    revision = serializers.IntegerField()


class AvailabilityConflictSerializer(serializers.Serializer[dict[str, object]]):
    type = serializers.ChoiceField(choices=["reservation", "block"])
    occupied_interval = IntervalSerializer()


class AvailabilitySpaceSerializer(serializers.Serializer[dict[str, object]]):
    space_id = serializers.UUIDField()
    available = serializers.BooleanField()
    occupied_interval = IntervalSerializer()
    policy = PolicyResponseSerializer()
    conflicts = AvailabilityConflictSerializer(many=True)


class AvailabilityResponseSerializer(serializers.Serializer[dict[str, object]]):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    timezone = serializers.CharField()
    spaces = AvailabilitySpaceSerializer(many=True)


class CalendarEntrySerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=["reservation", "hold", "block"])
    status = serializers.CharField()
    revision = serializers.IntegerField()
    root_id = serializers.UUIDField(required=False)
    space_id = serializers.UUIDField()
    space_name = serializers.CharField()
    venue_id = serializers.UUIDField()
    venue_name = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    occupied_interval = IntervalSerializer()
    event_timezone = serializers.CharField()
    setup_minutes = serializers.IntegerField(required=False)
    teardown_minutes = serializers.IntegerField(required=False)
    buffer_before_minutes = serializers.IntegerField(required=False)
    buffer_after_minutes = serializers.IntegerField(required=False)
    reason = serializers.CharField(required=False)
    is_blocking = serializers.BooleanField()


class CalendarResponseSerializer(serializers.Serializer[dict[str, object]]):
    view = serializers.ChoiceField(choices=["day", "week", "month"])
    anchor_date = serializers.DateField()
    timezone = serializers.CharField()
    entries = CalendarEntrySerializer(many=True)


CalendarResponseSerializer._declared_fields["from"] = serializers.DateTimeField()
CalendarResponseSerializer._declared_fields["to"] = serializers.DateTimeField()


class BlockResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    venue_id = serializers.UUIDField()
    scope = serializers.ChoiceField(choices=ScheduleBlock.Scope.choices)
    space_ids = serializers.ListField(child=serializers.UUIDField())
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    event_timezone = serializers.CharField()
    reason = serializers.CharField()
    status = serializers.ChoiceField(choices=ScheduleBlock.Status.choices)
    revision = serializers.IntegerField()
    ended_at = serializers.DateTimeField(allow_null=True)
    termination_reason = serializers.CharField(allow_null=True)


class BlockListResponseSerializer(serializers.Serializer[dict[str, object]]):
    results = BlockResponseSerializer(many=True)


class ReservationResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    root_id = serializers.UUIDField()
    predecessor_id = serializers.UUIDField(allow_null=True)
    space_id = serializers.UUIDField()
    status = serializers.CharField()
    revision = serializers.IntegerField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    event_timezone = serializers.CharField()
    occupied_interval = IntervalSerializer(allow_null=True)
    setup_minutes = serializers.IntegerField()
    teardown_minutes = serializers.IntegerField()
    buffer_before_minutes = serializers.IntegerField()
    buffer_after_minutes = serializers.IntegerField()
    hold_expires_at = serializers.DateTimeField()
    confirmation_kind = serializers.CharField(allow_null=True)
    recognized_deposit_amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, allow_null=True
    )
    deposit_reported_at = serializers.DateTimeField(allow_null=True)
    deposit_reference = serializers.CharField(allow_null=True)
    confirmed_at = serializers.DateTimeField(allow_null=True)
    waiver_reason = serializers.CharField(allow_null=True)
    waiver_authorized_at = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    cancellation_reason = serializers.CharField(allow_null=True)


class RescheduleResponseSerializer(serializers.Serializer[dict[str, object]]):
    previous = serializers.JSONField()
    reservation = ReservationResponseSerializer()
    carried_item_ids = serializers.ListField(child=serializers.UUIDField())


class ScheduleEventResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    source = serializers.CharField()  # type: ignore[assignment]
    reason = serializers.CharField(allow_null=True)
    actor_membership_id = serializers.UUIDField(allow_null=True)
    reservation_id = serializers.UUIDField(allow_null=True)
    predecessor_id = serializers.UUIDField(allow_null=True)
    successor_id = serializers.UUIDField(allow_null=True)
    aggregate_revision = serializers.IntegerField()
    previous_snapshot = serializers.JSONField()
    new_snapshot = serializers.JSONField()
    occurred_at = serializers.DateTimeField()
    recorded_at = serializers.DateTimeField()


class ScheduleHistoryResponseSerializer(serializers.Serializer[dict[str, object]]):
    results = ScheduleEventResponseSerializer(many=True)
