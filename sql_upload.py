#!/usr/bin/env python3
"""Точка входа legacy ETL: загрузка отчётов в SQLite staging-таблицы (замена VBA)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sql_upload.config_loader import load_upload_config
from sql_upload.connection import DEFAULT_DB_PATH
from sql_upload.db_backend import SqliteBackend
from sql_upload.db_init import init_database
from sql_upload.pipeline import DEFAULT_PIPELINE_ORDER, run_pipeline
from sql_upload.registry import LOADER_REGISTRY

import sql_upload.loaders  # noqa: F401


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Legacy ETL: загрузка отчётов депозитариев в SQLite (замена VBA-макросов).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Путь к SQLite (default: dep_report.db)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_ROOT / "config" / "upload_paths.example.yaml",
        help="YAML с путями к каталогам и порядком pipeline",
    )
    parser.add_argument(
        "--step",
        choices=[*LOADER_REGISTRY.keys(), "all"],
        default="all",
        help="Один загрузчик или all (весь pipeline)",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Создать/обновить схему БД перед загрузкой",
    )
    parser.add_argument(
        "--skip-post-process",
        action="store_true",
        help="Не выполнять post_process после rsd_dop",
    )
    args = parser.parse_args()

    if args.init_db or not args.db.exists():
        init_database(args.db)

    if not args.config.exists():
        print(f"Файл конфигурации не найден: {args.config}", file=sys.stderr)
        return 2

    paths, pipeline_order = load_upload_config(args.config, _ROOT)
    steps = pipeline_order if args.step == "all" else [args.step]

    backend = SqliteBackend(args.db)
    t0 = time.perf_counter()
    try:
        result = run_pipeline(
            backend,
            paths,
            steps,
            skip_post_process=args.skip_post_process,
        )
    finally:
        backend.close()

    elapsed = time.perf_counter() - t0
    total_rows = 0
    for stats in result.steps:
        total_rows += stats.rows_inserted
        status = "OK" if not stats.errors else "ERR"
        print(
            f"[{status}] {stats.loader}: файлов {stats.files_loaded}/{stats.files_seen}, "
            f"строк {stats.rows_inserted}",
        )
        for err in stats.errors:
            print(f"  ! {err}", file=sys.stderr)

    if result.post_process:
        print(
            "post_process:",
            f"schet обновлено {result.post_process.get('schet_rows_updated', 0)}, "
            f"working_mortgage {result.post_process.get('working_mortgage_rows', 0)} строк",
        )

    print(f"Готово за {elapsed:.2f} сек., всего INSERT: {total_rows}")
    return 1 if any(s.errors for s in result.steps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
