"""Предсвод Регион → predsvod_region (лист REGION)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.loaders._predsvod_common import iter_predsvod_sheet_rows
from sql_upload.predsvod_layout import PREDSVOD_SHEETS
from sql_upload.registry import register_loader


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
        yield from iter_predsvod_sheet_rows(path, PREDSVOD_SHEETS["svod_region"])
