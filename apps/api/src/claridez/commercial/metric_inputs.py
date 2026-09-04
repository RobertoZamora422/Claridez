"""Entradas cerradas de métricas commercial, bajo autoridad de su fuente."""

from types import MappingProxyType

from claridez.organizations.analytics_contracts import SourceInputContract

INPUTS = MappingProxyType(
    {
        "commercial.request_created_count": SourceInputContract(
            "F", "time_bucket origin responsible_membership_id", ""
        ),
        "commercial.closed_lost_request_count": SourceInputContract(
            "F", "time_bucket origin responsible_membership_id", ""
        ),
        "commercial.closed_lost_latest_issued_quote_amount": SourceInputContract(
            "F", "time_bucket currency origin event_type_id venue_id space_id", "currency"
        ),
        "commercial.quote_issued_count": SourceInputContract(
            "F", "time_bucket currency event_type_id venue_id space_id", ""
        ),
        "commercial.quote_accepted_count": SourceInputContract(
            "F", "time_bucket currency event_type_id venue_id space_id acceptance_channel", ""
        ),
        "commercial.accepted_quote_amount": SourceInputContract(
            "F",
            "time_bucket currency event_type_id venue_id space_id acceptance_channel",
            "currency",
        ),
        "commercial.open_issued_quote_amount": SourceInputContract(
            "S", "currency origin event_type_id venue_id space_id", "currency"
        ),
    }
)
