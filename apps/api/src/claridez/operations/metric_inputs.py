"""Entradas cerradas de métricas operations, bajo autoridad de su fuente."""

from types import MappingProxyType

from claridez.organizations.analytics_contracts import SourceInputContract

INPUTS = MappingProxyType(
    {
        "operations.preparation_open_count": SourceInputContract(
            "S", "status responsible_membership_id", ""
        ),
        "operations.pending_required_verification_count": SourceInputContract(
            "S", "phase role_key", ""
        ),
        "operations.execution_completed_count": SourceInputContract("F", "time_bucket", ""),
        "operations.phase_duration_seconds": SourceInputContract("F", "time_bucket phase", "phase"),
        "operations.incident_opened_count": SourceInputContract(
            "F", "time_bucket incident_type severity", ""
        ),
        "operations.post_event_close_elapsed_seconds": SourceInputContract("F", "time_bucket", ""),
    }
)
