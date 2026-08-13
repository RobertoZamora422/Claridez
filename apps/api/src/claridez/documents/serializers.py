from __future__ import annotations

from datetime import datetime

from rest_framework import serializers

from .acceptance import MANIFESTATION_VERSION
from .models import ContractualInstrument, ExternalAccessGrant


class DocumentDomainErrorSerializer(serializers.Serializer[dict[str, object]]):
    error = serializers.DictField()


class VariableSchemaSerializer(serializers.Serializer[dict[str, object]]):
    version = serializers.CharField()
    variables = serializers.ListField(child=serializers.DictField())


class TemplateWriteSerializer(serializers.Serializer[dict[str, object]]):
    name = serializers.CharField(max_length=160)
    title = serializers.CharField(max_length=200)
    body_html = serializers.CharField(max_length=200_000)
    variable_schema = VariableSchemaSerializer()


class TemplateVersionWriteSerializer(serializers.Serializer[dict[str, object]]):
    title = serializers.CharField(max_length=200)
    body_html = serializers.CharField(max_length=200_000)
    variable_schema = VariableSchemaSerializer()


class TemplateActiveSerializer(serializers.Serializer[dict[str, object]]):
    active = serializers.BooleanField()


class PreviewSerializer(serializers.Serializer[dict[str, object]]):
    root_reservation_id = serializers.UUIDField()
    template_version_id = serializers.UUIDField()


class RecordCreateSerializer(serializers.Serializer[dict[str, object]]):
    root_reservation_id = serializers.UUIDField()


class InstrumentCreateSerializer(serializers.Serializer[dict[str, object]]):
    instrument_type = serializers.ChoiceField(choices=ContractualInstrument.Type.choices)
    title = serializers.CharField(max_length=200)


class IssueSerializer(serializers.Serializer[dict[str, object]]):
    template_version_id = serializers.UUIDField()


class ExternalUploadSerializer(serializers.Serializer[dict[str, object]]):
    record_id = serializers.UUIDField()
    file = serializers.FileField()


class GrantCreateSerializer(serializers.Serializer[dict[str, object]]):
    issued_version_id = serializers.UUIDField()
    purpose = serializers.ChoiceField(choices=ExternalAccessGrant.Purpose.choices)
    expires_at = serializers.DateTimeField()
    max_exchanges = serializers.IntegerField(min_value=1, max_value=20, default=1)

    def validate_expires_at(self, value: datetime) -> datetime:
        from django.utils import timezone

        if value <= timezone.now():
            raise serializers.ValidationError("Debe ser una fecha futura.")
        return value


class RetentionPolicyCreateSerializer(serializers.Serializer[dict[str, object]]):
    key = serializers.RegexField(r"^[a-z][a-z0-9_]{1,79}$")
    version = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=160)
    classification = serializers.CharField(max_length=80)
    rules = serializers.JSONField()


class RetentionAssignmentCreateSerializer(serializers.Serializer[dict[str, object]]):
    policy_id = serializers.UUIDField()
    target_type = serializers.ChoiceField(
        choices=("contractual_record", "issued_version", "generated_artifact", "external_file")
    )
    target_id = serializers.UUIDField()


class RetentionEligibilitySerializer(serializers.Serializer[dict[str, object]]):
    eligible_at = serializers.DateTimeField()
    rationale = serializers.CharField(min_length=3, max_length=500)


class LegalHoldCreateSerializer(serializers.Serializer[dict[str, object]]):
    assignment_id = serializers.UUIDField()
    reason = serializers.CharField(min_length=3, max_length=500)


class LegalHoldReleaseSerializer(serializers.Serializer[dict[str, object]]):
    reason = serializers.CharField(min_length=3, max_length=500)


class GrantExchangeSerializer(serializers.Serializer[dict[str, object]]):
    token = serializers.CharField(min_length=48, max_length=256, trim_whitespace=False)


class AcceptanceSerializer(serializers.Serializer[dict[str, object]]):
    challenge_token = serializers.CharField(min_length=48, max_length=256, trim_whitespace=False)
    manifestation_version = serializers.ChoiceField(choices=(MANIFESTATION_VERSION,))
    affirmative = serializers.BooleanField()
    asserted_name = serializers.CharField(min_length=2, max_length=200)
    timezone = serializers.CharField(max_length=64, default="America/Guayaquil")


class GenericDocumentResponseSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField(required=False)
    status = serializers.CharField(required=False)


class DocumentCapabilitiesResponseSerializer(serializers.Serializer[dict[str, object]]):
    capabilities = serializers.ListField(child=serializers.CharField())
