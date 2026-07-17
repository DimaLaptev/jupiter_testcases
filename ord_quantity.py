"""Чтение поручений из Ord_Quantity (лист СВОД_операций)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.excel_grid import cell_at, read_workbook_sheets

from assemble.instruction_types import (
    direction_for,
    is_tracked_instruction,
    normalize_instruction_type,
)
from date_format import format_date_ddmmyyyy, parse_date
from models import ORD_COL_ALIASES, ORD_SHEET_NAME, OrdOpRow


def _norm_header(value: object | None) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip().casefold()


def _find_sheet(
    sheets: list[tuple[str, list[list[str]]]],
) -> tuple[str, list[list[str]]] | None:
    for name, rows in sheets:
        if _norm_header(name) == _norm_header(ORD_SHEET_NAME):
            return name, rows
    # fallback: первый лист с колонкой «Тип поручения»
    for name, rows in sheets:
        for r in range(min(5, len(rows))):
            for cell in rows[r]:
                if _norm_header(cell) == "тип поручения":
                    return name, rows
    return None


def _find_header_map(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    scan_limit = min(len(rows), 20)
    for r in range(1, scan_limit + 1):
        headers_by_col: dict[str, int] = {}
        row = rows[r - 1] if r - 1 < len(rows) else []
        for c, raw in enumerate(row, start=1):
            h = _norm_header(raw)
            if h:
                headers_by_col[h] = c
        field_map: dict[str, int] = {}
        for field, aliases in ORD_COL_ALIASES.items():
            for alias in aliases:
                col = headers_by_col.get(_norm_header(alias))
                if col:
                    field_map[field] = col
                    break
        if "instruction_type" in field_map and "ngri" in field_map:
            return r, field_map
    return None


def _cell(rows: list[list[str]], r: int, col: int | None) -> str:
    if not col:
        return ""
    return (cell_at(rows, r, col) or "").strip()


def iter_ord_op_rows(
    path: Path,
    *,
    warn: TextIO | None = None,
) -> list[OrdOpRow]:
    """Строки Ord с отслеживаемыми типами поручений."""
    out: TextIO = warn or sys.stdout
    if not path.is_file():
        print(f"WARN: Ord_Quantity не найден: {path}", file=out)
        return []

    sheets = read_workbook_sheets(path)
    found_sheet = _find_sheet(sheets)
    if not found_sheet:
        print(f"WARN: лист {ORD_SHEET_NAME!r} не найден в {path.name}", file=out)
        return []
    sheet_name, rows = found_sheet
    found = _find_header_map(rows)
    if not found:
        print(f"WARN: нет шапки Ord на листе {sheet_name!r}", file=out)
        return []
    header_row, fmap = found
    result: list[OrdOpRow] = []
    for r in range(header_row + 1, len(rows) + 1):
        raw_type = _cell(rows, r, fmap.get("instruction_type"))
        inst = normalize_instruction_type(raw_type)
        if not is_tracked_instruction(inst):
            continue
        ngri = _cell(rows, r, fmap.get("ngri"))
        if not ngri:
            continue
        date_raw = _cell(rows, r, fmap.get("op_date"))
        op_type = _cell(rows, r, fmap.get("op_type")) or None
        result.append(
            OrdOpRow(
                ngri=ngri,
                schet_depo=_cell(rows, r, fmap.get("schet_depo")),
                razdel_scheta=_cell(rows, r, fmap.get("razdel_scheta")),
                instruction_type=inst or "",
                op_date=parse_date(date_raw),
                op_date_raw=format_date_ddmmyyyy(date_raw) or (date_raw or None),
                op_type=op_type,
                direction=direction_for(inst, op_type=op_type),
            ),
        )
    return result
