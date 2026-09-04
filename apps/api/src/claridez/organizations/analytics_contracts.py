"""Contratos neutrales para los puertos batch source-owned de P15."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo


class Coverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class TemporalMode(StrEnum):
    FACT = "F"
    STATE = "S"
    STATE_IN_PERIOD = "SI"
    COHORT = "C"
    FINANCIAL_PERIOD = "FP"


class MetricValueStatus(StrEnum):
    VALUE = "value"
    NOT_APPLICABLE = "not_applicable"
    NOT_CALCULABLE = "not_calculable"


type Scalar = Decimal | int | str | bool | UUID | None
type DimensionValues = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class SourceMetricQuery:
    """Consulta ya validada por Analytics para una métrica fuente versionada."""

    source_metric_id: str
    source_metric_version: int
    mode: TemporalMode
    period_start: datetime | None
    period_end: datetime | None
    as_of_at: datetime | None
    knowledge_cutoff_at: datetime
    executed_at: datetime
    timezone_name: str
    dimensions: tuple[str, ...] = ()
    filters: tuple[tuple[str, str], ...] = ()
    operational_period_id: UUID | None = None

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone_name)
        for value in (
            self.period_start,
            self.period_end,
            self.as_of_at,
            self.knowledge_cutoff_at,
            self.executed_at,
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("las fechas deben incluir zona horaria")
        if not isinstance(self.mode, TemporalMode):
            raise ValueError("modo temporal no soportado")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("dimensiones duplicadas")
        if len(dict(self.filters)) != len(self.filters):
            raise ValueError("filtros duplicados")
        if (
            self.mode is not TemporalMode.FINANCIAL_PERIOD
            and self.operational_period_id is not None
        ):
            raise ValueError("operational_period_id solo aplica a FP")
        if self.source_metric_version != 1:
            raise ValueError("source_metric_version no soportada")
        if self.knowledge_cutoff_at > self.executed_at:
            raise ValueError("knowledge_cutoff_at no puede superar executed_at")
        if self.as_of_at is not None and self.as_of_at > self.knowledge_cutoff_at:
            raise ValueError("as_of_at no puede superar knowledge_cutoff_at")
        if self.mode is TemporalMode.FACT:
            if self.period_start is None or self.period_end is None or self.as_of_at is not None:
                raise ValueError("F exige periodo y rechaza as_of_at")
        elif self.mode is TemporalMode.STATE:
            if (
                self.as_of_at is None
                or self.period_start is not None
                or self.period_end is not None
            ):
                raise ValueError("S exige solo as_of_at")
        elif self.mode is TemporalMode.STATE_IN_PERIOD:
            if self.period_start is None or self.period_end is None or self.as_of_at is None:
                raise ValueError("SI exige periodo y as_of_at")
        elif self.mode is TemporalMode.COHORT:
            if self.period_start is None or self.period_end is None or self.as_of_at is None:
                raise ValueError("C exige periodo y as_of_at")
            if self.period_end > self.as_of_at:
                raise ValueError("period_end no puede superar as_of_at")
        elif (
            self.operational_period_id is None
            or self.as_of_at is None
            or self.period_start is not None
            or self.period_end is not None
        ):
            raise ValueError("FP exige operational_period_id y as_of_at")
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_start >= self.period_end
        ):
            raise ValueError("el periodo debe ser semiabierto y no vacío")

    def filter_value(self, name: str) -> str | None:
        return dict(self.filters).get(name)


@dataclass(frozen=True, slots=True)
class SourceInputContract:
    mode: str
    dimensions: str
    partitions: str = ""

    def validate(self, query: SourceMetricQuery) -> None:
        allowed = set(self.dimensions.split())
        if query.mode.value != self.mode:
            raise ValueError("el modo temporal no corresponde a la métrica fuente")
        if set(query.dimensions) - allowed or set(dict(query.filters)) - allowed:
            raise ValueError("dimensión o filtro no declarado por la fuente")
        if set(self.partitions.split()) - (set(query.dimensions) | set(dict(query.filters))):
            raise ValueError("falta una partición obligatoria de la fuente")


@dataclass(frozen=True, slots=True)
class MetricPoint:
    dimensions: DimensionValues
    value: Decimal | int | None
    status: MetricValueStatus = MetricValueStatus.VALUE
    eligible_count: int | None = None
    sample_size: int | None = None


@dataclass(frozen=True, slots=True)
class SourceMetricResult:
    source_metric_id: str
    source_metric_version: int
    points: tuple[MetricPoint, ...]
    coverage: Coverage
    coverage_from: datetime | None
    coverage_reason: str | None
    provenance: tuple[str, ...]
    watermark: str
    exclusions: tuple[str, ...] = ()
    provisional: bool = False
    authorization_scope_sha256: str | None = None

    @property
    def metric_id(self) -> str:
        """Identificador público conservado por las 51 fórmulas source-owned v1."""
        return self.source_metric_id.rsplit(".", 1)[-1]

    @property
    def unit(self) -> str:
        # Convención cerrada de nombres v1, contrastada con los 53 contratos del catálogo.
        for suffix, unit in (
            ("_seconds", "seconds"),
            ("_minutes", "minutes"),
            ("_quantity", "quantity"),
            ("_rate", "percentage_points"),
            ("_amount", "money"),
            ("_count", "count"),
        ):
            if self.metric_id.endswith(suffix):
                return unit
        if self.metric_id == "movement_reversal_amount_by_target":
            return "money"
        raise ValueError("source_metric_unit_not_defined")

    def __post_init__(self) -> None:
        if self.coverage is Coverage.PARTIAL and not self.coverage_reason:
            raise ValueError("partial exige motivo")
        if self.coverage is Coverage.UNAVAILABLE and not self.coverage_reason:
            raise ValueError("unavailable exige motivo")
        if self.coverage is Coverage.UNAVAILABLE and any(p.value is not None for p in self.points):
            raise ValueError("unavailable no admite valores estimados")


@dataclass(frozen=True, slots=True)
class CohortMember:
    subject_id: UUID
    related_id: UUID | None
    occurred_at: datetime
    dimensions: DimensionValues


@dataclass(frozen=True, slots=True)
class CanonicalCluster:
    person_id: UUID
    canonical_person_id: UUID
    source_revision: int | None
    merge_recorded_at: datetime | None


@dataclass(frozen=True, slots=True)
class SourceStateMember:
    subject_id: UUID
    status: str
    dimensions: DimensionValues
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class SourceCollection[T]:
    source_metric_id: str
    source_metric_version: int
    items: tuple[T, ...]
    coverage: Coverage
    coverage_from: datetime | None
    coverage_reason: str | None
    provenance: tuple[str, ...]
    watermark: str


def dimension_values(**values: object) -> DimensionValues:
    return tuple(sorted((key, str(value)) for key, value in values.items() if value is not None))


def worst_coverage(*values: Coverage) -> Coverage:
    rank = {Coverage.COMPLETE: 0, Coverage.PARTIAL: 1, Coverage.UNAVAILABLE: 2}
    return max(values, key=rank.__getitem__, default=Coverage.COMPLETE)


def evidence_watermark(references: tuple[str, ...]) -> str:
    """Huella del conjunto materializado de revisiones, independiente del orden SQL."""
    canonical = json.dumps(sorted(references), separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
