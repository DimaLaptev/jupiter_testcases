"""Подключение к SQLite dep_report.db."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = Path(os.environ.get("DEP_REPORT_DB_PATH", str(PROJECT_ROOT / "dep_report.db")))


def open_db(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
