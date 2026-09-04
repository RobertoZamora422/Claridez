"""Contratos públicos de entrada bajo autoridad Finance, P15 v1."""

from types import MappingProxyType

from claridez.organizations.public import SourceInputContract

INPUTS = MappingProxyType(
    {
        "finance.confirmed_sale_count": SourceInputContract("F", "time_bucket currency venue_id"),
        "finance.confirmed_sale_amount": SourceInputContract(
            "F", "time_bucket currency venue_id", "currency"
        ),
        "finance.baseline_direct_cost_amount": SourceInputContract(
            "S", "currency root_reservation_id category_id", "currency root_reservation_id"
        ),
        "finance.recognized_revenue_amount": SourceInputContract(
            "FP", "currency venue_id root_reservation_id", "currency"
        ),
        "finance.actual_direct_cost_amount": SourceInputContract(
            "FP", "currency venue_id root_reservation_id category_id", "currency"
        ),
        "finance.variable_expense_amount": SourceInputContract(
            "FP", "currency venue_id root_reservation_id category_id", "currency"
        ),
        "finance.recurring_expense_amount": SourceInputContract(
            "FP", "currency venue_id category_id", "currency"
        ),
        "finance.cash_inflow_amount": SourceInputContract(
            "FP", "currency venue_id root_reservation_id source_kind", "currency"
        ),
        "finance.cash_outflow_amount": SourceInputContract(
            "FP", "currency venue_id root_reservation_id source_kind", "currency"
        ),
        "finance.net_cash_flow_amount": SourceInputContract(
            "FP", "currency venue_id root_reservation_id", "currency"
        ),
        "finance.gross_margin_amount": SourceInputContract(
            "FP", "currency venue_id root_reservation_id", "currency"
        ),
        "finance.contribution_margin_amount": SourceInputContract(
            "FP", "currency venue_id root_reservation_id", "currency"
        ),
        "finance.operating_result_amount": SourceInputContract(
            "FP", "currency venue_id root_reservation_id", "currency"
        ),
        "finance.profitability_rate": SourceInputContract(
            "FP", "currency venue_id root_reservation_id", "currency"
        ),
    }
)
