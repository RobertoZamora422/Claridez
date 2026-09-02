from rest_framework import serializers

from claridez.communications.public import Channel
from claridez.portal.models import PortalChallenge


class AvailabilitySerializer(serializers.Serializer[dict[str, object]]):
    event_type_id = serializers.UUIDField()
    space_id = serializers.UUIDField()
    starts_at_local = serializers.RegexField(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    duration_minutes = serializers.IntegerField(min_value=15, max_value=1440)


class SubmissionSerializer(AvailabilitySerializer):
    idempotency_key = serializers.CharField(max_length=160)
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=32)
    email = serializers.EmailField(required=False, allow_blank=True)
    estimated_guests = serializers.IntegerField(min_value=1, max_value=100000)
    general_need = serializers.CharField(max_length=500)
    notes = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    consents = serializers.JSONField(default=dict)
    attribution = serializers.JSONField(default=dict)
    antiabuse_token = serializers.CharField(max_length=4096)
    antiabuse_hostname = serializers.CharField(max_length=240)


class ChallengeStartSerializer(serializers.Serializer[dict[str, object]]):
    form_locator = serializers.CharField(max_length=240)
    channel = serializers.ChoiceField(choices=Channel.choices)
    contact = serializers.CharField(max_length=254)
    kind = serializers.ChoiceField(
        choices=PortalChallenge.Kind.choices,
        default=PortalChallenge.Kind.AUTHENTICATION,
    )
    antiabuse_token = serializers.CharField(max_length=4096)
    antiabuse_hostname = serializers.CharField(max_length=240)


class ChallengeVerifySerializer(serializers.Serializer[dict[str, object]]):
    challenge = serializers.CharField(max_length=360)


class PreferenceSerializer(serializers.Serializer[dict[str, object]]):
    grant_id = serializers.UUIDField()
    channel = serializers.ChoiceField(choices=Channel.choices)
    purpose = serializers.CharField(max_length=32)
    allow = serializers.BooleanField()


class DocumentAcceptSerializer(serializers.Serializer[dict[str, object]]):
    issued_version_id = serializers.UUIDField()
    artifact_id = serializers.UUIDField()
    artifact_sha256 = serializers.RegexField(r"^[0-9a-f]{64}$")
    manifestation_text = serializers.CharField(max_length=2000)
    manifestation_version = serializers.CharField(max_length=32)
    idempotency_key = serializers.UUIDField()


class FormCreateSerializer(serializers.Serializer[dict[str, object]]):
    name = serializers.CharField(max_length=120)
    title = serializers.CharField(max_length=160)
    introduction = serializers.CharField(max_length=500, required=False, allow_blank=True)
    field_schema = serializers.JSONField()
    event_type_options = serializers.ListField(child=serializers.DictField())
    location_options = serializers.ListField(child=serializers.DictField())
    duration_options_minutes = serializers.ListField(child=serializers.IntegerField())
    timezone_name = serializers.CharField(max_length=64)
    responsible_membership_id = serializers.UUIDField()
    origin = serializers.CharField(max_length=24)
    origin_detail = serializers.CharField(max_length=160, required=False, allow_blank=True)
    attribution = serializers.JSONField(default=dict)
    consent_presentation = serializers.ListField(child=serializers.DictField(), default=list)
    portal_scopes = serializers.ListField(child=serializers.CharField(max_length=40))
    acknowledgement_template_version_id = serializers.UUIDField(required=False, allow_null=True)


class FormVersionCreateSerializer(serializers.Serializer[dict[str, object]]):
    title = serializers.CharField(max_length=160)
    introduction = serializers.CharField(max_length=500, required=False, allow_blank=True)
    field_schema = serializers.JSONField()
    event_type_options = serializers.ListField(child=serializers.DictField())
    location_options = serializers.ListField(child=serializers.DictField())
    duration_options_minutes = serializers.ListField(child=serializers.IntegerField())
    timezone_name = serializers.CharField(max_length=64)
    responsible_membership_id = serializers.UUIDField()
    origin = serializers.CharField(max_length=24)
    origin_detail = serializers.CharField(max_length=160, required=False, allow_blank=True)
    attribution = serializers.JSONField(default=dict)
    consent_presentation = serializers.ListField(child=serializers.DictField(), default=list)
    portal_scopes = serializers.ListField(child=serializers.CharField(max_length=40))
    acknowledgement_template_version_id = serializers.UUIDField(required=False, allow_null=True)


class GrantIssueSerializer(serializers.Serializer[dict[str, object]]):
    event_request_id = serializers.UUIDField()
    scopes = serializers.ListField(child=serializers.CharField(max_length=40))


class GrantRevokeSerializer(serializers.Serializer[dict[str, object]]):
    revision = serializers.IntegerField(min_value=1)


class WebhookLocatorSerializer(serializers.Serializer[dict[str, object]]):
    sender_identity_id = serializers.UUIDField()
