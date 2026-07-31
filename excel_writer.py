"""Запись Day_Quantity.xlsx / Day_Quantity_DOM.xlsx."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from date_format import (
    report_month_first_day,
    report_month_last_day,
    russian_month_name,
)
from models import DAY_HEADERS, DayQuantityRow

HEADER_META_ROW = 1
HEADER_ROW = 2
DATA_START_ROW = 3
SHEET_NAME = "Day_Quantity"

HEADER_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
HEADER_FONT = Font(bold=True)
META_FONT = Font(bold=True, color="FF0000")
GROUP_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")


def _looks_like_formula(value: str) -> bool:
    return bool(value) and value.lstrip().startswith("=")


def _set_cell(ws: Worksheet, row: int, column: int, value: object) -> None:
    cell = ws.cell(row=row, column=column)
    if isinstance(value, str) and _looks_like_formula(value):
        cell.value = value
        cell.data_type = "s"
    else:
        cell.value = value


def _write_header(ws: Worksheet, report_date: str) -> None:
    month_name = russian_month_name(report_date)
    start = report_month_first_day(report_date)
    end = report_month_last_day(report_date)
    # Предыдущий месяц для подписи «на начало» — день до period_start
    from datetime import datetime, timedelta

    start_dt = datetime.strptime(start, "%d.%m.%Y").date()
    prev_end = (start_dt - timedelta(days=1)).strftime("%d.%m.%Y")

    # A=ДЕПО; B=месяц; C=«из свода депо»; G–I начало; J–L конец; O=дата конца
    _set_cell(ws, HEADER_META_ROW, 2, month_name)
    ws.cell(row=HEADER_META_ROW, column=2).font = META_FONT
    _set_cell(ws, HEADER_META_ROW, 3, "из свода депо")
    _set_cell(ws, HEADER_META_ROW, 7, f"На начало месяца [{prev_end}]")
    ws.cell(row=HEADER_META_ROW, column=7).fill = GROUP_FILL
    ws.cell(row=HEADER_META_ROW, column=7).font = HEADER_FONT
    _set_cell(ws, HEADER_META_ROW, 10, f"На конец месяца [{end}]")
    ws.cell(row=HEADER_META_ROW, column=10).fill = GROUP_FILL
    ws.cell(row=HEADER_META_ROW, column=10).font = META_FONT
    _set_cell(ws, HEADER_META_ROW, 15, end)
    ws.cell(row=HEADER_META_ROW, column=15).font = META_FONT

    for c, title in enumerate(DAY_HEADERS, start=1):
        cell = ws.cell(row=HEADER_ROW, column=c, value=title)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")

    for c in range(7, 10):
        ws.cell(row=HEADER_META_ROW, column=c).fill = GROUP_FILL
    for c in range(10, 13):
        ws.cell(row=HEADER_META_ROW, column=c).fill = GROUP_FILL


def write_day_workbook(
    path: Path,
    rows: list[DayQuantityRow],
    report_date: str,
    *,
    sheet_name: str = SHEET_NAME,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    _write_header(ws, report_date)

    r = DATA_START_ROW
    for row in rows:
        for c, value in enumerate(row.as_tuple(), start=1):
            _set_cell(ws, r, c, value)
        r += 1

    wb.save(path)
    wb.close()
    return path


def write_day_workbooks(
    day_path: Path,
    day_dom_path: Path,
    ia_rows: list[DayQuantityRow],
    dom_rows: list[DayQuantityRow],
    report_date: str,
) -> tuple[Path, Path]:
    write_day_workbook(day_path, ia_rows, report_date, sheet_name="Day_Quantity")
    write_day_workbook(day_dom_path, dom_rows, report_date, sheet_name="Day_Quantity_DOM")
    return day_path, day_dom_path
