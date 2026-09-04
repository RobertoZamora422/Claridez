from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

from claridez.analytics.renderers import Column, ExportDataset, render_csv, render_xlsx


def _dataset() -> ExportDataset:
    return ExportDataset(
        (
            Column("label", "Métrica", "text"),
            Column("value", "USD", "decimal"),
            Column("count", "Cantidad", "integer"),
            Column("flag", "Provisional", "boolean"),
            Column("at", "Corte", "datetime"),
        ),
        (
            (
                '=HYPERLINK("https://invalid.test")',
                Decimal("-12.34"),
                10,
                False,
                datetime(2026, 9, 4, tzinfo=UTC),
            ),
        ),
        "execution",
        "hash",
        "America/Guayaquil",
        "2026-09-04T00:00:00Z",
    )


def test_csv_formula_injection_is_type_aware() -> None:
    result = render_csv(_dataset()).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(result)))
    assert rows[1][0].startswith("'=HYPERLINK")
    assert rows[1][1] == "-12.34"
    assert rows[1][2] == "10"
    assert rows[1][3] == "false"


@pytest.mark.parametrize("value", ["=1+1", "+cmd", "-cmd", "@SUM(A1)", "  =1+1", "\t=1+1"])
def test_all_formula_prefixes_remain_literal_text(value: str) -> None:
    original = _dataset()
    dataset = replace(original, rows=((value, *original.rows[0][1:]),))
    assert "'" + value in render_csv(dataset).decode("utf-8-sig")
    with ZipFile(io.BytesIO(render_xlsx(dataset))) as archive:
        tree = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    assert tree.findall(".//x:f", ns) == []
    assert tree.find('.//x:c[@r="A2"]', ns).attrib["t"] == "inlineStr"  # type: ignore[union-attr]


def test_xlsx_types_metadata_and_bytes_are_deterministic() -> None:
    dataset = _dataset()
    first = render_xlsx(dataset)
    assert first == render_xlsx(dataset)
    with ZipFile(io.BytesIO(first)) as archive:
        tree = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert b"knowledge_cutoff_at" in archive.read("xl/worksheets/sheet2.xml")
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    types = {c.attrib["r"]: c.attrib.get("t") for c in tree.findall(".//x:c", ns)}
    assert types["B2"] == "n" and types["C2"] == "n"
    assert types["D2"] == "b" and types["E2"] == "d"


def test_xlsx_never_silently_rounds_high_precision_money() -> None:
    original = _dataset()
    dataset = replace(
        original, rows=(("total", Decimal("9999999999999999.99"), *original.rows[0][2:]),)
    )
    with pytest.raises(ValueError, match="precision"):
        render_xlsx(dataset)
    assert b"9999999999999999.99" in render_csv(dataset)


def test_row_limits_and_types_are_checked() -> None:
    with pytest.raises(ValueError, match="limit"):
        render_csv(replace(_dataset(), rows=_dataset().rows * 25001))
    with pytest.raises(ValueError, match="type_mismatch"):
        render_csv(
            replace(
                _dataset(), rows=(("total", "=1+1", 1, False, datetime(2026, 9, 4, tzinfo=UTC)),)
            )
        )
