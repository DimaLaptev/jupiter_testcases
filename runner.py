"""Общая логика запуска одного загрузчика."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sql_upload.base import SqlLoader, UploadStats
from sql_upload.db_backend import SqliteBackend
from sql_upload.excel_grid import iter_files_in_dir


def run_loader(
    loader: SqlLoader,
    backend: SqliteBackend,
    input_dir: Path,
) -> UploadStats:
    cfg = loader.loader_config()
    stats = UploadStats(loader=cfg.name)

    if not input_dir.is_dir():
        stats.merge_error(f"Каталог не найден: {input_dir}")
        return stats

    if cfg.clear_before:
        backend.clear_table(cfg.temp_table)

    batch: list[tuple[Any, ...]] = []
    batch_size = 500

    for path in iter_files_in_dir(input_dir):
        stats.files_seen += 1
        try:
            row_count = 0
            for row in loader.iter_rows(path):
                batch.append(row)
                row_count += 1
                if len(batch) >= batch_size:
                    stats.rows_inserted += backend.insert_many(cfg.temp_table, batch)
                    batch.clear()
            if row_count > 0:
                stats.files_loaded += 1
        except Exception as exc:
            stats.merge_error(f"{path.name}: {exc}")

    if batch:
        stats.rows_inserted += backend.insert_many(cfg.temp_table, batch)

    backend.commit()
    return stats


def run_workbook_loader(
    loader: SqlLoader,
    backend: SqliteBackend,
    workbook_path: Path,
) -> UploadStats:
    """Один workbook на загрузчик (predsvod / spravochnik)."""
    cfg = loader.loader_config()
    stats = UploadStats(loader=cfg.name)

    if not workbook_path.is_file():
        stats.merge_error(f"Файл не найден: {workbook_path}")
        return stats

    if cfg.clear_before:
        backend.clear_table(cfg.temp_table)

    stats.files_seen = 1
    batch: list[tuple[Any, ...]] = []
    batch_size = 500

    try:
        row_count = 0
        for row in loader.iter_rows(workbook_path):
            batch.append(row)
            row_count += 1
            if len(batch) >= batch_size:
                stats.rows_inserted += backend.insert_many(cfg.temp_table, batch)
                batch.clear()
        if row_count > 0:
            stats.files_loaded = 1
    except Exception as exc:
        stats.merge_error(f"{workbook_path.name}: {exc}")

    if batch:
        stats.rows_inserted += backend.insert_many(cfg.temp_table, batch)

    backend.commit()
    return stats
