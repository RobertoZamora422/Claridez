from typing import Any, cast

from rest_framework import serializers

from .models import Channel, Purpose, SenderIdentity


class TemplateCreateSerializer(serializers.Serializer[dict[str, object]]):
    name = serializers.CharField(max_length=120)
    channel = serializers.ChoiceField(choices=Channel.choices)
    purpose = serializers.ChoiceField(choices=Purpose.choices)
    subject_template = serializers.CharField(max_length=240, required=False, allow_blank=True)
    body_template = serializers.CharField(max_length=20000)
    variable_names = serializers.ListField(child=serializers.CharField(max_length=80))


class CommunicationTemplateVersionCreateSerializer(serializers.Serializer[dict[str, object]]):
    subject_template = serializers.CharField(max_length=240, required=False, allow_blank=True)
    body_template = serializers.CharField(max_length=20000)
    variable_names = serializers.ListField(child=serializers.CharField(max_length=80))


class IntentCreateSerializer(serializers.Serializer[dict[str, object]]):
    purpose = serializers.ChoiceField(choices=Purpose.choices)
    channel = serializers.ChoiceField(choices=Channel.choices)
    event_request_id = serializers.UUIDField()
    template_version_id = serializers.UUIDField()
    variables = serializers.JSONField(default=dict)
    idempotency_key = serializers.CharField(max_length=160)
    not_before = serializers.DateTimeField(required=False)

    def to_internal_value(self, data: Any) -> dict[str, object]:
        allowed = set(self.fields)
        if not isinstance(data, dict) or set(data) - allowed:
            raise serializers.ValidationError("La procedencia debe resolverse en el servidor.")
        return cast(dict[str, object], super().to_internal_value(data))


class PolicySerializer(serializers.Serializer[dict[str, object]]):
    purpose = serializers.ChoiceField(choices=Purpose.choices)
    channel = serializers.ChoiceField(choices=Channel.choices)
    requires_consent = serializers.BooleanField(default=False)
    allow_unsubscribe = serializers.BooleanField(default=False)
    rationale = serializers.CharField(max_length=500)


class SenderSerializer(serializers.Serializer[dict[str, object]]):
    channel = serializers.ChoiceField(choices=Channel.choices)
    provider = serializers.CharField(max_length=32)
    ownership = serializers.ChoiceField(choices=SenderIdentity.Ownership.choices)
    sender_reference = serializers.CharField(max_length=240)
    display_name = serializers.CharField(max_length=120)


class PreferenceActionSerializer(serializers.Serializer[dict[str, object]]):
    person_id = serializers.UUIDField()
    channel = serializers.ChoiceField(choices=Channel.choices)
    purpose = serializers.ChoiceField(choices=Purpose.choices)
    action = serializers.ChoiceField(choices=["suppress", "restore"])
    reason = serializers.CharField(max_length=500)


class RetrySerializer(serializers.Serializer[dict[str, object]]):
    reason = serializers.CharField(max_length=500)
