"""Запись СВОД_поДЕПО.xlsx и СВОД_поДЕПО_ДОМ.xlsx."""

from __future__ import annotations

import shutil
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from models import (
    SVOD_DOM_SHEETS,
    SVOD_HEADERS,
    SVOD_IA_SHEETS,
    SvodRow,
)

HEADER_ROW = 5
DATA_START_ROW = 6


def _write_data_rows(ws: Worksheet, rows: list[SvodRow], start_row: int = DATA_START_ROW) -> int:
    r = start_row
    for row in rows:
        for c, val in enumerate(row.as_tuple(), start=1):
            ws.cell(row=r, column=c, value=val)
        r += 1
    return r - start_row


def _init_sheet_from_template(ws: Worksheet, report_date: str, row_count: int) -> None:
    ws.cell(row=1, column=1, value=report_date)
    ws.cell(row=1, column=3, value=row_count)
    for c, title in enumerate(SVOD_HEADERS, start=1):
        ws.cell(row=HEADER_ROW, column=c, value=title)


def _init_blank_sheet(ws: Worksheet, report_date: str, row_count: int) -> None:
    _init_sheet_from_template(ws, report_date, row_count)


def _write_workbook(
    output_path: Path,
    rows_by_sheet: dict[str, list[SvodRow]],
    sheet_order: tuple[str, ...],
    report_date: str,
    template_path: Path | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if template_path and template_path.is_file():
        shutil.copy2(template_path, output_path)
        wb = load_workbook(output_path)
        for sheet_name in sheet_order:
            if sheet_name not in wb.sheetnames:
                wb.create_sheet(sheet_name)
            ws = wb[sheet_name]
            count = len(rows_by_sheet.get(sheet_name, []))
            ws.cell(row=1, column=1, value=report_date)
            ws.cell(row=1, column=3, value=count)
            if ws.max_row >= DATA_START_ROW:
                ws.delete_rows(DATA_START_ROW, ws.max_row - DATA_START_ROW + 1)
            _write_data_rows(ws, rows_by_sheet.get(sheet_name, []))
        for name in list(wb.sheetnames):
            if name not in sheet_order:
                del wb[name]
        wb.save(output_path)
        wb.close()
        return output_path

    wb = Workbook()
    default = wb.active
    wb.remove(default)

    for sheet_name in sheet_order:
        ws = wb.create_sheet(sheet_name)
        rows = rows_by_sheet.get(sheet_name, [])
        _init_blank_sheet(ws, report_date, len(rows))
        _write_data_rows(ws, rows)

    wb.save(output_path)
    wb.close()
    return output_path


def write_svod_workbooks(
    svod_path: Path,
    svod_dom_path: Path,
    rows_by_sheet: dict[str, list[SvodRow]],
    report_date: str,
    template_path: Path | None = None,
    template_dom_path: Path | None = None,
) -> tuple[Path, Path]:
    ia_rows = {name: rows_by_sheet.get(name, []) for name in SVOD_IA_SHEETS}
    dom_rows = {name: rows_by_sheet.get(name, []) for name in SVOD_DOM_SHEETS}
    _write_workbook(svod_path, ia_rows, SVOD_IA_SHEETS, report_date, template_path)
    _write_workbook(svod_dom_path, dom_rows, SVOD_DOM_SHEETS, report_date, template_dom_path)
    return svod_path, svod_dom_path
