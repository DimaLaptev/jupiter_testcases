"""Чтение СВОД_поДЕПО / СВОД_поДЕПО_ДОМ для Day_Quantity."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.excel_grid import cell_at, read_workbook_sheets

from models import SVOD_COL_ALIASES, SvodDepoRow

_SKIP_SHEETS = frozenset({"валидация", "дубли", "ошибки"})
_FALLBACK_HEADER_ROW = 5
_FALLBACK_DATA_START = 6


def _norm_header(value: object | None) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip().casefold()


def _find_header_map(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    """Найти строку шапки и map логических полей → 1-based col."""
    scan_limit = min(len(rows), 30)
    for r in range(1, scan_limit + 1):
        headers_by_col: dict[str, int] = {}
        row = rows[r - 1] if r - 1 < len(rows) else []
        for c, raw in enumerate(row, start=1):
            h = _norm_header(raw)
            if h:
                headers_by_col[h] = c
        if not headers_by_col:
            continue
        field_map: dict[str, int] = {}
        for field, aliases in SVOD_COL_ALIASES.items():
            for alias in aliases:
                col = headers_by_col.get(_norm_header(alias))
                if col:
                    field_map[field] = col
                    break
        if "ngri" in field_map and "schet_depo" in field_map:
            return r, field_map
    # Fallback: фиксированная раскладка СВОД (A=портфель, E=счёт, F=раздел, K=НГРИ, M=ENC)
    if len(rows) >= _FALLBACK_HEADER_ROW:
        return _FALLBACK_HEADER_ROW, {
            "n_zakladnoy": 1,
            "schet_depo": 5,
            "razdel_scheta": 6,
            "ngri": 11,
            "enc": 13,
        }
    return None


def _cell(rows: list[list[str]], r: int, col: int | None) -> str:
    if not col:
        return ""
    return (cell_at(rows, r, col) or "").strip()


def iter_svod_depo_rows(
    path: Path,
    *,
    warn: TextIO | None = None,
) -> list[SvodDepoRow]:
    """Прочитать все листы портфеля СВОД_поДЕПО (кроме служебных)."""
    out: TextIO = warn or sys.stdout
    if not path.is_file():
        print(f"WARN: СВОД не найден: {path}", file=out)
        return []

    result: list[SvodDepoRow] = []
    for sheet_name, rows in read_workbook_sheets(path):
        if _norm_header(sheet_name) in _SKIP_SHEETS:
            continue
        found = _find_header_map(rows)
        if not found:
            print(f"WARN: нет шапки СВОД на листе {sheet_name!r} в {path.name}", file=out)
            continue
        header_row, fmap = found
        data_start = header_row + 1
        # Если нашли fallback-шапку на строке 5 — данные с 6
        if header_row == _FALLBACK_HEADER_ROW and "ngri" in fmap and fmap["ngri"] == 11:
            data_start = _FALLBACK_DATA_START

        for r in range(data_start, len(rows) + 1):
            ngri = _cell(rows, r, fmap.get("ngri"))
            schet = _cell(rows, r, fmap.get("schet_depo"))
            if not ngri and not schet:
                continue
            if not ngri:
                continue
            result.append(
                SvodDepoRow(
                    ngri=ngri,
                    n_zakladnoy=_cell(rows, r, fmap.get("n_zakladnoy")) or None,
                    enc=_cell(rows, r, fmap.get("enc")) or None,
                    schet_depo=schet,
                    razdel_scheta=_cell(rows, r, fmap.get("razdel_scheta")),
                    sheet_name=sheet_name,
                    source_file=path.name,
                ),
            )
    return result
