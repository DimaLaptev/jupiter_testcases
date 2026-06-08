"""Чтение листа «Добавление новых» (add_new.txt)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from sql_upload.depo.steps import ADD_NEW_COLS, ADD_NEW_ROW_START, ADD_NEW_SHEET
from sql_upload.values import cell_to_sql_value


def read_add_new_rows(workbook_path: Path, sheet_name: str = ADD_NEW_SHEET) -> list[tuple[Any, ...]]:
    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return []
    ws = wb[sheet_name]
    rows_out: list[tuple[Any, ...]] = []
    for r in range(ADD_NEW_ROW_START, (ws.max_row or 0) + 1):
        values = [
            cell_to_sql_value(ws.cell(row=r, column=c).value)
            for c in range(1, ADD_NEW_COLS + 1)
        ]
        if all(v is None for v in values):
            continue
        rows_out.append(tuple(values))
    wb.close()
    return rows_out
