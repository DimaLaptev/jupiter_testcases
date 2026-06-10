"""Общий iter_rows для svod_* loaders."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.loaders._workbook_grid import iter_workbook_sheet_rows
from sql_upload.predsvod_layout import (
    PREDSVOD_COL_END,
    PREDSVOD_COL_START,
    PREDSVOD_LAST_ROW_COL,
    PREDSVOD_ROW_START,
)


def iter_predsvod_sheet_rows(path: Path, sheet_name: str) -> Iterator[tuple[Any, ...]]:
    yield from iter_workbook_sheet_rows(
        path,
        sheet_name,
        row_start=PREDSVOD_ROW_START,
        col_start=PREDSVOD_COL_START,
        col_end=PREDSVOD_COL_END,
        last_row_col=PREDSVOD_LAST_ROW_COL,
    )
