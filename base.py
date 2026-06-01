"""Базовые типы и конфигурация загрузчиков."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol


@dataclass
class UploadPaths:
    gpb: Path
    vtb: Path
    region: Path
    rsd: Path
    rsd_dop: Path

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
