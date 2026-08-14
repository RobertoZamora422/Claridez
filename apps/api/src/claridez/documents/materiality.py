from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

_MISSING = object()
_CONTRACTUAL_PATHS = (
    ("organization", "id"),
    ("organization", "name"),
    ("organization", "currency"),
    ("organization", "timezone_name"),
    ("counterparty", "id"),
    ("counterparty", "full_name"),
    ("counterparty", "phone"),
    ("counterparty", "email"),
    ("quotation",),
    ("reservation", "organization_id"),
    ("reservation", "event_request_id"),
    ("reservation", "root_reservation_id"),
    ("reservation", "current_reservation_id"),
    ("reservation", "quotation_version_id"),
    ("reservation", "venue_id"),
    ("reservation", "space_id"),
    ("reservation", "starts_at"),
    ("reservation", "ends_at"),
    ("reservation", "timezone_name"),
    ("reservation", "status"),
    ("reservation", "cancelled_at"),
)


def _path_value(snapshot: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = snapshot
    for component in path:
        if not isinstance(value, dict) or component not in value:
            return _MISSING
        value = value[component]
    return value


@dataclass(frozen=True, slots=True)
class MaterialityAssessment:
    policy_version: str
    status: str
    changes: tuple[str, ...]
    requires_new_issue: bool | None
    requires_new_acceptance: bool | None
    legal_instrument_outcome: None


class MaterialityPolicy(Protocol):
    def assess(
        self, previous_snapshot: dict[str, Any], current_snapshot: dict[str, Any]
    ) -> MaterialityAssessment: ...


class ExplicitReviewPolicy:
    version = "explicit-review-v1"

    def assess(
        self, previous_snapshot: dict[str, Any], current_snapshot: dict[str, Any]
    ) -> MaterialityAssessment:
        changes = tuple(
            ".".join(path)
            for path in _CONTRACTUAL_PATHS
            if _path_value(previous_snapshot, path) != _path_value(current_snapshot, path)
        )
        return MaterialityAssessment(
            policy_version=self.version,
            status="review_required" if changes else "unchanged",
            changes=changes,
            requires_new_issue=None if changes else False,
            requires_new_acceptance=None if changes else False,
            legal_instrument_outcome=None,
        )


def materiality_policy() -> MaterialityPolicy:
    return ExplicitReviewPolicy()
