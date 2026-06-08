"""Чтение одного workbook / одного листа (VBA предсвод и справочники)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Union

from sql_upload.excel_grid import read_workbook_sheets
from sql_upload.loaders._grid_extract import iter_grid_rows

SheetSelector = Union[str, int]


def resolve_sheet(
    sheets: list[tuple[str, list[list[str]]]],
    sheet: SheetSelector,
) -> tuple[str, list[list[str]]]:
    if isinstance(sheet, int):
        if sheet < 0 or sheet >= len(sheets):
            raise ValueError(f"Лист с индексом {sheet} не найден (всего {len(sheets)})")
        return sheets[sheet]
    name_lower = sheet.strip().lower()
    for title, rows in sheets:
        if title.strip().lower() == name_lower:
            return title, rows
    raise ValueError(f"Лист «{sheet}» не найден в книге")


def iter_workbook_sheet_rows(
    path: Path,
    sheet: SheetSelector,
    *,
    row_start: int = 2,
    col_start: int = 1,
    col_end: int,
    last_row_col: int = 1,
) -> Iterator[tuple[Any, ...]]:
    """Строки одного листа книги (1-based row/col как VBA)."""
    all_sheets = read_workbook_sheets(path)
    if not all_sheets:
        raise ValueError(f"Не удалось прочитать листы: {path}")
    _title, rows = resolve_sheet(all_sheets, sheet)
    yield from iter_grid_rows(
        rows,
        row_start=row_start,
        col_start=col_start,
        col_end=col_end,
        last_row_col=last_row_col,
    )
