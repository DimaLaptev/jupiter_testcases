"""Общие утилиты для работы с Excel и ИНН."""

from __future__ import annotations

import re
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

INN_HEADER = "ИНН"


def normalize_inn(value: Any) -> str:
    """Нормализовать ИНН: только цифры."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return re.sub(r"\D", "", text)


def read_header_map(ws: Worksheet) -> dict[str, int]:
    """Карта заголовок → номер колонки (1-based)."""
    headers: dict[str, int] = {}
    for col in range(1, ws.max_column + 1):
        cell_value = ws.cell(1, col).value
        if cell_value is None:
            continue
        headers[str(cell_value).strip()] = col
    return headers


def ensure_column(ws: Worksheet, header: str, headers: dict[str, int] | None = None) -> int:
    """Вернуть индекс колонки; создать заголовок справа, если нет."""
    if headers is None:
        headers = read_header_map(ws)
    if header in headers:
        return headers[header]
    col = max(headers.values(), default=0) + 1
    ws.cell(1, col).value = header
    headers[header] = col
    return col


def require_inn_column(ws: Worksheet) -> tuple[int, dict[str, int]]:
    """Найти колонку ИНН или выбросить ValueError."""
    headers = read_header_map(ws)
    if INN_HEADER not in headers:
        raise ValueError(
            f"В первой строке нет колонки «{INN_HEADER}». "
            f"Найдены: {', '.join(headers) or '(пусто)'}"
        )
    return headers[INN_HEADER], headers


def collect_inn_rows(ws: Worksheet, inn_col: int) -> list[tuple[int, str]]:
    """Список (номер_строки, инн) без пустых ИНН."""
    rows: list[tuple[int, str]] = []
    for row in range(2, ws.max_row + 1):
        inn = normalize_inn(ws.cell(row, inn_col).value)
        if not inn:
            continue
        rows.append((row, inn))
    return rows
