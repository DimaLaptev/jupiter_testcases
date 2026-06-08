"""Базовые типы и конфигурация загрузчиков."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol

from sql_upload.schema_registry import WORKBOOK_LOADER_NAMES

_SVOD_WORKBOOK_KEYS = {
    "svod_gpb": "svod_gpb_workbook",
    "svod_vtb": "svod_vtb_workbook",
    "svod_region": "svod_region_workbook",
    "svod_rsd": "svod_rsd_workbook",
}


@dataclass
class LegacySqlPaths:
    """Каталоги upload (колонка B) и workbook предсвода/справочника (колонка O)."""

    gpb: Path
    vtb: Path
    region: Path
    rsd: Path
    rsd_dop: Path
    svod_gpb_workbook: Path
    svod_vtb_workbook: Path
    svod_region_workbook: Path
    svod_rsd_workbook: Path
    sprav_workbook: Path
    svod_depo_workbook: Path  # 2_СВОД_поДЕПО.xlsx (без макросов)

    def dir_for(self, loader_name: str) -> Path:
        mapping = {
            "gpb": self.gpb,
            "region": self.region,
            "region2": self.region,
            "vtb": self.vtb,
            "rsd": self.rsd,
            "rsd_dop": self.rsd_dop,
        }
        if loader_name not in mapping:
            raise KeyError(f"Нет каталога для загрузчика: {loader_name}")
        return mapping[loader_name]

    def workbook_for(self, loader_name: str) -> Path:
        if loader_name in ("spravochnik_1", "spravochnik_2"):
            return self.sprav_workbook
        key = _SVOD_WORKBOOK_KEYS.get(loader_name)
        if key is None:
            raise KeyError(f"Нет workbook для загрузчика: {loader_name}")
        return getattr(self, key)

    def input_for(self, loader_name: str) -> Path:
        if loader_name in WORKBOOK_LOADER_NAMES:
            return self.workbook_for(loader_name)
        return self.dir_for(loader_name)


# Обратная совместимость
UploadPaths = LegacySqlPaths


@dataclass
class LoaderConfig:
    name: str
    temp_table: str
    clear_before: bool
    run_post_process: bool = False


@dataclass
class UploadStats:
    loader: str
    files_seen: int = 0
    files_loaded: int = 0
    rows_inserted: int = 0
    errors: list[str] = field(default_factory=list)

    def merge_error(self, msg: str) -> None:
        self.errors.append(msg)


class SqlLoader(Protocol):
    name: str

    def loader_config(self) -> LoaderConfig: ...
    def iter_rows(self, path: Path) -> Iterator[tuple[Any, ...]]: ...


def is_workbook_loader(loader_name: str) -> bool:
    return loader_name in WORKBOOK_LOADER_NAMES
