"""VBA сводГПБ → predsvod_gpb (лист GPB, 24 колонки)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.loaders._workbook_grid import iter_workbook_sheet_rows
from sql_upload.registry import register_loader

_SHEET = "GPB"
_COLS = 24


@register_loader("svod_gpb")
class SvodGpbLoader:
    name = "svod_gpb"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="svod_gpb",
            temp_table="predsvod_gpb",
            clear_before=True,
        )

    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]:
        yield from iter_workbook_sheet_rows(
            path,
            _SHEET,
            row_start=2,
            col_start=1,
            col_end=_COLS,
            last_row_col=1,
        )
