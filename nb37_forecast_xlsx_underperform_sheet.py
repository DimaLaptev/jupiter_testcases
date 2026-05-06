# -*- coding: utf-8 -*-
"""Дописывает в книгу Excel от nb37 лист со списками конфигураций, которые ни на одном
``resist_id`` не попали в топ-1 и в топ-3 по числу побед на ``operation_id``
(агрегат колонки «Победившая Конфигурация» на листах ``{rid} По операциям``).

Если книга собрана с флагом ``--config`` (одна модель), в «По операциям» везде одно имя —
списки тривиальны; для осмысленного комбайна нужен полный nb37-прогон.

Запуск из корня репозитория:
  python scripts/nb37_forecast_xlsx_underperform_sheet.py
  python scripts/nb37_forecast_xlsx_underperform_sheet.py --xlsx data/processed/37_forecast_test_fix.xlsx
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
import pandas as pd
from openpyxl import load_workbook

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from scripts.tsa_per_series_nb37_trainers import SERIES_CONFIGS  # noqa: E402

# Синхронно с ``DISABLED_FN_FOR_SCRIPT`` в ``scripts/37_forecast_test_fix.py``.
DISABLED_FN_FOR_SCRIPT: frozenset[str] = frozenset({"prophet", "tbats", "zip", "greykite"})

SHEET_SUFFIX = " По операциям"
WINNER_COL = "Победившая Конфигурация"
OUT_SHEET_NAME = "Ни топ1 ни топ3"
DEFAULT_XLSX = _ROOT / "data" / "processed" / "37_forecast_test_fix.xlsx"


def series_configs_allowed_in_forecast_script() -> dict[str, dict]:
    return {
        name: cfg
        for name, cfg in SERIES_CONFIGS.items()
        if cfg.get("fn") not in DISABLED_FN_FOR_SCRIPT
    }


def parse_rid_from_sheet_name(name: str) -> int | None:
    """``124 По операциям`` → ``124``; иначе ``None``."""
    if not name.endswith(SHEET_SUFFIX):
        return None
    prefix = name[: -len(SHEET_SUFFIX)].strip()
    if not prefix:
        return None
    try:
        return int(prefix)
    except ValueError:
        return None


def top1_and_top3_sets(counts: dict[str, int]) -> tuple[set[str], set[str]]:
    """По словарю config→wins: множества имён в топ-1 и в топ-3 (три лучших уровня wins)."""
    if not counts:
        return set(), set()
    distinct = sorted(set(counts.values()), reverse=True)
    max_w = distinct[0]
    top1 = {c for c, w in counts.items() if w == max_w}
    top3_thresholds = set(distinct[: min(3, len(distinct))])
    top3 = {c for c, w in counts.items() if w in top3_thresholds}
    return top1, top3


def sheet_op_winner_counts(
    xlsx: Path, sheet_name: str
) -> tuple[dict[str, int], list[str]]:
    """Число строк на имя в ``Победившая Конфигурация``; предупреждения для «левых» имён."""
    df = pd.read_excel(xlsx, sheet_name=sheet_name, engine="openpyxl")
    if WINNER_COL not in df.columns:
        warnings.warn(f"Лист «{sheet_name}»: нет колонки «{WINNER_COL}», пропуск.")
        return {}, []
    s = df[WINNER_COL]
    s = s.dropna()
    s = s.astype(str).str.strip()
    s = s[s != ""]
    unknown: list[str] = []
    counts: dict[str, int] = {}
    universe = set(series_configs_allowed_in_forecast_script().keys())
    for name in s:
        counts[name] = counts.get(name, 0) + 1
        if name not in universe:
            unknown.append(name)
    return counts, unknown


def collect_top_labels(xlsx: Path) -> tuple[set[str], set[str], list[str]]:
    """``(ever_top1, ever_top3, foreign_names)`` по всем листам ``* По операциям``."""
    xl = pd.ExcelFile(xlsx, engine="openpyxl")
    ever1: set[str] = set()
    ever3: set[str] = set()
    foreign: list[str] = []
    for sn in xl.sheet_names:
        rid = parse_rid_from_sheet_name(sn)
        if rid is None:
            continue
        counts, unk = sheet_op_winner_counts(xlsx, sn)
        foreign.extend(unk)
        t1, t3 = top1_and_top3_sets(counts)
        ever1 |= t1
        ever3 |= t3
    return ever1, ever3, foreign


def write_summary_sheet(xlsx: Path, never1: list[str], never3: list[str]) -> None:
    wb = load_workbook(xlsx)
    if OUT_SHEET_NAME in wb.sheetnames:
        ws_old = wb[OUT_SHEET_NAME]
        wb.remove(ws_old)
    ws = wb.create_sheet(OUT_SHEET_NAME, len(wb.sheetnames))

    ws["A1"] = "Ни разу топ-1 ни на одном resist_id"
    ws["C1"] = "Ни разу в топ-3 ни на одном resist_id"
    for i, name in enumerate(never1, start=2):
        ws.cell(row=i, column=1, value=name)
    for i, name in enumerate(never3, start=2):
        ws.cell(row=i, column=3, value=name)

    wb.save(xlsx)
    wb.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Добавляет лист с конфигами, ни разу не попавшими в топ-1 / топ-3 по resist_id "
            "(по победам на operation_id на листах «… По операциям»)."
        )
    )
    p.add_argument(
        "--xlsx",
        type=Path,
        default=DEFAULT_XLSX,
        help=f"Excel-файл (по умолчанию {DEFAULT_XLSX})",
    )
    args = p.parse_args(argv)

    xlsx = args.xlsx.resolve()
    if not xlsx.exists():
        print(f"Файл не найден: {xlsx}", file=sys.stderr)
        return 1

    allowed = series_configs_allowed_in_forecast_script()
    universe = sorted(allowed.keys())
    universe_set = set(universe)

    ever1, ever3, foreign = collect_top_labels(xlsx)
    foreign_unique = sorted(set(foreign))
    if foreign_unique:
        print(
            "Предупреждение: в «Победившая Конфигурация» встретились имена вне allowed-universe "
            f"(возможна опечатка или старый прогон): {foreign_unique[:20]}"
            + (" …" if len(foreign_unique) > 20 else ""),
            file=sys.stderr,
        )

    never1_sorted = sorted(universe_set - ever1)
    never3_sorted = sorted(universe_set - ever3)

    write_summary_sheet(xlsx, never1_sorted, never3_sorted)
    print(f"Готово: лист «{OUT_SHEET_NAME}» в конец файла {xlsx}")
    print(f"  Ни разу топ-1: {len(never1_sorted)} из {len(universe)}")
    print(f"  Ни разу топ-3: {len(never3_sorted)} из {len(universe)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
