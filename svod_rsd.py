"""Предсвод РСД → predsvod_rsd (лист RSD_MSG)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sql_upload.base import LoaderConfig
from sql_upload.loaders._predsvod_common import iter_predsvod_sheet_rows
from sql_upload.predsvod_layout import PREDSVOD_SHEETS
from sql_upload.registry import register_loader


@register_loader("svod_rsd")
class SvodRsdLoader:
    name = "svod_rsd"

    def loader_config(self) -> LoaderConfig:
        return LoaderConfig(
            name="svod_rsd",
            temp_table="predsvod_rsd",
            clear_before=True,
        )

    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]:
        yield from iter_predsvod_sheet_rows(path, PREDSVOD_SHEETS["svod_rsd"])
