#!/usr/bin/env python3
"""Заполнение листа «Количество поручений» агрегацией (aggregation) из «СВОД_операций»."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ord_quantity_excel import fill_ord_quantity_from_workbook, ensure_ord_quantity_sheet, load_headers_layout
from openpyxl import load_workbook


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--workbook",
        type=Path,
        default=_ROOT / "2026_01" / "2026_01_Ord_Quantity.xlsx",
        help="Путь к 2026_01_Ord_Quantity.xlsx",
    )
    p.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Год отчётного периода (reporting year)",
    )
    p.add_argument(
        "--month",
        type=int,
        default=1,
        help="Месяц отчётного периода (1–12)",
    )
    p.add_argument(
        "--layout",
        type=Path,
        default=None,
        help="Путь к Ord_Quantity_headers.json",
    )
    p.add_argument(
        "--ensure-sheet",
        action="store_true",
        help="Создать/обновить шапку листа «Количество поручений», если лист пустой или без merge",
    )
    args = p.parse_args()

    if not args.workbook.is_file():
        print(f"Файл не найден: {args.workbook}", file=sys.stderr)
        return 1

    layout = None
    layout_path = args.layout
    if layout_path:
        layout = json.load(layout_path.open(encoding="utf-8"))

    if args.ensure_sheet:
        wb = load_workbook(args.workbook)
        ensure_ord_quantity_sheet(wb, layout or load_headers_layout())
        wb.save(args.workbook)

    n = fill_ord_quantity_from_workbook(
        args.workbook,
        args.year,
        args.month,
        layout_path=layout_path,
    )
    print(f"Строк матрицы (matrix rows): {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
