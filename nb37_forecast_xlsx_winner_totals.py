# -*- coding: utf-8 -*-
"""Сводка глобальных «побед» по листам ``{resist_id} По операциям`` книги Excel от nb37.

Суммирует по всем таким листам колонку «Победившая Конфигурация» (одна строка = один
``operation_id`` на ``resist_id``) и записывает таблицу **последним листом** книги.

Запуск из корня репозитория:
  python scripts/nb37_forecast_xlsx_winner_totals.py
  python scripts/nb37_forecast_xlsx_winner_totals.py data/processed/37_forecast_test_fix.xlsx
  python scripts/nb37_forecast_xlsx_winner_totals.py --xlsx data/processed/37_forecast_test_fix.xlsx
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd
from openpyxl import load_workbook

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from scripts.nb37_forecast_xlsx_underperform_sheet import (  # noqa: E402
    DEFAULT_XLSX,
    WINNER_COL,
    parse_rid_from_sheet_name,
    series_configs_allowed_in_forecast_script,
)

COL_CONFIG_NAME = "название конфига"
COL_WIN_COUNT = "количество побед в operation_id"
DEFAULT_SUMMARY_SHEET = "Сводка побед operation_id"


def _resolve_winner_column(df: pd.DataFrame) -> Optional[str]:
    """Имя колонки победителя: точное совпадение с ``WINNER_COL`` или без учёта регистра."""
    if WINNER_COL in df.columns:
        return WINNER_COL
    target = WINNER_COL.casefold()
    for c in df.columns:
        if str(c).strip().casefold() == target:
            return str(c)
    return None


def _nonempty_winner_rows_on_sheet(df: pd.DataFrame, col: str) -> int:
    s = df[col]
    s = s.dropna()
    s = s.astype(str).str.strip()
    s = s[s != ""]
    return int(s.shape[0])


def build_winner_totals_dataframe(xlsx: Path) -> pd.DataFrame:
    """Глобальные счётчики: сумма по всем листам ``* По операциям``."""
    xlsx = xlsx.resolve()
    xl = pd.ExcelFile(xlsx, engine="openpyxl")
    total: dict[str, int] = {}
    foreign: list[str] = []
    universe = set(series_configs_allowed_in_forecast_script().keys())

    for sn in xl.sheet_names:
        if parse_rid_from_sheet_name(sn) is None:
            continue
        df = pd.read_excel(xlsx, sheet_name=sn, engine="openpyxl")
        col = _resolve_winner_column(df)
        if col is None:
            warnings.warn(
                f"Лист «{sn}»: нет колонки «{WINNER_COL}» (в т.ч. с другим регистром), пропуск.",
                stacklevel=2,
            )
            continue
        s = df[col].dropna()
        s = s.astype(str).str.strip()
        s = s[s != ""]
        for name in s:
            total[name] = total.get(name, 0) + 1
            if name not in universe:
                foreign.append(name)

    foreign_unique = sorted(set(foreign))
    if foreign_unique:
        warnings.warn(
            "В колонке победителя встретились имена вне allowed-universe "
            f"(возможна опечатка или старый прогон): {foreign_unique[:30]}"
            + (" …" if len(foreign_unique) > 30 else ""),
            stacklevel=2,
        )

    rows = sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))
    out = pd.DataFrame(rows, columns=[COL_CONFIG_NAME, COL_WIN_COUNT])
    return out


def count_nonempty_winners_all_op_sheets(xlsx: Path) -> int:
    """Число непустых значений победителя по всем листам ``* По операциям`` (для проверки)."""
    xlsx = xlsx.resolve()
    xl = pd.ExcelFile(xlsx, engine="openpyxl")
    n = 0
    for sn in xl.sheet_names:
        if parse_rid_from_sheet_name(sn) is None:
            continue
        df = pd.read_excel(xlsx, sheet_name=sn, engine="openpyxl")
        col = _resolve_winner_column(df)
        if col is None:
            continue
        n += _nonempty_winner_rows_on_sheet(df, col)
    return n


def validate_winner_totals_against_sheets(xlsx: Path, df: pd.DataFrame) -> bool:
    """``True``, если сумма сводки совпадает с числом непустых победителей по листам."""
    if df.empty:
        expected = count_nonempty_winners_all_op_sheets(xlsx)
        return expected == 0
    got = int(df[COL_WIN_COUNT].sum())
    expected = count_nonempty_winners_all_op_sheets(xlsx)
    return got == expected


def append_winner_totals_sheet(
    xlsx: Path,
    *,
    sheet_name: str = DEFAULT_SUMMARY_SHEET,
    df: Optional[pd.DataFrame] = None,
) -> None:
    """Удаляет лист ``sheet_name`` при повторном запуске; создаёт его снова в конце книги."""
    xlsx = xlsx.resolve()
    if df is None:
        df = build_winner_totals_dataframe(xlsx)

    wb = load_workbook(xlsx)
    if sheet_name in wb.sheetnames:
        wb.remove(wb[sheet_name])
    ws = wb.create_sheet(sheet_name, len(wb.sheetnames))

    ws.cell(row=1, column=1, value=COL_CONFIG_NAME)
    ws.cell(row=1, column=2, value=COL_WIN_COUNT)
    for i, row in enumerate(df.itertuples(index=False), start=2):
        ws.cell(row=i, column=1, value=row[0])
        ws.cell(row=i, column=2, value=int(row[1]))

    wb.save(xlsx)
    wb.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Добавляет последний лист со сводкой: сколько раз каждая конфигурация «победила» "
            "в колонке «Победившая Конфигурация» на всех листах «… По операциям»."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "xlsx_positional",
        nargs="?",
        type=Path,
        default=None,
        metavar="BOOK.xlsx",
        help="путь к Excel (positional); если не задан — --xlsx или путь по умолчанию",
    )
    p.add_argument(
        "--xlsx",
        dest="xlsx_flag",
        type=Path,
        default=None,
        help=f"путь к Excel (по умолчанию без аргументов: {DEFAULT_XLSX})",
    )
    p.add_argument(
        "--sheet-name",
        type=str,
        default=DEFAULT_SUMMARY_SHEET,
        metavar="NAME",
        help=f"имя листа сводки (по умолчанию: {DEFAULT_SUMMARY_SHEET!r})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="только посчитать и вывести в stdout, файл не менять",
    )
    p.add_argument(
        "--validate",
        action="store_true",
        help="проверить: сумма «{количество побед}» == число непустых победителей на всех листах",
    )
    args = p.parse_args(argv)

    book = args.xlsx_positional or args.xlsx_flag or DEFAULT_XLSX
    xlsx = book.resolve()
    if not xlsx.exists():
        print(f"Файл не найден: {xlsx}", file=sys.stderr)
        return 1

    df = build_winner_totals_dataframe(xlsx)
    if args.validate:
        ok = validate_winner_totals_against_sheets(xlsx, df)
        exp = count_nonempty_winners_all_op_sheets(xlsx)
        got_sum = int(df[COL_WIN_COUNT].sum()) if not df.empty else 0
        print(f"Проверка: сумма сводки={got_sum}, непустых победителей по листам={exp} → {'OK' if ok else 'FAIL'}")
        if not ok:
            return 2

    if args.dry_run:
        print(df.to_string(index=False))
        print(f"Строк в сводке: {len(df)}")
        return 0

    append_winner_totals_sheet(xlsx, sheet_name=args.sheet_name, df=df)
    print(f"Готово: лист «{args.sheet_name}» в конец файла {xlsx}")
    print(f"  Строк в сводке: {len(df)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
