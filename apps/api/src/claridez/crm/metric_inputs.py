"""Entradas cerradas de métricas crm, bajo autoridad de su fuente."""

from types import MappingProxyType

from claridez.organizations.analytics_contracts import SourceInputContract

INPUTS = MappingProxyType(
    {
        "crm.first_outbound_response_elapsed_seconds": SourceInputContract(
            "C", "time_bucket origin channel", ""
        ),
        "crm.open_request_without_next_action_count": SourceInputContract(
            "S", "origin responsible_membership_id", ""
        ),
    }
)
