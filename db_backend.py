"""Абстракция бэкенда БД (SQLite сейчас, SQL Server — позже)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Protocol

from sql_upload.connection import open_db
from sql_upload.writer import clear_table, insert_rows, table_row_count


class DbBackend(Protocol):
    def connect(self) -> sqlite3.Connection: ...
    def clear_table(self, table: str) -> None: ...
    def insert_many(self, table: str, rows: list[tuple[Any, ...]]) -> int: ...
    def row_count(self, table: str) -> int: ...
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


class SqliteBackend:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = open_db(self._db_path)
        return self._conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connect()

    def clear_table(self, table: str) -> None:
        clear_table(self.conn, table)

    def insert_many(self, table: str, rows: list[tuple[Any, ...]]) -> int:
        return insert_rows(self.conn, table, rows)

    def row_count(self, table: str) -> int:
        return table_row_count(self.conn, table)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.conn.execute(sql, params)

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
