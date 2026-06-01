#!/usr/bin/env python3
"""Создание SQLite dep_report.db и применение schema/*.sql."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sql_upload.connection import DEFAULT_DB_PATH, open_db
from sql_upload.db_init import apply_schema, init_database, list_user_tables
from sql_upload.writer import table_row_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Инициализация SQLite dep_report.db из schema/*.sql")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Путь к файлу SQLite (default: dep_report.db в корне проекта)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="DROP все пользовательские таблицы и пересоздать схему",
    )
    args = parser.parse_args()

    db_path = init_database(args.db, force=args.force)
    print(f"База данных (database): {db_path.resolve()}")

    conn = open_db(db_path)
    try:
        if args.force:
            applied = apply_schema(conn, force=False)
        else:
            applied = sorted((_ROOT / "schema").glob("*.sql"))
            applied = [p.name for p in applied]
        print("Применены DDL:", ", ".join(applied) if applied else "(нет файлов)")
        for table in list_user_tables(conn):
            count = table_row_count(conn, table)
            print(f"  {table}: {count} строк")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
