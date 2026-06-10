"""Предсвод ВТБ → predsvod_vtb (лист VTBSD)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.loaders._predsvod_common import iter_predsvod_sheet_rows
from sql_upload.predsvod_layout import PREDSVOD_SHEETS
from sql_upload.registry import register_loader


@register_loader("svod_vtb")
class SvodVtbLoader:
    name = "svod_vtb"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="svod_vtb",
            temp_table="predsvod_vtb",
            clear_before=True,
        )

    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]:
        yield from iter_predsvod_sheet_rows(path, PREDSVOD_SHEETS["svod_vtb"])
