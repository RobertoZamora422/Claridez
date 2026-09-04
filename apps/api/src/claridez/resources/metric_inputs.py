"""Contrato de entradas resource/unit, sin agregación entre unidades incompatibles."""

from types import MappingProxyType

from claridez.organizations.analytics_contracts import SourceInputContract

INPUTS = MappingProxyType(
    {
        "resources.stock_on_hand_quantity": SourceInputContract(
            "S", "resource_id unit_id location_id", "resource_id unit_id"
        ),
        "resources.stock_movement_quantity": SourceInputContract(
            "F",
            "resource_id unit_id time_bucket location_id kind direction",
            "resource_id unit_id direction",
        ),
        "resources.event_required_quantity": SourceInputContract(
            "SI", "resource_id unit_id root_reservation_id temporal_source", "resource_id unit_id"
        ),
        "resources.event_allocated_quantity": SourceInputContract(
            "SI",
            "resource_id unit_id root_reservation_id source_location_id assignment_status",
            "resource_id unit_id",
        ),
        "resources.event_shortage_quantity": SourceInputContract(
            "SI", "resource_id unit_id root_reservation_id temporal_source", "resource_id unit_id"
        ),
        "resources.resource_unavailability_quantity": SourceInputContract(
            "S", "resource_id unit_id location_id", "resource_id unit_id"
        ),
    }
)
