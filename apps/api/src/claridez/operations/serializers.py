from __future__ import annotations

from rest_framework import serializers

from .models import EventPreparation, PreparationItem


class EventListQuerySerializer(serializers.Serializer[dict[str, object]]):
    from_date = serializers.DateField(required=False)
    to_date = serializers.DateField(required=False)
    status = serializers.ListField(
        child=serializers.ChoiceField(choices=EventPreparation.Status.choices), required=False
    )
    attention = serializers.ChoiceField(
        choices=["overdue", "upcoming", "blocked", "ready", "unassigned"], required=False
    )
    responsible_membership_id = serializers.UUIDField(required=False)
    cursor = serializers.IntegerField(min_value=0, required=False, default=0)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False, default=25)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        start = attrs.get("from_date")
        end = attrs.get("to_date")
        if start and end:
            if start > end:  # type: ignore[operator]
                raise serializers.ValidationError("El periodo no es válido.")
            if (end - start).days > 366:  # type: ignore[operator]
                raise serializers.ValidationError("El periodo máximo es 366 días.")
        return attrs


class PreparationUpdateSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    operational_notes = serializers.CharField(max_length=4000, allow_blank=True)


class AssignmentSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    responsible_membership_id = serializers.UUIDField()


class RevisionSerializer(serializers.Serializer[dict[str, int]]):
    revision = serializers.IntegerField(min_value=1)


class ItemCreateSerializer(serializers.Serializer[dict[str, object]]):
    client_request_id = serializers.UUIDField()
    title = serializers.CharField(max_length=160)
    section = serializers.ChoiceField(choices=PreparationItem.Section.choices)
    is_required = serializers.BooleanField()
    due_on = serializers.DateField(required=False, allow_null=True)
    responsible_membership_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    place_before_item_id = serializers.UUIDField(required=False, allow_null=True)


class ItemUpdateSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    title = serializers.CharField(max_length=160, required=False)
    section = serializers.ChoiceField(choices=PreparationItem.Section.choices, required=False)
    is_required = serializers.BooleanField(required=False)
    due_on = serializers.DateField(required=False, allow_null=True)
    responsible_membership_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=PreparationItem.Status.choices, required=False)
    status_note = serializers.CharField(max_length=500, required=False, allow_blank=True)
    place_before_item_id = serializers.UUIDField(required=False, allow_null=True)
