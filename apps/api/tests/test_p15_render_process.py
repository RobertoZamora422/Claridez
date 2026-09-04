from __future__ import annotations

import multiprocessing

import pytest

from claridez.analytics.render_process import render_bounded
from claridez.analytics.renderers import render_csv, render_xlsx
from tests.test_p15_renderers import _dataset


@pytest.mark.parametrize("format_name", ["csv", "xlsx"])
def test_isolated_renderer_matches_exact_in_process_bytes(format_name: str) -> None:
    dataset = _dataset()
    expected = (render_csv if format_name == "csv" else render_xlsx)(dataset)
    assert render_bounded(dataset, format_name, timeout_seconds=15) == expected


def test_renderer_timeout_reaps_child_without_published_bytes() -> None:
    before = {row.pid for row in multiprocessing.active_children()}
    with pytest.raises(ValueError, match="export_time_limit"):
        render_bounded(_dataset(), "csv", timeout_seconds=0.000001)
    assert {row.pid for row in multiprocessing.active_children()} == before


def test_renderer_invalid_format_is_a_terminal_contract_error() -> None:
    with pytest.raises(ValueError, match="contract_or_limit"):
        render_bounded(_dataset(), "html", timeout_seconds=15)
