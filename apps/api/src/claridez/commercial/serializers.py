from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import ContactOrigin


class PersonCreateSerializer(serializers.Serializer[dict[str, object]]):
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=40)
    email = serializers.EmailField(
        max_length=254, required=False, allow_blank=True, allow_null=True
    )
    origin = serializers.ChoiceField(choices=ContactOrigin.choices)
    origin_detail = serializers.CharField(
        max_length=160, required=False, allow_blank=True, allow_null=True
    )


class PersonUpdateSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    full_name = serializers.CharField(max_length=150, required=False)
    phone = serializers.CharField(max_length=40, required=False)
    email = serializers.EmailField(
        max_length=254, required=False, allow_blank=True, allow_null=True
    )
    origin = serializers.ChoiceField(choices=ContactOrigin.choices, required=False)
    origin_detail = serializers.CharField(
        max_length=160, required=False, allow_blank=True, allow_null=True
    )


class EventRequestCreateSerializer(serializers.Serializer[dict[str, object]]):
    person_id = serializers.UUIDField()
    event_type_id = serializers.UUIDField()
    space_id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    estimated_guests = serializers.IntegerField(min_value=1)
    general_need = serializers.CharField(max_length=500)
    notes = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    origin = serializers.ChoiceField(choices=ContactOrigin.choices)
    origin_detail = serializers.CharField(
        max_length=160, required=False, allow_blank=True, allow_null=True
    )
    responsible_membership_id = serializers.UUIDField(required=False, allow_null=True)


class EventRequestUpdateSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    event_type_id = serializers.UUIDField(required=False)
    space_id = serializers.UUIDField(required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    estimated_guests = serializers.IntegerField(min_value=1, required=False)
    general_need = serializers.CharField(max_length=500, required=False)
    notes = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    origin = serializers.ChoiceField(choices=ContactOrigin.choices, required=False)
    origin_detail = serializers.CharField(
        max_length=160, required=False, allow_blank=True, allow_null=True
    )
    responsible_membership_id = serializers.UUIDField(required=False)


class ReasonSerializer(serializers.Serializer[dict[str, str]]):
    reason = serializers.CharField(max_length=500)


class AvailabilityQuerySerializer(serializers.Serializer[dict[str, object]]):
    space_id = serializers.UUIDField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class QuotationCreateSerializer(serializers.Serializer[dict[str, object]]):
    valid_until = serializers.DateTimeField()


class QuotationLineInputSerializer(serializers.Serializer[dict[str, object]]):
    catalog_item_id = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(max_length=240, required=False)
    unit_label = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True
    )
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)
    discount_amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, default=Decimal("0.00")
    )


class QuotationDraftSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    valid_until = serializers.DateTimeField()
    notes = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    lines = QuotationLineInputSerializer(many=True, allow_empty=False)


class QuotationAcceptSerializer(serializers.Serializer[dict[str, str]]):
    channel = serializers.ChoiceField(
        choices=["in_person", "phone_call", "whatsapp", "email", "other"]
    )
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ReservationConfirmSerializer(serializers.Serializer[dict[str, object]]):
    kind = serializers.ChoiceField(choices=["external_deposit", "waiver"])
    recognized_amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, required=False, allow_null=True
    )
    reported_at = serializers.DateTimeField(required=False, allow_null=True)
    reference = serializers.CharField(max_length=300, required=False, allow_blank=True)
    waiver_reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
