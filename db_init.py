"""Инициализация SQLite из schema/*.sql."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sql_upload.connection import DEFAULT_DB_PATH, PROJECT_ROOT

SCHEMA_DIR = PROJECT_ROOT / "schema"


def list_schema_files() -> list[Path]:
    if not SCHEMA_DIR.is_dir():
        return []
    return sorted(SCHEMA_DIR.glob("*.sql"))


def apply_schema(conn: sqlite3.Connection, *, force: bool = False) -> list[str]:
    applied: list[str] = []
    if force:
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        ).fetchall():
            conn.execute(f"DROP TABLE IF EXISTS {row[0]}")
        conn.commit()

    for sql_file in list_schema_files():
        conn.executescript(sql_file.read_text(encoding="utf-8"))
        applied.append(sql_file.name)
    conn.commit()
    return applied


def init_database(db_path: Path | None = None, *, force: bool = False) -> Path:
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    try:
        apply_schema(conn, force=force)
    finally:
        conn.close()
    return path


def list_user_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).fetchall()
    return [str(r[0]) for r in rows]
