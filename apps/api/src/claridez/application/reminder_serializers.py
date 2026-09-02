from rest_framework import serializers

from claridez.communications.models import Channel


class ReminderRequestSerializer(serializers.Serializer[dict[str, object]]):
    kind = serializers.CharField(max_length=16)
    source_id = serializers.UUIDField()
    channel = serializers.ChoiceField(choices=Channel.choices)
    template_version_id = serializers.UUIDField()
    variables = serializers.JSONField(default=dict)
    idempotency_key = serializers.CharField(max_length=160)
    not_before = serializers.DateTimeField()

    def validate_kind(self, value: str) -> str:
        if value not in {"event", "payment", "document"}:
            raise serializers.ValidationError("El tipo de recordatorio no es válido.")
        return value


class ReminderCancelSerializer(serializers.Serializer[dict[str, object]]):
    kind = serializers.CharField(max_length=16)
    source_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=500)

    def validate_kind(self, value: str) -> str:
        if value not in {"event", "payment", "document"}:
            raise serializers.ValidationError("El tipo de recordatorio no es válido.")
        return value
