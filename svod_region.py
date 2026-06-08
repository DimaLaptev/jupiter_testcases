"""VBA сводРегион → predsvod_region (лист REGION, 24 колонки)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.loaders._workbook_grid import iter_workbook_sheet_rows
from sql_upload.registry import register_loader

_SHEET = "REGION"
_COLS = 24


@register_loader("svod_region")
class SvodRegionLoader:
    name = "svod_region"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="svod_region",
            temp_table="predsvod_region",
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
