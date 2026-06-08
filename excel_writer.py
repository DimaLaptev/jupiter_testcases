"""Запись SQL-результатов на лист Excel (CopyFromRecordset)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Sequence

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

HEADER_ROW = 5
DATA_ROW_START = 6
CLEAR_MAX_COL = 107  # DC


def _clear_sheet_data(ws: Worksheet) -> None:
    last_row = max(ws.max_row or HEADER_ROW, HEADER_ROW)
    for r in range(HEADER_ROW, last_row + 1):
        for c in range(1, CLEAR_MAX_COL + 1):
            ws.cell(row=r, column=c).value = None


def write_query_to_sheet(
    workbook_path: Path,
    sheet_name: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> int:
    wb = load_workbook(workbook_path)
    if sheet_name not in wb.sheetnames:
        wb.create_sheet(sheet_name)
    ws = wb[sheet_name]
    _clear_sheet_data(ws)
    for col_idx, header in enumerate(headers, start=1):
        ws.cell(row=HEADER_ROW, column=col_idx).value = header
    for row_idx, row in enumerate(rows, start=DATA_ROW_START):
        for col_idx, value in enumerate(row, start=1):
            if col_idx > len(headers):
                break
            ws.cell(row=row_idx, column=col_idx).value = value
    wb.save(workbook_path)
    wb.close()
    return len(rows)


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute(sql, params).fetchall()]
