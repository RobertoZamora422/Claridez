"""Entradas cerradas de métricas scheduling, bajo autoridad de su fuente."""

from types import MappingProxyType

from claridez.organizations.analytics_contracts import SourceInputContract

INPUTS = MappingProxyType(
    {
        "scheduling.confirmed_event_minutes": SourceInputContract(
            "SI", "time_bucket venue_id space_id", ""
        ),
        "scheduling.confirmed_occupied_minutes": SourceInputContract(
            "SI", "time_bucket venue_id space_id", ""
        ),
        "scheduling.confirmed_reservation_count": SourceInputContract(
            "SI", "time_bucket venue_id space_id", ""
        ),
        "scheduling.blocked_minutes": SourceInputContract(
            "SI", "time_bucket venue_id space_id", "space_id"
        ),
        "scheduling.reservation_cancelled_count": SourceInputContract(
            "F", "time_bucket venue_id space_id", ""
        ),
        "scheduling.reservation_rescheduled_count": SourceInputContract(
            "F", "time_bucket from_venue_id from_space_id to_venue_id to_space_id", ""
        ),
    }
)
