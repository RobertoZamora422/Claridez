from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest

from claridez.analytics import exporting
from claridez.analytics.exporting import (
    export_dataset,
    freeze_payload,
    presentation_dataset,
    reconstruct_execution,
)
from claridez.analytics.models import ReportExecution
from claridez.analytics.query import MetricOutput, MetricSelection, QueryOutput, output_payload
from claridez.analytics.registry import CATALOG_HASH
from claridez.analytics.services import payload_hash
from claridez.analytics.storage import StorageIntegrityError
from claridez.organizations.analytics_contracts import Coverage, MetricPoint, SourceMetricResult
from claridez.organizations.capabilities import Capability
from claridez.organizations.exceptions import AuthorizationDenied
from claridez.organizations.models import Membership
from claridez.organizations.tenant_scope import TenantAuthorization

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def execution(*, closed: bool = False) -> tuple[ReportExecution, QueryOutput]:
    metric_id = "recognized_revenue_amount" if closed else "open_balance_amount"
    selected = MetricSelection(
        metric_id,
        dimensions=("currency",),
        as_of_at=NOW,
        operational_period_id=uuid4() if closed else None,
    )
    source = SourceMetricResult(
        f"{'finance' if closed else 'receivables'}.{metric_id}",
        1,
        (MetricPoint((("currency", "USD"),), Decimal("25.00")),),
        Coverage.COMPLETE,
        None,
        None,
        ("ledger@1",),
        "revision:1",
    )
    output = QueryOutput(
        (selected,),
        "America/Guayaquil",
        NOW,
        NOW,
        (MetricOutput(metric_id, 1, "money", source),),
    )
    payload = output_payload(output)
    row = ReportExecution(
        id=uuid4(),
        organization_id=uuid4(),
        catalog_sha256=CATALOG_HASH,
        selection=payload["selection"],
        timezone_name=output.timezone_name,
        knowledge_cutoff_at=NOW,
        executed_at=NOW,
        result_snapshot=freeze_payload(payload),
        result_sha256=payload_hash(payload),
    )
    return row, output


def auth() -> TenantAuthorization:
    return TenantAuthorization(
        uuid4(), uuid4(), uuid4(), Membership.Role.OWNER, Capability.ANALYTICS_CREATE_EXPORT
    )


def test_immutable_finance_close_is_requeried_without_duplicating_its_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, output = execution(closed=True)
    assert "points" not in row.result_snapshot["metrics"][0]
    observed: list[datetime] = []

    def replay(*args: object, **kwargs: object) -> QueryOutput:
        observed.append(cast(datetime, kwargs["knowledge_cutoff_at"]))
        return output

    monkeypatch.setattr(exporting, "_execute_frozen", replay)
    result = reconstruct_execution(auth(), row, Capability.ANALYTICS_CREATE_EXPORT)
    assert observed == [NOW]
    assert result == output_payload(output)
    dataset = export_dataset(str(row.pk), result)
    assert dataset.rows[0][3] == Decimal("25.00")


def test_divergent_requery_is_terminal_integrity_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    row, output = execution(closed=True)
    row.result_sha256 = "0" * 64
    monkeypatch.setattr(exporting, "_execute_frozen", lambda *args, **kwargs: output)
    with pytest.raises(StorageIntegrityError, match="execution_result_integrity_failure"):
        reconstruct_execution(auth(), row, Capability.ANALYTICS_CREATE_EXPORT)


def test_mutable_visibility_ledger_is_frozen_against_late_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, output = execution()
    assert row.result_snapshot["metrics"][0]["materialization"] == "execution_snapshot"

    def unexpected_requery(*_args: object, **_kwargs: object) -> QueryOutput:
        raise AssertionError("un commit tardío no debe reconsultarse para cambiar esta ejecución")

    monkeypatch.setattr(exporting, "_execute_frozen", unexpected_requery)
    assert reconstruct_execution(auth(), row, Capability.ANALYTICS_CREATE_EXPORT) == output_payload(
        output
    )


@pytest.mark.parametrize("original_scope", [None, "previous-context"])
def test_frozen_schedule_cannot_bypass_a_changed_or_narrowed_access_scope(
    monkeypatch: pytest.MonkeyPatch,
    original_scope: str | None,
) -> None:
    row = ReportExecution(
        result_snapshot={
            "metrics": [
                {
                    "metric_id": "confirmed_reservation_count",
                    "metric_version": 1,
                    "provenance": {"authorization_scope_sha256": original_scope},
                }
            ]
        }
    )
    monkeypatch.setattr(exporting, "analytics_scope_fingerprint", lambda _: "current-context")
    with pytest.raises(AuthorizationDenied, match="ámbito de agenda cambió"):
        exporting.revalidate_execution_scope(auth(), row)


def test_unchanged_schedule_scope_can_download_frozen_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = ReportExecution(
        result_snapshot={
            "metrics": [
                {
                    "metric_id": "confirmed_reservation_count",
                    "metric_version": 1,
                    "provenance": {"authorization_scope_sha256": "current-context"},
                }
            ]
        }
    )
    monkeypatch.setattr(exporting, "analytics_scope_fingerprint", lambda _: "current-context")
    exporting.revalidate_execution_scope(auth(), row)


def test_currency_filtered_out_of_grouping_is_still_exported_without_fx() -> None:
    row, original = execution()
    output = replace(
        original,
        selections=(
            replace(original.selections[0], dimensions=(), filters=(("currency", "USD"),)),
        ),
        metrics=(
            replace(
                original.metrics[0],
                result=replace(
                    original.metrics[0].result, points=(MetricPoint((), Decimal("25.00")),)
                ),
            ),
        ),
    )
    payload = output_payload(output)
    tabular = export_dataset(str(row.pk), payload)
    values = dict(zip((column.key for column in tabular.columns), tabular.rows[0], strict=True))
    assert values["currency"] == "USD"
    assert values["value"] == Decimal("25.00")
    assert "currency: USD" in str(presentation_dataset(str(row.pk), payload).rows[0][1])


def test_snapshot_only_contains_non_reconstructible_family_and_is_immutable_copy() -> None:
    row, output = execution()
    payload = output_payload(output)
    original = deepcopy(payload)
    metrics = cast(list[dict[str, object]], payload["metrics"])
    metrics[0]["metric_id"] = "accepted_quote_amount"
    frozen = freeze_payload(payload)
    assert frozen["metrics"] != original["metrics"]
    assert (
        cast(list[dict[str, object]], frozen["metrics"])[0]["materialization"]
        == "execution_snapshot"
    )
    assert "points" in cast(list[dict[str, object]], frozen["metrics"])[0]
    assert "materialization" not in cast(list[dict[str, object]], payload["metrics"])[0]
