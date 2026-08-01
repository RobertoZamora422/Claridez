"""Contratos JSON de los endpoints organizacionales de solo lectura."""

from typing import Any

from rest_framework import serializers


class OrganizationSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)


class OrganizationListResponseSerializer(serializers.Serializer[dict[str, object]]):
    organizations = OrganizationSerializer(many=True, read_only=True)


class OrganizationContextResponseSerializer(serializers.Serializer[dict[str, object]]):
    organization = OrganizationSerializer(read_only=True, allow_null=True)


class OrganizationContextSelectionSerializer(serializers.Serializer[dict[str, object]]):
    organization_id = serializers.UUIDField()


class OrganizationSettingsSerializer(serializers.Serializer[Any]):
    organization_id = serializers.UUIDField(read_only=True)
    currency = serializers.CharField(read_only=True)
    timezone = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class OrganizationSettingsResponseSerializer(serializers.Serializer[dict[str, object]]):
    settings = OrganizationSettingsSerializer(read_only=True)


class MembershipUserSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    display_name = serializers.CharField(read_only=True)


class MembershipSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField(read_only=True)
    user = MembershipUserSerializer(read_only=True)
    role = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    joined_at = serializers.DateTimeField(read_only=True)
    suspended_at = serializers.DateTimeField(read_only=True, allow_null=True)
    revoked_at = serializers.DateTimeField(read_only=True, allow_null=True)


class MembershipListResponseSerializer(serializers.Serializer[dict[str, object]]):
    memberships = MembershipSerializer(many=True, read_only=True)
