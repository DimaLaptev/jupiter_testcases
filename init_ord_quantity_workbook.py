#!/usr/bin/env python3
"""Создание книги Excel с шаблоном листа «Количество поручений» (и опционально «СВОД_операций»)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ord_quantity_excel import (
    create_workbook_svod_and_ord_templates,
    create_workbook_with_ord_quantity_template,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "2026_01" / "2026_01_Ord_Quantity.xlsx",
        help="Путь к создаваемой книге (workbook)",
    )
    p.add_argument(
        "--layout",
        type=Path,
        default=None,
        help="Путь к Ord_Quantity_headers.json (по умолчанию memory/Ord_Quantity_headers.json)",
    )
    p.add_argument(
        "--ord-only",
        action="store_true",
        help="Только лист «Количество поручений», без «СВОД_операций»",
    )
    args = p.parse_args()
    layout = None
    if args.layout:
        import json

        layout = json.load(args.layout.open(encoding="utf-8"))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.ord_only:
        create_workbook_with_ord_quantity_template(args.out, layout)
    else:
        create_workbook_svod_and_ord_templates(args.out, layout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
