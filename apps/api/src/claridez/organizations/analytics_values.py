"""Mecánica de agregación de DTO; no contiene fórmulas ni consultas de dominio."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from .analytics_contracts import (
    Coverage,
    DimensionValues,
    MetricPoint,
    MetricValueStatus,
    SourceMetricQuery,
    SourceMetricResult,
)


def time_bucket(instant: datetime, query: SourceMetricQuery) -> str:
    local = instant.astimezone(ZoneInfo(query.timezone_name))
    granularity = query.filter_value("time_bucket") or "month"
    if granularity == "day":
        return local.date().isoformat()
    if granularity == "week":
        year, week, _ = local.isocalendar()
        return f"{year}-W{week:02d}"
    if granularity != "month":
        raise ValueError("time_bucket debe ser day, week o month")
    return f"{local.year:04d}-{local.month:02d}"


def interval_slices(
    start: datetime,
    end: datetime,
    query: SourceMetricQuery,
) -> tuple[tuple[datetime, Decimal], ...]:
    """Intersecciones exactas en microsegundos UTC, antes del único redondeo final."""
    assert query.period_start is not None and query.period_end is not None
    lower = max(start.astimezone(UTC), query.period_start.astimezone(UTC))
    upper = min(end.astimezone(UTC), query.period_end.astimezone(UTC))
    values: list[tuple[datetime, Decimal]] = []
    zone = ZoneInfo(query.timezone_name)
    while lower < upper:
        next_boundary = upper
        if "time_bucket" in query.dimensions:
            local = lower.astimezone(zone)
            granularity = query.filter_value("time_bucket") or "month"
            if granularity == "day":
                next_date = local.date() + timedelta(days=1)
            elif granularity == "week":
                next_date = local.date() + timedelta(days=7 - local.weekday())
            elif granularity == "month":
                next_date = local.date().replace(day=28) + timedelta(days=4)
                next_date = next_date.replace(day=1)
            else:
                raise ValueError("time_bucket no soportado")
            next_boundary = min(
                upper, datetime.combine(next_date, datetime.min.time(), zone).astimezone(UTC)
            )
        delta = next_boundary - lower
        micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
        values.append((lower, Decimal(micros) / Decimal(1000000)))
        lower = next_boundary
    return tuple(values)


class MetricAccumulator:
    """Agrupa solo las dimensiones declaradas y jamás suma particiones implícitas."""

    def __init__(self, query: SourceMetricQuery, *, scale: int = 0, average: bool = False) -> None:
        self.query = query
        self.scale = scale
        self.average = average
        self.sums: dict[DimensionValues, Decimal] = defaultdict(Decimal)
        self.samples: dict[DimensionValues, int] = defaultdict(int)
        self.eligible: dict[DimensionValues, int] = defaultdict(int)
        self.observed: list[datetime] = []
        self.reasons: set[str] = set()

    def key(
        self,
        dimensions: Mapping[str, object],
        at: datetime | None = None,
    ) -> DimensionValues | None:
        values = {key: "" if val is None else str(val) for key, val in dimensions.items()}
        if "time_bucket" in self.query.dimensions:
            if at is None:
                self.reasons.add("missing_time_bucket_evidence")
                return None
            values["time_bucket"] = time_bucket(at, self.query)
        for name, expected in self.query.filters:
            if name == "time_bucket":
                continue
            if name not in values:
                self.reasons.add(f"missing_dimension:{name}")
                return None
            if values[name] != expected:
                return None
        if any(name not in values for name in self.query.dimensions):
            self.reasons.add("missing_dimension_evidence")
            return None
        return tuple(sorted((name, values[name]) for name in self.query.dimensions))

    def add(
        self,
        value: Decimal | int | None,
        dimensions: Mapping[str, object],
        *,
        at: datetime | None = None,
    ) -> None:
        key = self.key(dimensions, at)
        if key is None:
            return
        self.eligible[key] += 1
        if value is not None:
            self.sums[key] += value
            self.samples[key] += 1
        if at is not None:
            self.observed.append(at)

    def result(
        self,
        *,
        provenance: tuple[str, ...],
        watermark: str,
        coverage: Coverage = Coverage.COMPLETE,
        reason: str | None = None,
        coverage_from: datetime | None = None,
        exclusions: tuple[str, ...] = (),
        provisional: bool = False,
    ) -> SourceMetricResult:
        if reason:
            self.reasons.add(reason)
        keys = sorted(self.eligible)
        if self.reasons and coverage is Coverage.COMPLETE:
            coverage = Coverage.PARTIAL if any(self.samples.values()) else Coverage.UNAVAILABLE
        if not keys and not self.query.dimensions:
            keys = [()]
        points: list[MetricPoint] = []
        quantum = Decimal(1).scaleb(-self.scale)
        for key in keys:
            size = self.samples[key]
            if coverage is Coverage.UNAVAILABLE or (coverage is Coverage.PARTIAL and size == 0):
                value: Decimal | int | None = None
            elif self.average:
                value = (self.sums[key] / size).quantize(quantum, ROUND_HALF_UP) if size else None
            elif self.scale:
                value = self.sums[key].quantize(quantum, ROUND_HALF_UP)
            else:
                value = int(self.sums[key])
            points.append(
                MetricPoint(
                    key,
                    value,
                    status=MetricValueStatus.NOT_CALCULABLE
                    if value is None
                    else MetricValueStatus.VALUE,
                    sample_size=size if self.average else None,
                    eligible_count=self.eligible[key] if self.average else None,
                )
            )
        return SourceMetricResult(
            self.query.source_metric_id,
            self.query.source_metric_version,
            tuple(points),
            coverage,
            coverage_from,
            ";".join(sorted(self.reasons)) or None,
            provenance,
            watermark,
            exclusions=exclusions,
            provisional=provisional,
        )
