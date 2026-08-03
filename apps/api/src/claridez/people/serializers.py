from rest_framework import serializers

from .models import ConsentEvent


class PersonMergeSerializer(serializers.Serializer[dict[str, object]]):
    source_person_id = serializers.UUIDField()
    target_person_id = serializers.UUIDField()
    source_revision = serializers.IntegerField(min_value=1)
    target_revision = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=500)
    idempotency_key = serializers.UUIDField()


class ConsentEventSerializer(serializers.Serializer[dict[str, object]]):
    purpose = serializers.CharField(max_length=80)
    channel = serializers.ChoiceField(choices=ConsentEvent.Channel.choices)
    event_type = serializers.ChoiceField(choices=ConsentEvent.EventType.choices)
    decision = serializers.ChoiceField(choices=ConsentEvent.Decision.choices)
    source = serializers.CharField(max_length=80)  # type: ignore[assignment]
    occurred_at = serializers.DateTimeField()
    evidence_reference = serializers.CharField(max_length=240)
    corrects_id = serializers.UUIDField(required=False, allow_null=True)
