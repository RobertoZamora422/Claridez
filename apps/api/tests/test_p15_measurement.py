from __future__ import annotations

import math

import pytest

from tests.p15_dataset import REPRESENTATIVE, SMOKE, DatasetProfile
from tests.p15_measurement import Sample, _safe_plan, assert_budget, summarize


def test_profile_has_fixed_source_volumes_not_random_counts() -> None:
    assert REPRESENTATIVE.expected["requests"] == 2400
    assert REPRESENTATIVE.expected["people"] == 240
    assert REPRESENTATIVE.expected["confirmed_roots"] == 300
    assert REPRESENTATIVE.expected["execution_completed"] == 150
    assert REPRESENTATIVE.expected["stock_movements"] == 792
    assert SMOKE.expected["confirmed_roots"] == 2
    with pytest.raises(ValueError):
        DatasetProfile("invalid", 15, 2, 2)


def test_p95_uses_nearest_rank_and_does_not_drop_the_slowest_client() -> None:
    rows = tuple(Sample(float(index), index % 10, index) for index in range(1, 201))
    assert summarize(rows) == {
        "samples": 200,
        "p95_ms": 190.0,
        "max_ms": 200.0,
        "qmax": 9,
        "payload_max_bytes": 200,
    }
    with pytest.raises(AssertionError, match="p95"):
        assert_budget("dashboard", (Sample(500, 1, 1),))
    with pytest.raises(AssertionError, match="qmax"):
        assert_budget("dashboard", (Sample(1, 111, 1),))
    with pytest.raises(AssertionError, match="payload"):
        assert_budget("dashboard", (Sample(1, 1, 512 * 1024 + 1),))


@pytest.mark.parametrize("samples", [(), (Sample(math.nan, 1, 1),), (Sample(-1, 1, 1),)])
def test_missing_or_invalid_evidence_cannot_pass(samples: tuple[Sample, ...]) -> None:
    with pytest.raises(ValueError):
        summarize(samples)


def test_explain_evidence_keeps_cost_rows_buffers_not_sensitive_sql_literals() -> None:
    plan = _safe_plan(
        {
            "Node Type": "Seq Scan",
            "Relation Name": "people_person",
            "Actual Rows": 12,
            "Filter": "phone = 'sensitive'",
            "Output": ["full_name"],
            "Index Cond": "secret",
            "Shared Hit Blocks": 3,
            "Plans": [{"Node Type": "Index Scan", "Filter": "private"}],
        }
    )
    assert "sensitive" not in str(plan) and "secret" not in str(plan) and "private" not in str(plan)
    assert plan["Actual Rows"] == 12 and plan["Shared Hit Blocks"] == 3
