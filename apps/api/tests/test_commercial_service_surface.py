from __future__ import annotations

from inspect import signature

from claridez.commercial import services

EXPECTED_PARAMETERS = {
    "accept_quotation_version": (
        "actor",
        "organization_reference",
        "quotation_id",
        "version",
        "channel",
        "note",
    ),
    "cancel_reservation": ("actor", "organization_reference", "reservation_id", "reason"),
    "close_event_request": ("actor", "organization_reference", "request_id", "reason"),
    "commercial_capabilities": ("actor", "organization_reference"),
    "confirm_reservation": (
        "actor",
        "organization_reference",
        "reservation_id",
        "kind",
        "recognized_amount",
        "reported_at",
        "reference",
        "waiver_reason",
    ),
    "create_event_request": (
        "actor",
        "organization_reference",
        "person_id",
        "event_type_id",
        "space_id",
        "starts_at",
        "ends_at",
        "estimated_guests",
        "general_need",
        "notes",
        "origin",
        "origin_detail",
        "responsible_membership_id",
    ),
    "create_person": (
        "actor",
        "organization_reference",
        "full_name",
        "phone",
        "email",
        "origin",
        "origin_detail",
    ),
    "create_quotation": ("actor", "organization_reference", "request_id", "valid_until"),
    "create_quotation_version": (
        "actor",
        "organization_reference",
        "quotation_id",
        "valid_until",
    ),
    "issue_quotation_version": ("actor", "organization_reference", "quotation_id", "version"),
    "list_availability": (
        "actor",
        "organization_reference",
        "space_id",
        "starts_at",
        "ends_at",
    ),
    "list_event_requests": ("actor", "organization_reference", "status"),
    "list_people": ("actor", "organization_reference", "query"),
    "list_person_revisions": ("actor", "organization_reference", "person_id"),
    "read_event_request": ("actor", "organization_reference", "request_id"),
    "read_person": ("actor", "organization_reference", "person_id"),
    "read_quotation": ("actor", "organization_reference", "quotation_id"),
    "read_reservation": ("actor", "organization_reference", "reservation_id"),
    "replace_quotation_draft": (
        "actor",
        "organization_reference",
        "quotation_id",
        "version",
        "revision",
        "valid_until",
        "notes",
        "lines",
    ),
    "update_event_request": (
        "actor",
        "organization_reference",
        "request_id",
        "revision",
        "changes",
    ),
    "update_person": (
        "actor",
        "organization_reference",
        "person_id",
        "revision",
        "changes",
    ),
}


def test_public_commercial_service_surface_remains_stable() -> None:
    assert services.__all__ == tuple(EXPECTED_PARAMETERS)
    for name, expected_parameters in EXPECTED_PARAMETERS.items():
        public_function = getattr(services, name)
        assert callable(public_function)
        assert tuple(signature(public_function).parameters) == expected_parameters
