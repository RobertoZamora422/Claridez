from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.types.range import Range

from .errors import invalid


@dataclass(frozen=True, slots=True)
class LocalInterval:
    starts_at: datetime
    ends_at: datetime
    timezone_name: str


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise invalid("La zona horaria no es válida.") from None


def local_to_instant(value: datetime, timezone_name: str, *, field: str) -> datetime:
    if value.tzinfo is not None:
        raise invalid(f"{field} debe expresarse como hora local sin offset.")
    zone = _zone(timezone_name)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        round_trip = candidate.astimezone(zone).replace(tzinfo=None)
        if round_trip == value:
            candidates.add(candidate)
    if not candidates:
        raise invalid(
            f"{field} corresponde a una hora local inexistente.",
            code="nonexistent_local_time",
        )
    if len(candidates) > 1:
        raise invalid(
            f"{field} corresponde a una hora local ambigua.",
            code="ambiguous_local_time",
        )
    return next(iter(candidates))


def local_interval(
    starts_at_local: datetime,
    ends_at_local: datetime,
    timezone_name: str,
) -> LocalInterval:
    start = local_to_instant(starts_at_local, timezone_name, field="starts_at_local")
    end = local_to_instant(ends_at_local, timezone_name, field="ends_at_local")
    if start >= end:
        raise invalid("El inicio debe ser anterior al fin.")
    return LocalInterval(start, end, timezone_name)


def canonical_range(start: datetime, end: datetime) -> Range[datetime]:
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise invalid("El intervalo debe ser finito, aware, no vacío y con inicio anterior al fin.")
    return Range(start, end, bounds="[)")


def occupied_range(
    start: datetime,
    end: datetime,
    *,
    setup_minutes: int,
    teardown_minutes: int,
    buffer_before_minutes: int,
    buffer_after_minutes: int,
) -> Range[datetime]:
    values = (setup_minutes, teardown_minutes, buffer_before_minutes, buffer_after_minutes)
    if any(value < 0 for value in values):
        raise invalid("Las duraciones temporales no pueden ser negativas.")
    return canonical_range(
        start - timedelta(minutes=setup_minutes + buffer_before_minutes),
        end + timedelta(minutes=teardown_minutes + buffer_after_minutes),
    )


def calendar_bounds(view: str, anchor: date, timezone_name: str) -> tuple[datetime, datetime]:
    if view == "day":
        start_day, end_day = anchor, anchor + timedelta(days=1)
    elif view == "week":
        start_day = anchor - timedelta(days=anchor.weekday())
        end_day = start_day + timedelta(days=7)
    elif view == "month":
        start_day = anchor.replace(day=1)
        end_day = (start_day.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        raise invalid("La vista debe ser day, week o month.")
    try:
        start = local_to_instant(
            datetime.combine(start_day, time.min), timezone_name, field="inicio"
        )
        end = local_to_instant(datetime.combine(end_day, time.min), timezone_name, field="fin")
    except Exception as error:
        if getattr(error, "code", "") in {"ambiguous_local_time", "nonexistent_local_time"}:
            raise invalid(
                "El límite local del calendario no es válido.", code="invalid_calendar_boundary"
            ) from error
        raise
    return start, end
