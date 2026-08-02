from decimal import Decimal

from rest_framework import serializers

from .models import CatalogItem


class EventTypeCreateSerializer(serializers.Serializer[dict[str, object]]):
    name = serializers.CharField(max_length=100)


class EventTypeUpdateSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=100)
    is_active = serializers.BooleanField()


class PackageComponentInputSerializer(serializers.Serializer[dict[str, object]]):
    item_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class CatalogItemCreateSerializer(serializers.Serializer[dict[str, object]]):
    kind = serializers.ChoiceField(choices=CatalogItem.Kind.choices)
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    unit_label = serializers.CharField(max_length=40)
    components = PackageComponentInputSerializer(many=True, required=False, default=list)


class CatalogItemUpdateSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    unit_label = serializers.CharField(max_length=40)
    is_active = serializers.BooleanField()
    components = PackageComponentInputSerializer(many=True, required=False, default=list)


class CatalogPriceCreateSerializer(serializers.Serializer[dict[str, object]]):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    valid_from = serializers.DateTimeField()
    valid_until = serializers.DateTimeField(required=False, allow_null=True)
