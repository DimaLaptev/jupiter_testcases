#!/usr/bin/env python3
"""Точка входа legacy ETL: upload, sprav, svod, depo → SQLite (замена VBA)."""

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
from sql_upload.depo.runner import DepoStepStats, FormUpdateParams
from sql_upload.depo.steps import DEFAULT_DEPO_PIPELINE_ORDER, DEPO_STEPS
from sql_upload.pipeline import (
    DEFAULT_PIPELINE_ORDER,
    DEFAULT_SPRAV_PIPELINE_ORDER,
    DEFAULT_SVOD_PIPELINE_ORDER,
    PipelineResult,
    run_depo_pipeline,
    run_full_legacy_sql,
    run_pipeline,
    run_sprav_pipeline,
    run_svod_pipeline,
)
from sql_upload.loaders import register_all_loaders
from sql_upload.registry import LOADER_REGISTRY

register_all_loaders()

_ALL_UPLOAD_STEPS = sorted(LOADER_REGISTRY.keys())
_ALL_DEPO_STEPS = sorted(DEPO_STEPS.keys())
_PHASE_CHOICES = ("upload", "sprav", "svod", "depo", "all")


def _resolve_upload_steps(
    phase: str,
    step: str,
    pipeline_map: dict[str, list[str]],
) -> tuple[list[str] | None, bool, bool, bool, bool]:
    skip_sprav = False
    skip_svod = False
    skip_depo = False

    if step != "all":
        return [step], True, True, True

    if phase == "upload":
        return pipeline_map.get("upload", DEFAULT_PIPELINE_ORDER), True, True, True
    if phase == "sprav":
        return pipeline_map.get("sprav", DEFAULT_SPRAV_PIPELINE_ORDER), True, True, True
    if phase == "svod":
        return pipeline_map.get("svod", DEFAULT_SVOD_PIPELINE_ORDER), True, True, True
    if phase == "depo":
        return None, True, True, True
    return None, False, False, False


def _resolve_depo_steps(
    phase: str,
    step: str,
    pipeline_map: dict[str, list[str]],
) -> list[str] | None:
    if step != "all" and step in DEPO_STEPS:
        return [step]
    if phase == "depo" or phase == "all":
        return pipeline_map.get("depo", DEFAULT_DEPO_PIPELINE_ORDER)
    return None


def _print_upload_stats(result: PipelineResult) -> int:
    total_rows = 0
    has_errors = False
    for stats in result.steps:
        total_rows += stats.rows_inserted
        status = "OK" if not stats.errors else "ERR"
        print(
            f"[{status}] {stats.loader}: файлов {stats.files_loaded}/{stats.files_seen}, "
            f"строк {stats.rows_inserted}",
        )
        for err in stats.errors:
            print(f"  ! {err}", file=sys.stderr)
        if stats.errors:
            has_errors = True

    if result.post_process:
        print(
            "post_process:",
            f"schet обновлено {result.post_process.get('schet_rows_updated', 0)}, "
            f"working_mortgage {result.post_process.get('working_mortgage_rows', 0)} строк",
        )
    return total_rows, has_errors


def _print_depo_stats(
    depo_steps: list[DepoStepStats],
    *,
    fail_on_duplicates: bool,
) -> bool:
    has_errors = False
    for stats in depo_steps:
        if stats.errors:
            status = "ERR"
            has_errors = True
        elif stats.duplicate_count > 0:
            status = "WARN"
            if fail_on_duplicates:
                has_errors = True
        elif stats.warnings:
            status = "WARN"
        else:
            status = "OK"

        parts = [f"[{status}] {stats.step}"]
        if stats.step == "depo_add_new":
            parts.append(
                f"строк {stats.rows_read} → ruki_temp, merge {stats.rows_merged} → editable_registry",
            )
        elif stats.step == "depo_archive":
            extra = stats.extra
            parts.append(
                f"predsvod_* → archive, таблиц {extra.get('tables_archived', 0)}, "
                f"строк {stats.rows_written}",
            )
        elif stats.step.startswith("depo_check_"):
            sheet = stats.sheet_name or ""
            parts.append(f"дублей/проблем {stats.duplicate_count}, лист «{sheet}»")
        elif stats.step == "depo_form_update":
            parts.append(f"обновлено строк {stats.rows_merged}")
        else:
            sheet = stats.sheet_name or ""
            parts.append(f"строк {stats.rows_written} → лист «{sheet}»")

        parts.append(f"{stats.elapsed_sec:.2f} сек")
        print(", ".join(parts))

        for w in stats.warnings:
            print(f"  ~ {w}")
        for err in stats.errors:
            print(f"  ! {err}", file=sys.stderr)

    return has_errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Legacy ETL: upload / sprav / svod / depo to SQLite.",
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
        help="YAML с путями и порядком pipeline",
    )
    parser.add_argument(
        "--phase",
        choices=_PHASE_CHOICES,
        default="upload",
        help="upload | sprav | svod | depo | all",
    )
    parser.add_argument(
        "--step",
        default="all",
        help="upload/svod/sprav: имя загрузчика или all; depo: depo_* или all",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Создать/обновить схему БД перед загрузкой",
    )
    parser.add_argument(
        "--skip-post-process",
        action="store_true",
        help="Не выполнять post_process после rsd_dop (только upload)",
    )
    parser.add_argument(
        "--skip-sprav",
        action="store_true",
        help="При --phase all не загружать справочники",
    )
    parser.add_argument(
        "--skip-svod",
        action="store_true",
        help="При --phase all не загружать предсвод",
    )
    parser.add_argument(
        "--skip-depo",
        action="store_true",
        help="При --phase all не выполнять фазу depo",
    )
    parser.add_argument(
        "--no-fail-on-duplicates",
        action="store_true",
        help="Не завершать с ошибкой при дублях в check-шагах depo",
    )
    parser.add_argument("--ngri", default="", help="depo_form_update: НГРИ в депо")
    parser.add_argument("--zakladnay", default="", help="depo_form_update: № закладной")
    parser.add_argument("--comment", default="", help="depo_form_update: комментарий")
    parser.add_argument(
        "--archived-at",
        default="",
        help="Метка времени для depo_archive (ISO), по умолчанию now",
    )
    args = parser.parse_args()

    if args.init_db or not args.db.exists():
        init_database(args.db)

    if not args.config.exists():
        print(f"Файл конфигурации не найден: {args.config}", file=sys.stderr)
        return 2

    paths, pipeline_map = load_upload_config(args.config, _ROOT)
    upload_steps, skip_sprav, skip_svod, skip_depo = _resolve_upload_steps(
        args.phase,
        args.step,
        pipeline_map,
    )
    depo_steps_order = _resolve_depo_steps(args.phase, args.step, pipeline_map)
    if args.skip_sprav:
        skip_sprav = True
    if args.skip_svod:
        skip_svod = True
    if args.skip_depo:
        skip_depo = True

    fail_on_duplicates = not args.no_fail_on_duplicates
    archived_at = args.archived_at or None
    form_params = None
    if args.step == "depo_form_update" or (args.ngri and args.phase == "depo"):
        form_params = FormUpdateParams(
            ngri=args.ngri,
            zakladnoy=args.zakladnay,
            comment=args.comment,
        )

    backend = SqliteBackend(args.db)
    t0 = time.perf_counter()
    result = PipelineResult()
    depo_only = False
    try:
        if args.phase == "depo":
            depo_only = True
            depo_result = run_depo_pipeline(
                backend,
                paths,
                depo_steps_order,
                form_params=form_params,
                archived_at=archived_at,
            )
            result.depo_steps = depo_result.steps
        elif args.phase == "all" and args.step == "all":
            result = run_full_legacy_sql(
                backend,
                paths,
                upload_steps=pipeline_map.get("upload"),
                sprav_steps=None if skip_sprav else pipeline_map.get("sprav"),
                svod_steps=None if skip_svod else pipeline_map.get("svod"),
                skip_post_process=args.skip_post_process,
                skip_sprav=skip_sprav,
                skip_svod=skip_svod,
                skip_depo=skip_depo,
                depo_steps=depo_steps_order,
                archived_at=archived_at,
            )
        elif args.phase == "sprav":
            result = run_sprav_pipeline(backend, paths, upload_steps)
        elif args.phase == "svod":
            result = run_svod_pipeline(backend, paths, upload_steps)
        else:
            result = run_pipeline(
                backend,
                paths,
                upload_steps,
                skip_post_process=args.skip_post_process,
            )
    finally:
        backend.close()

    elapsed = time.perf_counter() - t0
    total_rows, upload_errors = _print_upload_stats(result)
    depo_errors = False
    if result.depo_steps:
        depo_errors = _print_depo_stats(
            result.depo_steps,
            fail_on_duplicates=fail_on_duplicates,
        )

    if depo_only:
        print(f"Готово за {elapsed:.2f} сек., depo-шагов: {len(result.depo_steps)}")
    else:
        print(f"Готово за {elapsed:.2f} сек., всего INSERT: {total_rows}")

    return 1 if upload_errors or depo_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
