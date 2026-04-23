"""
ПШЕ (FTE) за ноябрь/декабрь 2025 (норма: workDayMonth_2 * 8 ч) + нагрузка (workload) из calc_resist_10.

Загрузка — как в export_resist_fte_period.load_model39_like_notebook28;
нагрузка — строка C10 (resist_10), см. memory/excel_workload_model.md, HANDOFF.md.

Запуск из корня репозитория:
  python scripts/export_resist_phe_workload_2025.py -o out/phe_workload_2025.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from export_resist_fte_period import coerce_numeric_series, load_model39_like_notebook28
from export_resist_operation_facts import default_raw_files

YEAR = 2025
MONTH_NOV = 11
MONTH_DEC = 12
MONTH_OCT = 10

# Колонка нагрузки (workload) в развёрнутом calculate_parameter (resist_10)
WORKLOAD_COL = "calc_resist_10"

SUMMARY_SHEET = "Сводка"

# Заливка (fill) openpyxl — светлые тона, читаемый текст
FILL_GREEN = "C6EFCE"
FILL_GRAY = "D9D9D9"
FILL_RED = "FFC7CE"


def _workload_to_pct_for_rules(value) -> float | None:
    """Приведение к % (percent) для порогов 80/90/110/120."""
    if pd.isna(value):
        return None
    x = float(value)
    if x <= 1.5:
        return x * 100.0
    return x


def _workload_display(value) -> float | None:
    """Отображаемая нагрузка (как %)."""
    return _workload_to_pct_for_rules(value)


def _fill_color_for_pct(p: float) -> str:
    if p < 80 or p > 120:
        return FILL_RED
    if (80 <= p < 90) or (110 < p <= 120):
        return FILL_GRAY
    if 90 <= p <= 110:
        return FILL_GREEN
    return FILL_GRAY


def add_phe_wd8(df: pd.DataFrame) -> pd.DataFrame:
    """ПШЕ: coefficient = calculate_minute / 60 / (workDayMonth_2 * 8), без 148.3."""
    out = df.copy()
    wm = out["workDayMonth_2"] * 8.0
    valid = out["workDayMonth_2"].notna() & (out["workDayMonth_2"] > 0) & out["calculate_minute"].notna()
    coef = out["calculate_minute"] / 60.0 / wm
    out["fact_fts"] = np.where(valid, out["fact_value"] * coef, np.nan)
    return out


def aggregate_phe_nov_dec(df: pd.DataFrame) -> pd.DataFrame:
    """Сумма ПШЕ по resist_id: ноя, дек, ноя+дек (год 2025)."""
    d = df[(df["year"] == YEAR) & (df["month"].isin([MONTH_NOV, MONTH_DEC]))].copy()
    if d.empty:
        return pd.DataFrame(
            columns=["resist_id", "ПШЕ ноя 2025", "ПШЕ дек 2025", "ПШЕ ноя+дек 2025"]
        )
    s_nov = d[d["month"] == MONTH_NOV].groupby("resist_id", sort=True)["fact_fts"].sum()
    s_dec = d[d["month"] == MONTH_DEC].groupby("resist_id", sort=True)["fact_fts"].sum()
    all_ids = sorted(set(s_nov.index) | set(s_dec.index))
    out = pd.DataFrame({"resist_id": all_ids})
    a = out["resist_id"].map(s_nov)
    b = out["resist_id"].map(s_dec)
    out["ПШЕ ноя 2025"] = a
    out["ПШЕ дек 2025"] = b
    out["ПШЕ ноя+дек 2025"] = [
        (np.nan if (pd.isna(x) and pd.isna(y)) else (0.0 if pd.isna(x) else x) + (0.0 if pd.isna(y) else y))
        for x, y in zip(a, b)
    ]
    for c in ("ПШЕ ноя 2025", "ПШЕ дек 2025", "ПШЕ ноя+дек 2025"):
        out[c] = pd.to_numeric(out[c], errors="coerce").round(2)
    return out


def monthly_workload_table(df: pd.DataFrame) -> pd.DataFrame:
    """Одна строка (resist_id, year, month) — resist_10."""
    if df.empty or WORKLOAD_COL not in df.columns:
        return pd.DataFrame(
            columns=["resist_id", "year", "month", WORKLOAD_COL]
        )
    g = (
        df.groupby(["resist_id", "year", "month"], sort=True, dropna=True)[WORKLOAD_COL]
        .first()
        .reset_index()
    )
    return g


def build_workload_summary(wm: pd.DataFrame) -> pd.DataFrame:
    """
    Пивот (pivot) окт/ноя/дек 2025, средняя окт–дек, средняя за 2025 (по месяцам с notna).
    """
    if wm.empty:
        return pd.DataFrame(
            columns=[
                "resist_id",
                "Нагрузка, % окт 2025",
                "Нагрузка, % ноя 2025",
                "Нагрузка, % дек 2025",
                "Средняя нагрузка, окт–дек 2025",
                "Средняя нагрузка, 2025",
            ]
        )
    w25 = wm[wm["year"] == YEAR].copy()
    # Помесячные value для 2025
    def mval(month: int) -> dict:
        sub = w25[w25["month"] == month]
        m = sub.set_index("resist_id")[WORKLOAD_COL]
        return m

    o = mval(MONTH_OCT)
    n = mval(MONTH_NOV)
    d_ = mval(MONTH_DEC)
    rids = sorted(
        set(w25["resist_id"].dropna().astype(int).unique().tolist()) if not w25.empty else []
    )
    rows = []
    for rid in rids:
        v_o = o.get(rid, np.nan)
        v_n = n.get(rid, np.nan)
        v_d = d_.get(rid, np.nan)
        m3 = pd.Series([v_o, v_n, v_d])
        m_oct_dec = m3.dropna()
        q4 = float(m_oct_dec.mean()) if not m_oct_dec.empty else np.nan
        wyr = w25[w25["resist_id"] == rid][WORKLOAD_COL].dropna()
        ymean = float(wyr.mean()) if not wyr.empty else np.nan
        rows.append(
            {
                "resist_id": rid,
                "Нагрузка, % окт 2025": _workload_display(v_o),
                "Нагрузка, % ноя 2025": _workload_display(v_n),
                "Нагрузка, % дек 2025": _workload_display(v_d),
                "Средняя нагрузка, окт–дек 2025": _workload_display(q4) if not pd.isna(q4) else np.nan,
                "Средняя нагрузка, 2025": _workload_display(ymean) if not pd.isna(ymean) else np.nan,
            }
        )
    out = pd.DataFrame(rows)
    for c in out.columns:
        if c != "resist_id":
            out[c] = pd.to_numeric(out[c], errors="coerce").round(2)
    return out.sort_values("resist_id").reset_index(drop=True)


def merge_summary(
    phe: pd.DataFrame,
    wld: pd.DataFrame,
) -> pd.DataFrame:
    want = [
        "resist_id",
        "ПШЕ ноя 2025",
        "ПШЕ дек 2025",
        "ПШЕ ноя+дек 2025",
        "Нагрузка, % окт 2025",
        "Нагрузка, % ноя 2025",
        "Нагрузка, % дек 2025",
        "Средняя нагрузка, окт–дек 2025",
        "Средняя нагрузка, 2025",
    ]
    if phe.empty and wld.empty:
        return pd.DataFrame(columns=want)
    merged = pd.merge(
        phe,
        wld,
        on="resist_id",
        how="outer",
    ).sort_values("resist_id", kind="mergesort")
    for c in want:
        if c not in merged.columns:
            merged[c] = np.nan
    return merged[want]


def apply_workload_fills(
    xlsx_path: Path,
    sheet_name: str,
    workload_col_names: list[str],
) -> None:
    from openpyxl import load_workbook
    from openpyxl.styles import PatternFill

    wb = load_workbook(xlsx_path)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return
    ws = wb[sheet_name]
    header = {str(ws.cell(1, c).value): c for c in range(1, ws.max_column + 1)}

    col_indices: list[tuple[str, int]] = []
    for name in workload_col_names:
        if name in header:
            col_indices.append((name, header[name]))

    for r in range(2, ws.max_row + 1):
        for name, cidx in col_indices:
            cell = ws.cell(r, cidx)
            val = cell.value
            p = _workload_to_pct_for_rules(val)
            if p is None:
                continue
            color = _fill_color_for_pct(p)
            cell.fill = PatternFill(fill_type="solid", start_color=color, end_color=color)
    wb.save(xlsx_path)
    wb.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ПШЕ (норма workDayMonth_2*8) ноя+дек 2025 + нагрузка calc_resist_10, Excel (Excel) с заливкой."
    )
    p.add_argument("-o", "--output", type=Path, required=True, help="Выходной .xlsx (openpyxl).")
    p.add_argument(
        "--raw",
        type=Path,
        nargs="*",
        default=None,
        help="CSV; по умолчанию data/raw/data-2022…2025.",
    )
    p.add_argument(
        "--resist-ids",
        type=int,
        nargs="*",
        default=None,
        help="Ограничить resist_id.",
    )
    p.add_argument(
        "--include-excluded",
        action="store_true",
        help="Не исключать EXCLUDED_RESIST_IDS (как в export_resist_fte_period).",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("Для записи Excel установите openpyxl: pip install openpyxl", file=sys.stderr)
        return 1

    raw_paths = list(args.raw) if args.raw else default_raw_files()
    try:
        df_model39 = load_model39_like_notebook28(
            raw_paths,
            include_excluded=args.include_excluded,
        )
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    if df_model39.empty:
        print("После загрузки датафрейм пуст.", file=sys.stderr)
        return 1

    if WORKLOAD_COL not in df_model39.columns:
        print(
            f"В данных нет колонки {WORKLOAD_COL!r} (resist_10 в JSON).",
            file=sys.stderr,
        )

    if args.resist_ids:
        want = set(args.resist_ids)
        df_model39 = df_model39[df_model39["resist_id"].isin(want)].copy()
        if df_model39.empty:
            print("После фильтра resist_id таблица пуста.", file=sys.stderr)
            return 1

    df_model39 = add_phe_wd8(df_model39)
    phe = aggregate_phe_nov_dec(df_model39)
    wm = monthly_workload_table(df_model39)
    wld = build_workload_summary(wm)
    summary = merge_summary(phe, wld)
    if summary.empty and not args.resist_ids:
        print("Сводка пуста (нет пересечения показателей).", file=sys.stderr)

    workload_display_cols = [
        "Нагрузка, % окт 2025",
        "Нагрузка, % ноя 2025",
        "Нагрузка, % дек 2025",
        "Средняя нагрузка, окт–дек 2025",
        "Средняя нагрузка, 2025",
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name=SUMMARY_SHEET, index=False)

    apply_workload_fills(
        args.output,
        SUMMARY_SHEET,
        workload_display_cols,
    )

    n_w = (WORKLOAD_COL in df_model39.columns) and df_model39[WORKLOAD_COL].notna().any()
    if not n_w:
        print(
            "Предупреждение: нет непустых значений нагрузки; колонки нагрузки пусты.",
            file=sys.stderr,
        )
    print(
        f"Записано: {args.output} (лист «{SUMMARY_SHEET}»: {len(summary)} строк; "
        f"норма ПШЕ = workDayMonth_2*8ч)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
