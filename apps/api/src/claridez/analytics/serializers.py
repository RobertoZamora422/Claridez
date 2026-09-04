"""Superficie cerrada: rechaza campos extra, timestamps naïve y contratos no publicados."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from django.utils import timezone
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from claridez.organizations.analytics_contracts import Coverage, MetricValueStatus, TemporalMode

from .models import ExportJob, ReportRevision
from .query import MAX_QUERY_METRICS, MetricSelection
from .registry import METRICS

COVERAGE_CHOICES = tuple((row.value, row.value) for row in Coverage)
VALUE_STATUS_CHOICES = tuple((row.value, row.value) for row in MetricValueStatus)
TEMPORAL_MODE_CHOICES = tuple((row.value, row.value) for row in TemporalMode)


class StrictSerializer(serializers.Serializer[dict[str, Any]]):
    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError("La solicitud contiene campos no permitidos.")
        return cast(dict[str, Any], super().to_internal_value(data))


class AwareDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, value: Any) -> datetime:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise serializers.ValidationError("Fecha no válida.") from error
            if parsed.utcoffset() is None:
                raise serializers.ValidationError("La fecha debe incluir offset.")
        elif not isinstance(value, datetime) or value.utcoffset() is None:
            raise serializers.ValidationError("La fecha debe incluir offset.")
        return super().to_internal_value(value)


class HistoryQuerySerializer(StrictSerializer):
    cursor = serializers.CharField(max_length=2048, required=False, default="", allow_blank=True)
    limit = serializers.IntegerField(min_value=1, max_value=50, default=50)


class MetricSelectionSerializer(StrictSerializer):
    metric_id = serializers.ChoiceField(choices=[row.metric_id for row in METRICS])
    metric_version = serializers.IntegerField(min_value=1, max_value=1, default=1)
    dimensions = serializers.ListField(
        child=serializers.CharField(max_length=64), max_length=10, default=list
    )
    filters = serializers.DictField(
        child=serializers.CharField(max_length=80, allow_blank=True), default=dict
    )
    period_start = AwareDateTimeField(required=False, allow_null=True, default=None)
    period_end = AwareDateTimeField(required=False, allow_null=True, default=None)
    as_of_at = AwareDateTimeField(required=False, allow_null=True, default=None)
    operational_period_id = serializers.UUIDField(required=False, allow_null=True, default=None)


def selections(data: list[dict[str, object]]) -> tuple[MetricSelection, ...]:
    return tuple(
        MetricSelection(
            str(row["metric_id"]),
            cast(int, row["metric_version"]),
            tuple(cast(list[str], row["dimensions"])),
            tuple(sorted(cast(dict[str, str], row["filters"]).items())),
            cast(datetime | None, row["period_start"]),
            cast(datetime | None, row["period_end"]),
            cast(datetime | None, row["as_of_at"]),
            cast(UUID | None, row["operational_period_id"]),
        )
        for row in data
    )


def validate_query(data: dict[str, Any]) -> dict[str, Any]:
    now = timezone.now()
    selected = selections(data["metrics"])
    if not 1 <= len(selected) <= MAX_QUERY_METRICS or len(
        {row.metric_id for row in selected}
    ) != len(selected):
        raise serializers.ValidationError("La selección de métricas no es válida.")
    try:
        for row in selected:
            row.source_query(
                timezone_name=data["timezone"], knowledge_cutoff_at=now, executed_at=now
            )
    except (ValueError, KeyError) as error:
        raise serializers.ValidationError(
            "El contrato métrico, sus filtros o tiempos no son válidos."
        ) from error
    return data


class QuerySerializer(StrictSerializer):
    timezone = serializers.CharField(max_length=64)
    metrics = MetricSelectionSerializer(many=True, allow_empty=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return validate_query(attrs)


class ReportCreateSerializer(QuerySerializer):
    title = serializers.CharField(max_length=120)
    visibility = serializers.ChoiceField(choices=ReportRevision.Visibility.choices)


class ReportReviseSerializer(ReportCreateSerializer):
    expected_revision = serializers.IntegerField(min_value=1)


class ReportArchiveSerializer(StrictSerializer):
    expected_revision = serializers.IntegerField(min_value=1)
    archived = serializers.BooleanField()


class ExecutionCreateSerializer(StrictSerializer):
    report_revision_id = serializers.UUIDField(required=False)
    timezone = serializers.CharField(max_length=64, required=False)
    metrics = MetricSelectionSerializer(many=True, required=False, allow_empty=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "report_revision_id" in attrs:
            if "metrics" in attrs or "timezone" in attrs:
                raise serializers.ValidationError("Una revisión no admite parámetros sustitutos.")
        elif "metrics" not in attrs or "timezone" not in attrs:
            raise serializers.ValidationError("Indique revisión o selección y zona.")
        else:
            validate_query(attrs)
        return attrs


class ExportCreateSerializer(StrictSerializer):
    execution_id = serializers.UUIDField()
    format = serializers.ChoiceField(choices=ExportJob.Format.choices)


@extend_schema_serializer(component_name="AnalyticsError")
class ErrorSerializer(serializers.Serializer[dict[str, object]]):
    error = serializers.JSONField()


class SourceMetricSerializer(serializers.Serializer[dict[str, object]]):
    source_metric_id = serializers.CharField()
    source_metric_version = serializers.IntegerField()


class MetricContractSerializer(serializers.Serializer[dict[str, object]]):
    metric_id = serializers.CharField()
    metric_version = serializers.IntegerField()
    owner = serializers.CharField()
    category = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]  # Campo declarativo DRF.
    source_metrics = SourceMetricSerializer(many=True)
    formula = serializers.CharField()
    grain = serializers.CharField()
    dimensions = serializers.ListField(child=serializers.CharField())
    required_dimensions = serializers.ListField(child=serializers.CharField())
    temporal_mode = serializers.ChoiceField(choices=TEMPORAL_MODE_CHOICES)
    unit = serializers.CharField()
    scale = serializers.IntegerField()
    required_capabilities = serializers.ListField(child=serializers.CharField())
    coverage_rule = serializers.CharField()


class AnalyticsPeriodSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    currency = serializers.CharField()
    closed = serializers.BooleanField()


class CatalogSerializer(serializers.Serializer[dict[str, object]]):
    catalog_version = serializers.CharField()
    catalog_hash = serializers.CharField()
    profile = serializers.CharField()
    capabilities = serializers.ListField(child=serializers.CharField())
    metrics = MetricContractSerializer(many=True)
    preset = serializers.ListField(child=serializers.CharField())
    server_now = serializers.DateTimeField()
    timezone = serializers.CharField()
    currency = serializers.CharField()
    periods = AnalyticsPeriodSerializer(many=True)


class MetricPointSerializer(serializers.Serializer[dict[str, object]]):
    dimensions = serializers.DictField(child=serializers.CharField())
    value = serializers.JSONField(allow_null=True)
    status = serializers.ChoiceField(choices=VALUE_STATUS_CHOICES)
    sample_size = serializers.IntegerField(allow_null=True)
    eligible_count = serializers.IntegerField(allow_null=True)


class MetricResultSerializer(serializers.Serializer[dict[str, object]]):
    metric_id = serializers.CharField()
    metric_version = serializers.IntegerField()
    unit = serializers.CharField()
    coverage = serializers.ChoiceField(choices=COVERAGE_CHOICES)
    coverage_from = serializers.DateTimeField(allow_null=True)
    coverage_reason = serializers.CharField(allow_null=True)
    provisional = serializers.BooleanField()
    exclusions = serializers.ListField(child=serializers.CharField())
    source_metrics = SourceMetricSerializer(many=True)
    provenance = serializers.JSONField()
    points = MetricPointSerializer(many=True)


class QueryResultSerializer(serializers.Serializer[dict[str, object]]):
    catalog_version = serializers.CharField()
    catalog_hash = serializers.CharField()
    timezone = serializers.CharField()
    knowledge_cutoff_at = serializers.DateTimeField()
    executed_at = serializers.DateTimeField()
    selection = MetricSelectionSerializer(many=True)
    metrics = MetricResultSerializer(many=True)


class ReportSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    revision_id = serializers.UUIDField()
    revision = serializers.IntegerField()
    title = serializers.CharField()
    visibility = serializers.ChoiceField(choices=ReportRevision.Visibility.choices)
    timezone = serializers.CharField()
    selection = MetricSelectionSerializer(many=True)
    owner_membership_id = serializers.UUIDField()
    archived = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    definition_sha256 = serializers.CharField()


class ExecutionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    report_revision_id = serializers.UUIDField(allow_null=True)
    executed_at = serializers.DateTimeField()
    knowledge_cutoff_at = serializers.DateTimeField()
    catalog_version = serializers.CharField()
    catalog_hash = serializers.CharField()
    result_sha256 = serializers.CharField()
    row_count = serializers.IntegerField()
    timezone = serializers.CharField()
    result = QueryResultSerializer(required=False)


class ExportJobSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    execution_id = serializers.UUIDField()
    format = serializers.ChoiceField(choices=ExportJob.Format.choices)
    state = serializers.ChoiceField(choices=ExportJob.State.choices)
    attempt_count = serializers.IntegerField()
    error_code = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    completed_at = serializers.DateTimeField(allow_null=True)
    next_attempt_at = serializers.DateTimeField(allow_null=True)


class ReportPageSerializer(serializers.Serializer[dict[str, object]]):
    results = ReportSerializer(many=True)
    next_cursor = serializers.CharField(allow_null=True)


class ExecutionPageSerializer(serializers.Serializer[dict[str, object]]):
    results = ExecutionSerializer(many=True)
    next_cursor = serializers.CharField(allow_null=True)


class ExportPageSerializer(serializers.Serializer[dict[str, object]]):
    results = ExportJobSerializer(many=True)
    next_cursor = serializers.CharField(allow_null=True)
