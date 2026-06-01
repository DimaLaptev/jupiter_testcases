"""Post-process: аналог EXEC [Добавление_нолей] и [наполнение_изменяемой]."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from sql_upload.schema_registry import TABLE_COLUMNS

SChet_TABLES = ("vtb_temp", "rsd_dop_temp")


def _normalize_schet(value: str | None) -> str | None:
    """9 цифр с «3» в начале → дописать «000» (как normalize_r01_depo_account)."""
    if value is None:
        return None
    s = re.sub(r"\s+", "", value.strip())
    if not s or not s.isdigit():
        return value.strip() or None
    if len(s) == 9 and s.startswith("3"):
        return "000" + s
    return s


def apply_zero_padding(conn: sqlite3.Connection) -> int:
    """
    v1: нормализация schet в vtb_temp и rsd_dop_temp.
    Полная логика [Добавление_нолей] — TODO при доступе к SP hatunceva.
    """
    updated = 0
    for table in SChet_TABLES:
        rows = conn.execute(f"SELECT rowid, schet FROM {table} WHERE schet IS NOT NULL").fetchall()
        for rowid, schet in rows:
            new_val = _normalize_schet(str(schet))
            if new_val != schet:
                conn.execute(f"UPDATE {table} SET schet = ? WHERE rowid = ?", (new_val, rowid))
                updated += 1
    return updated


def _row_to_dict(table: str, columns: list[str], values: tuple[Any, ...]) -> dict[str, Any]:
    return {col: values[i] for i, col in enumerate(columns)}


def fill_working_table(conn: sqlite3.Connection) -> int:
    """Собрать working_mortgage из всех staging-таблиц."""
    conn.execute("DELETE FROM working_mortgage")
    inserted = 0
    source_map = {
        "gpb_temp": "gpb",
        "region_temp": "region",
        "region2_temp": "region2",
        "vtb_temp": "vtb",
        "rsd_temp": "rsd",
        "rsd_dop_temp": "rsd_dop",
    }
    for table, source in source_map.items():
        columns = TABLE_COLUMNS[table]
        col_list = ", ".join(columns)
        for row in conn.execute(f"SELECT {col_list} FROM {table}").fetchall():
            data = _row_to_dict(table, columns, tuple(row))
            schet = data.get("schet")
            conn.execute(
                "INSERT INTO working_mortgage (source, schet, data_json) VALUES (?, ?, ?)",
                (source, schet, json.dumps(data, ensure_ascii=False)),
            )
            inserted += 1
    return inserted


def run_post_process(conn: sqlite3.Connection) -> dict[str, int]:
    padded = apply_zero_padding(conn)
    filled = fill_working_table(conn)
    conn.commit()
    return {"schet_rows_updated": padded, "working_mortgage_rows": filled}
