"""Загрузчик ВТБ (VBA Sub ВТБ) → vtb_temp."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets
from sql_upload.registry import register_loader
from sql_upload.values import cell_to_sql_value, row_from_cells


@register_loader("vtb")
class VtbLoader:
    name = "vtb"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="vtb",
            temp_table="vtb_temp",
            clear_before=True,
        )

    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]:
        for _sheet_name, sheet_rows in read_workbook_sheets(path):
            if cell_at(sheet_rows, 11, 6) != "Залогодатель":
                continue
            schet = cell_to_sql_value(cell_at(sheet_rows, 6, 7))
            last_row = last_row_in_column(sheet_rows, 3)
            for r in range(13, last_row + 1):
                cells = [cell_at(sheet_rows, r, c) for c in range(1, 13)]
                if not any((str(x) or "").strip() for x in cells):
                    continue
                data = row_from_cells(cells)
                yield (schet, *data)
