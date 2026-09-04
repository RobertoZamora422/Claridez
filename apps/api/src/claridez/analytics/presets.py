"""Presets de presentación; nunca otorgan capabilities ni cambian contratos métricos."""

PRESETS = {
    "owner": (
        "request_created_count",
        "accepted_quote_amount",
        "confirmed_sale_amount",
        "confirmed_occupied_minutes",
        "pending_required_verification_count",
        "open_balance_amount",
        "operating_result_amount",
        "event_shortage_quantity",
    ),
    "administrator": (
        "request_created_count",
        "accepted_quote_amount",
        "confirmed_sale_amount",
        "confirmed_occupied_minutes",
        "pending_required_verification_count",
        "open_balance_amount",
        "operating_result_amount",
        "event_shortage_quantity",
    ),
    "commercial": (
        "request_created_count",
        "first_outbound_response_elapsed_seconds",
        "quote_issued_count",
        "accepted_quote_amount",
        "open_issued_quote_amount",
        "confirmed_reservation_count",
    ),
    "operations": (
        "confirmed_occupied_minutes",
        "confirmed_reservation_count",
        "pending_required_verification_count",
        "incident_opened_count",
        "execution_completed_count",
        "event_shortage_quantity",
    ),
    "finance": (
        "confirmed_sale_amount",
        "payment_received_amount",
        "application_net_amount",
        "open_balance_amount",
        "recognized_revenue_amount",
        "operating_result_amount",
        "net_cash_flow_amount",
    ),
}


def permitted_preset(profile: str, permitted_ids: set[str]) -> list[str]:
    return [value for value in PRESETS.get(profile, ()) if value in permitted_ids]
