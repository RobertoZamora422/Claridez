from rest_framework import serializers


class BusinessConfigurationSerializer(serializers.Serializer[dict[str, object]]):
    name = serializers.CharField(max_length=150)
    currency = serializers.CharField(max_length=3)
    timezone = serializers.CharField(max_length=64)


class VenueCreateSerializer(serializers.Serializer[dict[str, object]]):
    name = serializers.CharField(max_length=150)
    location_reference = serializers.CharField(max_length=300, required=False, allow_blank=True)
    is_primary = serializers.BooleanField(required=False, default=False)


class VenueUpdateSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=150, required=False)
    location_reference = serializers.CharField(max_length=300, required=False, allow_blank=True)
    is_primary = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)


class SpaceCreateSerializer(serializers.Serializer[dict[str, object]]):
    name = serializers.CharField(max_length=150)
    is_primary = serializers.BooleanField(required=False, default=False)


class SpaceUpdateSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=150, required=False)
    is_primary = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
