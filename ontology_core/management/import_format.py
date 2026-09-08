"""Canonical metadata import contract shared by parsers and template builders."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass

from ontology_core.errors import OntologyImportError

STANDARD_COLUMNS = (
    "对象英文名称",
    "对象中文名称",
    "对象描述",
    "状态",
    "属性英文名",
    "属性中文名",
    "属性类型",
    "属性描述",
    "是否主键",
    "是否标题",
)
HEADER_SCAN_LIMIT = 20


@dataclass(frozen=True)
class PreparedTabularText:
    """Canonical TSV plus the number of physical rows preceding its header."""

    text: str
    line_offset: int = 0


def prepare_tsv(text: str) -> PreparedTabularText:
    """Require the exact ten-column contract on the first TSV/TXT row."""
    rows = tuple(csv.reader(io.StringIO(text), delimiter="\t"))
    if not rows:
        raise OntologyImportError("元数据必须使用十列标准表头")
    _require_standard_header(rows[0])
    return PreparedTabularText(text=_rows_to_tsv(rows), line_offset=0)


def prepare_xlsx_rows(
    rows: Iterable[tuple[object, ...]],
    sheet_name: str,
) -> PreparedTabularText:
    """Locate one exact standard header in the first twenty physical rows."""
    materialized = tuple(tuple(row) for row in rows)
    matches = [
        index
        for index, row in enumerate(materialized[:HEADER_SCAN_LIMIT])
        if _normalized_row(row) == STANDARD_COLUMNS
    ]
    if not matches:
        raise OntologyImportError(f"{sheet_name} 前 20 行未找到十列标准表头")
    if len(matches) > 1:
        raise OntologyImportError(f"{sheet_name} 前 20 行存在多个十列标准表头")
    header_index = matches[0]
    _require_standard_header(materialized[header_index])
    return PreparedTabularText(
        text=_rows_to_tsv(materialized[header_index:]),
        line_offset=header_index,
    )


def _require_standard_header(row: Iterable[object]) -> None:
    if _normalized_row(row) != STANDARD_COLUMNS:
        raise OntologyImportError("元数据必须使用十列标准表头")


def _normalized_row(row: Iterable[object]) -> tuple[str, ...]:
    values = ["" if value is None else str(value).strip() for value in row]
    while values and not values[-1]:
        values.pop()
    return tuple(values)


def _rows_to_tsv(rows: Iterable[Iterable[object]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    for row in rows:
        writer.writerow("" if value is None else str(value) for value in row)
    return output.getvalue()
