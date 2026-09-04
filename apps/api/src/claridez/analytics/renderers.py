"""Serialización tipada de resultados congelados; no consulta ni calcula métricas."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import platform
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .storage import MAX_ARTIFACT_BYTES

MAX_EXPORT_ROWS = 25000
MAX_EXPORT_COLUMNS = 32
MAX_CELL_CHARACTERS = 4000
CANONICAL_RENDERER = "claridez-analytics-weasyprint-69.0-debian12-v1"
type Cell = str | int | Decimal | bool | date | datetime | None
type ColumnType = Literal["text", "integer", "decimal", "boolean", "date", "datetime"]


@dataclass(frozen=True, slots=True)
class Column:
    key: str
    label: str
    kind: ColumnType


@dataclass(frozen=True, slots=True)
class ExportDataset:
    columns: tuple[Column, ...]
    rows: tuple[tuple[Cell, ...], ...]
    execution_id: str
    catalog_hash: str
    timezone_name: str
    knowledge_cutoff_at: str

    def validate(self) -> None:
        if not 1 <= len(self.columns) <= MAX_EXPORT_COLUMNS or len(self.rows) > MAX_EXPORT_ROWS:
            raise ValueError("export_row_or_column_limit")
        if len({column.key for column in self.columns}) != len(self.columns):
            raise ValueError("duplicate_export_columns")
        estimated_bytes = 0
        for column in self.columns:
            if (
                len(column.label) > MAX_CELL_CHARACTERS
                or len(column.key) > 80
                or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", column.label)
            ):
                raise ValueError("invalid_export_column")
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError("export_row_shape_mismatch")
            for column, value in zip(self.columns, row, strict=True):
                if value is None:
                    continue
                valid = {
                    "text": isinstance(value, str),
                    "integer": isinstance(value, int) and not isinstance(value, bool),
                    "decimal": isinstance(value, Decimal) and value.is_finite(),
                    "boolean": isinstance(value, bool),
                    "date": isinstance(value, date) and not isinstance(value, datetime),
                    "datetime": isinstance(value, datetime) and value.utcoffset() is not None,
                }
                if not valid[column.kind]:
                    raise ValueError("export_cell_type_mismatch")
                if len(_text(value)) > MAX_CELL_CHARACTERS:
                    raise ValueError("export_cell_size_limit")
                if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", _text(value)):
                    raise ValueError("export_cell_invalid_control_character")
                estimated_bytes += len(_text(value).encode("utf-8"))
                if estimated_bytes > MAX_ARTIFACT_BYTES:
                    raise ValueError("export_dataset_size_limit")


def _text(value: Cell) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _csv_text(value: Cell) -> str:
    text = _text(value)
    # Solo texto: los Decimal negativos permanecen numéricos.
    if isinstance(value, str) and (
        text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n"))
    ):
        return "'" + text
    return text


def _bounded(content: bytes) -> bytes:
    if len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError("export_size_limit")
    return content


def render_csv(dataset: ExportDataset) -> bytes:
    dataset.validate()
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow([_csv_text(column.label) for column in dataset.columns])
    for row in dataset.rows:
        writer.writerow([_csv_text(value) for value in row])
        if stream.tell() > MAX_ARTIFACT_BYTES:
            raise ValueError("export_size_limit")
    return _bounded(stream.getvalue().encode("utf-8-sig"))


def _column_letter(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _xlsx_cell(reference: str, value: Cell) -> str:
    if value is None:
        return f'<c r="{reference}"/>'
    if isinstance(value, bool):
        return f'<c r="{reference}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (Decimal, int)):
        # Excel no conserva más de 15 dígitos significativos. Se rechaza, nunca se redondea.
        normalized = Decimal(value).normalize()
        if len(normalized.as_tuple().digits) > 15:
            raise ValueError("xlsx_numeric_precision_limit_use_csv")
        return f'<c r="{reference}" t="n"><v>{_text(value)}</v></c>'
    if isinstance(value, date):
        return f'<c r="{reference}" t="d"><v>{value.isoformat()}</v></c>'
    # inlineStr no ejecuta texto como fórmulas, incluso si comienza por =,+,-,@.
    return (
        f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'
    )


def render_xlsx(dataset: ExportDataset) -> bytes:
    dataset.validate()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    rows = (tuple(column.label for column in dataset.columns), *dataset.rows)
    row_xml = []
    for number, row in enumerate(rows, 1):
        cells = "".join(
            _xlsx_cell(f"{_column_letter(index)}{number}", value)
            for index, value in enumerate(row, 1)
        )
        row_xml.append(f'<row r="{number}">{cells}</row>')
    sheet = f'<worksheet xmlns="{ns}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    metadata = {
        "execution_id": dataset.execution_id,
        "catalog_hash": dataset.catalog_hash,
        "timezone": dataset.timezone_name,
        "knowledge_cutoff_at": dataset.knowledge_cutoff_at,
        "column_types": ", ".join(f"{c.key}:{c.kind}" for c in dataset.columns),
    }
    meta_rows = "".join(
        f'<row r="{i}">{_xlsx_cell(f"A{i}", key)}{_xlsx_cell(f"B{i}", value)}</row>'
        for i, (key, value) in enumerate(metadata.items(), 1)
    )
    entries = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": f'<Relationships xmlns="{package_rel}"><Relationship Id="rId1" '
        f'Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>'
        '<sheet name="Resultados" sheetId="1" r:id="rId1"/>'
        '<sheet name="Procedencia" sheetId="2" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{package_rel}">'
        f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{rel}/worksheet" Target="worksheets/sheet2.xml"/>'
        "</Relationships>",
        "xl/worksheets/sheet1.xml": sheet,
        "xl/worksheets/sheet2.xml": (
            f'<worksheet xmlns="{ns}"><sheetData>{meta_rows}</sheetData></worksheet>'
        ),
    }
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path, xml in sorted(entries.items()):
            entry = ZipInfo(path, date_time=(2000, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml)
    return _bounded(output.getvalue())


def render_pdf(dataset: ExportDataset) -> bytes:
    dataset.validate()
    if len(dataset.rows) > 1000 or len(dataset.columns) > 8:
        raise ValueError("pdf_presentation_limit_use_tabular_export")
    if (
        os.environ.get("CLARIDEZ_ANALYTICS_RENDERER_ENVIRONMENT") != CANONICAL_RENDERER
        or platform.system() != "Linux"
    ):
        raise ValueError("pdf_requires_canonical_analytics_worker")
    # WeasyPrint es la biblioteca P9 existente y no publica stubs.
    from weasyprint import HTML  # type: ignore[import-untyped]

    def deny_external_fetch(url: str, **kwargs: object) -> dict[str, object]:
        raise ValueError("external_resource_fetch_forbidden")

    header = "".join(f'<th scope="col">{html.escape(c.label)}</th>' for c in dataset.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(_text(v))}</td>" for v in row) + "</tr>"
        for row in dataset.rows
    )
    source = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
    <title>Reporte de métricas Claridez</title><style>
    @page {{ size: A4 landscape; margin: 15mm; @bottom-right {{ content: counter(page); }} }}
    body {{ font-family: "DejaVu Sans", sans-serif; color: #0f172a; font-size: 10pt; }}
    h1 {{ font-size: 20pt; }} table {{ border-collapse: collapse; width: 100%; }}
    th,td {{ border-bottom: 1px solid #e2e8f0; padding: 7px;
             text-align: left; overflow-wrap: anywhere; }}
    thead {{ display: table-header-group; background: #f1f5f9; }} tr {{ break-inside: avoid; }}
    </style></head><body><h1>Reporte de métricas</h1>
    <p>Claridez · Ejecución {html.escape(dataset.execution_id)}</p>
    <p>Zona: {html.escape(dataset.timezone_name)} ·
    Conocimiento hasta: {html.escape(dataset.knowledge_cutoff_at)}</p>
    <p>Catálogo: {html.escape(dataset.catalog_hash)}</p>
    <table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></body></html>"""
    identity = hashlib.sha256(json.dumps(dataset.execution_id).encode()).hexdigest().encode("ascii")
    return _bounded(
        HTML(string=source, url_fetcher=deny_external_fetch).write_pdf(
            pdf_identifier=identity,
            pdf_tags=True,
        )
    )


def render(dataset: ExportDataset, format: str) -> bytes:
    if format == "csv":
        return render_csv(dataset)
    if format == "xlsx":
        return render_xlsx(dataset)
    if format == "pdf":
        return render_pdf(dataset)
    raise ValueError("export_format_not_supported")
