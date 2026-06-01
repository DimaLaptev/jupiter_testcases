"""Загрузчик ГПБ (VBA Sub ГПБ) → gpb_temp."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.excel_grid import read_workbook_sheets
from sql_upload.loaders._grid_extract import iter_grid_rows
from sql_upload.msg_grid import msg_path_to_rows, sheet_a8_empty
from sql_upload.registry import register_loader


@register_loader("gpb")
class GpbLoader:
    name = "gpb"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="gpb",
            temp_table="gpb_temp",
            clear_before=True,
        )

    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]:
        suffix = path.suffix.lower()
        if suffix == ".msg":
            rows = msg_path_to_rows(path)
            if sheet_a8_empty(rows):
                yield from iter_grid_rows(
                    rows,
                    row_start=9,
                    col_start=1,
                    col_end=9,
                    last_row_col=1,
                )
            return

        for _sheet_name, sheet_rows in read_workbook_sheets(path):
            if sheet_a8_empty(sheet_rows):
                yield from iter_grid_rows(
                    sheet_rows,
                    row_start=9,
                    col_start=1,
                    col_end=9,
                    last_row_col=1,
                )
