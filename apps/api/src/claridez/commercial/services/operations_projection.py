from __future__ import annotations

from typing import Any


def operational_event_projection(reservation: Any, *, include_phone: bool) -> dict[str, Any]:
    """Proyección pública mínima que operations puede consumir dentro del scope tenant."""
    version = reservation.quotation_version
    event = {
        "event_type_id": version.event_type_definition_snapshot_id,
        "event_type": version.event_type_snapshot,
        "venue": {"id": version.venue_snapshot_id, "name": version.venue_name_snapshot},
        "space": {"id": version.space_snapshot_id, "name": version.space_name_snapshot},
        "starts_at": version.event_starts_at_snapshot,
        "ends_at": version.event_ends_at_snapshot,
        "timezone": version.event_timezone_snapshot,
        "estimated_guests": version.estimated_guests_snapshot,
        "general_need": version.general_need_snapshot,
    }
    contact = {"display_name": version.person_name_snapshot}
    if include_phone:
        contact["phone_e164"] = reservation.event_request.person.phone_e164
    return {"event": event, "contact": contact, "reservation_status": reservation.status}
