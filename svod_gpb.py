"""Предсвод ГПБ → predsvod_gpb (лист GPB)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.loaders._predsvod_common import iter_predsvod_sheet_rows
from sql_upload.predsvod_layout import PREDSVOD_SHEETS
from sql_upload.registry import register_loader


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
        yield from iter_predsvod_sheet_rows(path, PREDSVOD_SHEETS["svod_gpb"])
