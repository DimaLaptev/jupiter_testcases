"""Статистика и запуск одного depo-шага."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sql_upload.depo.excel_reader import read_add_new_rows
from sql_upload.depo.excel_writer import fetch_all, write_query_to_sheet
from sql_upload.depo.procedures import (
    run_form_update,
    run_napolnenie_ruki,
    run_perenos_v_archive,
    sync_editable_from_predsvod,
)
from sql_upload.depo.steps import (
    DUBLI_NGRI_HEADERS,
    DUBLI_ZAKLADNYE_HEADERS,
    PROVERKA_ZAGRUZKI_HEADERS,
    SBOR_REESTRA_HEADERS,
    DepoStepDef,
    DepoStepKind,
    get_depo_step,
)
from sql_upload.depo.views import ensure_depo_views, sbor_reestra_query


@dataclass
class DepoStepStats:
    step: str
    rows_read: int = 0
    rows_written: int = 0
    rows_merged: int = 0
    duplicate_count: int = 0
    sheet_name: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    elapsed_sec: float = 0.0

    def merge_error(self, msg: str) -> None:
        self.errors.append(msg)

    def merge_warning(self, msg: str) -> None:
        self.warnings.append(msg)


@dataclass
class FormUpdateParams:
    ngri: str
    zakladnoy: str
    comment: str


def _prepare_registry(conn: sqlite3.Connection) -> None:
    sync_editable_from_predsvod(conn)
    ensure_depo_views(conn)


def run_depo_step(
    conn: sqlite3.Connection,
    step_name: str,
    workbook_path: Path,
    *,
    form_params: FormUpdateParams | None = None,
    archived_at: str | None = None,
) -> DepoStepStats:
    step = get_depo_step(step_name)
    stats = DepoStepStats(step=step_name, sheet_name=step.sheet_name)
    t0 = time.perf_counter()

    try:
        if not workbook_path.is_file() and step.kind != DepoStepKind.PROCEDURE:
            stats.merge_error(f"Workbook не найден: {workbook_path}")
            return stats

        _prepare_registry(conn)

        if step.kind == DepoStepKind.IMPORT:
            _run_import(conn, step, workbook_path, stats)
        elif step.kind == DepoStepKind.EXPORT:
            _run_export(conn, step, workbook_path, stats)
        elif step.kind == DepoStepKind.CHECK:
            _run_check(conn, step, workbook_path, stats)
        elif step.kind == DepoStepKind.PROCEDURE:
            _run_procedure(conn, stats, archived_at=archived_at)
        elif step.kind == DepoStepKind.FORM:
            _run_form(conn, form_params, stats)
        else:
            stats.merge_error(f"Неизвестный kind: {step.kind}")
    except Exception as exc:
        stats.merge_error(str(exc))
    finally:
        stats.elapsed_sec = time.perf_counter() - t0

    if step.kind in (DepoStepKind.EXPORT, DepoStepKind.CHECK):
        stats.merge_warning("formatting=skipped")

    return stats


def _run_import(
    conn: sqlite3.Connection,
    step: DepoStepDef,
    workbook_path: Path,
    stats: DepoStepStats,
) -> None:
    sheet = step.add_sheet_name or ""
    rows = read_add_new_rows(workbook_path, sheet)
    stats.rows_read = len(rows)
    if not rows:
        stats.merge_warning("лист «Добавление новых» пуст — пропуск INSERT")
        return
    conn.execute("DELETE FROM ruki_temp")
    conn.executemany(
        """
        INSERT INTO ruki_temp (col_01, col_02, col_03, col_04, col_05, col_06, col_07, col_08)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    result = run_napolnenie_ruki(conn)
    stats.rows_merged = result["ruki_rows_merged"]
    stats.rows_written = stats.rows_merged
    ensure_depo_views(conn)


def _run_export(
    conn: sqlite3.Connection,
    step: DepoStepDef,
    workbook_path: Path,
    stats: DepoStepStats,
) -> None:
    if not step.portfolio_section or not step.sheet_name:
        stats.merge_error("export: не задан portfolio_section или sheet_name")
        return
    sql, params = sbor_reestra_query(step.portfolio_section)
    rows = fetch_all(conn, sql, params)
    stats.rows_read = len(rows)
    written = write_query_to_sheet(
        workbook_path,
        step.sheet_name,
        SBOR_REESTRA_HEADERS,
        rows,
    )
    stats.rows_written = written


def _run_check(
    conn: sqlite3.Connection,
    step: DepoStepDef,
    workbook_path: Path,
    stats: DepoStepStats,
) -> None:
    if not step.sql or not step.sheet_name:
        stats.merge_error("check: не задан sql или sheet_name")
        return
    headers_map = {
        "depo_check_upload": PROVERKA_ZAGRUZKI_HEADERS,
        "depo_check_ngri": DUBLI_NGRI_HEADERS,
        "depo_check_mortgage": DUBLI_ZAKLADNYE_HEADERS,
    }
    headers = headers_map.get(step.name, ())
    rows = fetch_all(conn, step.sql)
    stats.rows_read = len(rows)
    stats.duplicate_count = len(rows)
    if step.name == "depo_check_ngri":
        export_rows = [(r[0], r[1]) for r in rows]
    elif step.name == "depo_check_mortgage":
        export_rows = [(r[0], r[1]) for r in rows]
    else:
        export_rows = rows
    stats.rows_written = write_query_to_sheet(
        workbook_path,
        step.sheet_name,
        headers,
        export_rows,
    )


def _run_procedure(
    conn: sqlite3.Connection,
    stats: DepoStepStats,
    *,
    archived_at: str | None,
) -> None:
    result = run_perenos_v_archive(conn, archived_at=archived_at)
    stats.rows_written = result["archived_rows"]
    stats.extra = result


def _run_form(
    conn: sqlite3.Connection,
    form_params: FormUpdateParams | None,
    stats: DepoStepStats,
) -> None:
    if form_params is None:
        stats.merge_error("depo_form_update: нужны --ngri, --zakladnay, --comment")
        return
    updated = run_form_update(
        conn,
        form_params.ngri,
        form_params.zakladnoy,
        form_params.comment,
    )
    stats.rows_merged = updated
    ensure_depo_views(conn)
