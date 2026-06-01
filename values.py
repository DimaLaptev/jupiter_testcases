"""Маппинг ячеек Excel/MSG → значения для INSERT (NULL = пусто)."""

from __future__ import annotations

from typing import Any


def cell_to_sql_value(raw: Any, *, quoteless_last: bool = False) -> str | None:
    """
    Эквивалент VBA IsEmpty / IsError → DEFAULT; в Python → None.
    quoteless_last: для region v1 последняя колонка без кавычек в VBA — значение как есть.
    """
    if raw is None:
        return None
    if isinstance(raw, float):
        if raw != raw:  # NaN
            return None
        if raw == int(raw):
            s = str(int(raw))
        else:
            s = str(raw).strip()
    else:
        s = str(raw).strip()
    if s == "":
        return None
    if quoteless_last:
        return s
    return s


def row_from_cells(
    cells: list[Any],
    *,
    quoteless_last: bool = False,
) -> tuple[str | None, ...]:
    if not cells:
        return tuple()
    out: list[str | None] = []
    last_idx = len(cells) - 1
    for i, cell in enumerate(cells):
        out.append(
            cell_to_sql_value(cell, quoteless_last=quoteless_last and i == last_idx),
        )
    return tuple(out)
