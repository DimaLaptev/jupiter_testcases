"""Реестр колонок staging-таблиц (соответствует schema/*.sql)."""

from __future__ import annotations

TABLE_COLUMNS: dict[str, list[str]] = {
    "gpb_temp": [f"col_{i:02d}" for i in range(1, 10)],
    "region_temp": [f"col_{i:02d}" for i in range(1, 41)],
    "region2_temp": [
        "depo_account",
        "division_name",
        "quantity",
        "agreement_number",
        "registration_number",
    ],
    "vtb_temp": ["schet"] + [f"col_{i:02d}" for i in range(1, 13)],
    "rsd_temp": [f"col_{i:02d}" for i in range(1, 7)],
    "rsd_dop_temp": ["schet"] + [f"col_{i:02d}" for i in range(2, 11)],
}

TEMP_TABLES = tuple(TABLE_COLUMNS.keys())

VBA_TABLE_MAP: dict[str, str] = {
    "gpb": "gpb_temp",
    "region": "region_temp",
    "region2": "region2_temp",
    "vtb": "vtb_temp",
    "rsd": "rsd_temp",
    "rsd_dop": "rsd_dop_temp",
}


def columns_for(table: str) -> list[str]:
    if table not in TABLE_COLUMNS:
        raise KeyError(f"Неизвестная таблица: {table}")
    return list(TABLE_COLUMNS[table])


def assert_row_width(table: str, row: tuple) -> None:
    expected = len(TABLE_COLUMNS[table])
    if len(row) != expected:
        raise ValueError(
            f"Таблица {table}: ожидалось {expected} полей, получено {len(row)}",
        )
