"""Общие функции извлечения строк из grid."""

from __future__ import annotations

from typing import Any, Iterator

from sql_upload.excel_grid import cell_at, last_row_in_column
from sql_upload.values import row_from_cells


def iter_grid_rows(
    rows: list[list[str]],
    *,
    row_start: int,
    col_start: int,
    col_end: int,
    last_row_col: int,
    quoteless_last: bool = False,
) -> Iterator[tuple[Any, ...]]:
    last_row = last_row_in_column(rows, last_row_col)
    if last_row < row_start:
        return
    width = col_end - col_start + 1
    for r in range(row_start, last_row + 1):
        cells: list[Any] = []
        for c in range(col_start, col_end + 1):
            cells.append(cell_at(rows, r, c))
        if not any((str(x) or "").strip() for x in cells):
            continue
        yield row_from_cells(cells, quoteless_last=quoteless_last)[:width]
