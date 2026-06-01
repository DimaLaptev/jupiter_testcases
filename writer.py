"""Запись в SQLite: DELETE, batch INSERT."""

from __future__ import annotations

import sqlite3
from typing import Any

from sql_upload.schema_registry import assert_row_width, columns_for

BATCH_SIZE = 500


def clear_table(conn: sqlite3.Connection, table: str) -> None:
    conn.execute(f"DELETE FROM {table}")


def insert_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: list[tuple[Any, ...]],
    *,
    columns: list[str] | None = None,
) -> int:
    if not rows:
        return 0
    cols = columns or columns_for(table)
    for row in rows:
        assert_row_width(table, row)
    placeholders = ",".join("?" * len(cols))
    col_list = ",".join(cols)
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    for i in range(0, len(rows), BATCH_SIZE):
        conn.executemany(sql, rows[i : i + BATCH_SIZE])
    return len(rows)


def table_row_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0]) if row else 0
