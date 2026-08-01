from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

BASELINE_VERSION = "operations-5.2-v1"
BASELINE_NAMESPACE = UUID("6f4bc8cb-3f79-5ed8-a62d-d8d9d688ee53")


@dataclass(frozen=True, slots=True)
class BaselineItem:
    key: str
    section: str
    title: str
    days_before: int


BASELINE: tuple[BaselineItem, ...] = (
    BaselineItem("space_layout", "definitions", "Confirmar distribución del espacio", 7),
    BaselineItem("guest_count", "definitions", "Revisar número estimado de invitados", 7),
    BaselineItem("special_requirements", "definitions", "Confirmar requerimientos especiales", 7),
    BaselineItem("entry_schedule", "definitions", "Validar horario de ingreso", 7),
    BaselineItem("furniture", "setup", "Preparar mobiliario", 1),
    BaselineItem("decoration", "setup", "Verificar decoración", 1),
    BaselineItem(
        "final_readiness_review",
        "final_review",
        "Revisar que todo esté listo antes del evento",
        0,
    ),
)
BASELINE_KEYS = frozenset(item.key for item in BASELINE)


def baseline_item_id(reservation_id: UUID, key: str) -> UUID:
    return uuid5(BASELINE_NAMESPACE, f"{reservation_id}:{BASELINE_VERSION}:item:{key}")


def baseline_request_id(reservation_id: UUID, key: str) -> UUID:
    return uuid5(BASELINE_NAMESPACE, f"{reservation_id}:{BASELINE_VERSION}:request:{key}")


def transition_id(reservation_id: UUID, cause: str) -> UUID:
    return uuid5(BASELINE_NAMESPACE, f"{reservation_id}:{BASELINE_VERSION}:transition:{cause}")


def due_date(
    *, starts_at: datetime, timezone_name: str, confirmed_at: datetime, days_before: int
) -> date:
    event_day = starts_at.astimezone(ZoneInfo(timezone_name)).date()
    confirmation_day = confirmed_at.astimezone(ZoneInfo(timezone_name)).date()
    return max(confirmation_day, event_day - timedelta(days=days_before))
