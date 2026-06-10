"""Справочник.xls → spravochnik_1 (13 col) / spravochnik_2 (3 col)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.loaders._workbook_grid import iter_workbook_sheet_rows
from sql_upload.predsvod_layout import (
    SPRAV1_ACCOUNT_COL,
    SPRAV1_COL_END,
    SPRAV1_ROW_START,
    SPRAV2_COL_END,
    SPRAV2_ROW_START,
)
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
            row_start=SPRAV1_ROW_START,
            col_start=1,
            col_end=SPRAV1_COL_END,
            last_row_col=SPRAV1_ACCOUNT_COL,
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
            row_start=SPRAV2_ROW_START,
            col_start=1,
            col_end=SPRAV2_COL_END,
            last_row_col=1,
        )
