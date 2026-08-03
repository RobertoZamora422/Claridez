from rest_framework import serializers

from .models import FollowUpTask, Interaction


class InteractionCreateSerializer(serializers.Serializer[dict[str, object]]):
    person_id = serializers.UUIDField()
    event_request_id = serializers.UUIDField(required=False, allow_null=True)
    channel = serializers.ChoiceField(choices=Interaction.Channel.choices)
    direction = serializers.ChoiceField(choices=Interaction.Direction.choices)
    occurred_at = serializers.DateTimeField()
    responsible_membership_id = serializers.UUIDField(required=False, allow_null=True)
    summary = serializers.CharField(max_length=1000)
    correction_of_id = serializers.UUIDField(required=False, allow_null=True)


class TaskCreateSerializer(serializers.Serializer[dict[str, object]]):
    person_id = serializers.UUIDField()
    event_request_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=180)
    due_at = serializers.DateTimeField()
    next_contact_at = serializers.DateTimeField(required=False, allow_null=True)
    responsible_membership_id = serializers.UUIDField(required=False, allow_null=True)


class TaskUpdateSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    title = serializers.CharField(max_length=180, required=False)
    due_at = serializers.DateTimeField(required=False)
    next_contact_at = serializers.DateTimeField(required=False, allow_null=True)
    responsible_membership_id = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=FollowUpTask.Status.choices, required=False)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
