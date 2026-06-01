"""Загрузчик Регион v1 (VBA Sub Регион) → region_temp, без DELETE."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.excel_grid import cell_at, read_workbook_sheets
from sql_upload.loaders._grid_extract import iter_grid_rows
from sql_upload.registry import register_loader


@register_loader("region")
class RegionLoader:
    name = "region"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="region",
            temp_table="region_temp",
            clear_before=False,
        )

    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]:
        for _sheet_name, sheet_rows in read_workbook_sheets(path):
            if cell_at(sheet_rows, 1, 1) != "/DEPOACCOUNT_BALANCE_REPORT":
                continue
            yield from iter_grid_rows(
                sheet_rows,
                row_start=3,
                col_start=1,
                col_end=40,
                last_row_col=2,
                quoteless_last=True,
            )
