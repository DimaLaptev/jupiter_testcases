"""Загрузчик РСД_доп (VBA Sub РСД_доп) → rsd_dop_temp."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets
from sql_upload.registry import register_loader
from sql_upload.values import cell_to_sql_value, row_from_cells


@register_loader("rsd_dop")
class RsdDopLoader:
    name = "rsd_dop"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="rsd_dop",
            temp_table="rsd_dop_temp",
            clear_before=True,
            run_post_process=True,
        )

    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]:
        for _sheet_name, sheet_rows in read_workbook_sheets(path):
            if cell_at(sheet_rows, 20, 2) != "Счет депо:":
                continue
            schet = cell_to_sql_value(cell_at(sheet_rows, 20, 3))
            last_row = last_row_in_column(sheet_rows, 5)
            for r in range(25, last_row + 1):
                cells = [cell_at(sheet_rows, r, c) for c in range(2, 11)]
                if not any((str(x) or "").strip() for x in cells):
                    continue
                data = row_from_cells(cells)
                yield (schet, *data)
