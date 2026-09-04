"""Entradas cerradas de métricas receivables, bajo autoridad de su fuente."""

from types import MappingProxyType

from claridez.organizations.analytics_contracts import SourceInputContract

INPUTS = MappingProxyType(
    {
        "receivables.obligation_original_amount": SourceInputContract(
            "F", "time_bucket currency", "currency"
        ),
        "receivables.payment_received_amount": SourceInputContract(
            "F", "time_bucket currency method provenance", "currency"
        ),
        "receivables.payment_unapplied_amount": SourceInputContract(
            "C", "time_bucket currency method provenance", "currency"
        ),
        "receivables.application_net_amount": SourceInputContract(
            "F", "time_bucket currency effect_kind", "currency"
        ),
        "receivables.adjustment_net_amount": SourceInputContract(
            "F", "time_bucket currency direction", "currency"
        ),
        "receivables.movement_reversal_amount_by_target": SourceInputContract(
            "F", "time_bucket currency target_kind", "currency target_kind"
        ),
        "receivables.refund_recorded_amount": SourceInputContract(
            "F", "time_bucket currency", "currency"
        ),
        "receivables.open_balance_amount": SourceInputContract("S", "currency", "currency"),
        "receivables.aging_open_balance_amount": SourceInputContract(
            "S", "currency aging_bucket", "currency aging_bucket"
        ),
        "receivables.expected_collection_amount": SourceInputContract(
            "SI", "time_bucket currency", "currency"
        ),
    }
)
