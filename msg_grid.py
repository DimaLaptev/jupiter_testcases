"""Парсинг .MSG как semicolon-separated grid (аналог VBA TextToColumns)."""

from __future__ import annotations

from pathlib import Path

from gpb_d_msg import read_text_with_encoding
from gpb_i_msg import _split_row


def msg_path_to_rows(path: Path) -> list[list[str]]:
    """Каждая строка файла → список полей после split(';')."""
    text = read_text_with_encoding(path)
    out: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip() and not line:
            out.append([""])
            continue
        out.append(_split_row(line) if line.strip() else [""])
    return out


def sheet_a8_empty(rows: list[list[str]]) -> bool:
    """ГПБ: A8 пуста."""
    return cell_at(rows, 8, 1) == ""


def sheet_a7_empty(rows: list[list[str]]) -> bool:
    """РСД: A7 пуста."""
    return cell_at(rows, 7, 1) == ""


def cell_at(rows: list[list[str]], row_1based: int, col_1based: int) -> str:
    r = row_1based - 1
    c = col_1based - 1
    if r < 0 or r >= len(rows):
        return ""
    row = rows[r]
    if c < 0 or c >= len(row):
        return ""
    return row[c]


def last_row_in_column(rows: list[list[str]], col_1based: int) -> int:
    c = col_1based - 1
    last = 0
    for r_idx, row in enumerate(rows):
        if c < len(row) and (row[c] or "").strip():
            last = r_idx + 1
    return last
