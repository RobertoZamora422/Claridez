from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


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
        fields = (
            "quotation",
            "reservation",
            "organization",
            "counterparty",
        )
        changes = tuple(
            field for field in fields if previous_snapshot.get(field) != current_snapshot.get(field)
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
