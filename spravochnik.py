"""VBA Справочник1/2 → spravochnik_1/2 (листы 1 и 2 по индексу)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.loaders._workbook_grid import iter_workbook_sheet_rows
from sql_upload.registry import register_loader


@register_loader("spravochnik_1")
class Spravochnik1Loader:
    name = "spravochnik_1"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="spravochnik_1",
            temp_table="spravochnik_1",
            clear_before=True,
        )

    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]:
        yield from iter_workbook_sheet_rows(
            path,
            0,
            row_start=2,
            col_start=1,
            col_end=7,
            last_row_col=1,
        )


@register_loader("spravochnik_2")
class Spravochnik2Loader:
    name = "spravochnik_2"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="spravochnik_2",
            temp_table="spravochnik_2",
            clear_before=True,
        )

    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]:
        yield from iter_workbook_sheet_rows(
            path,
            1,
            row_start=2,
            col_start=1,
            col_end=3,
            last_row_col=1,
        )
