"""
Сумма ПШЕ (FTE, fact_fts) по resist_id за выбранный период из сырых CSV.

Загрузка и фильтры — как в notebooks/28_comparison_per_series_trimmed_extras_artem_preprocess.ipynb
(ячейка с calc_flat и coerce_numeric_series). Расчёт ПШЕ — как в build_dataframe_for_dashboard.add_derived_columns:
coefficient_fulltime_staff = calculate_minute / 60 / 148.3; fact_fts = fact_value * coefficient_fulltime_staff.

Запуск из корня репозитория:
  python scripts/export_resist_fte_period.py -o out/phe_2025_h2.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from export_resist_operation_facts import (
    EXCLUDED_RESIST_IDS,
    PREDICT_COMMENT,
    default_raw_files,
)

# Норма часов в месяц (как в проекте) для перевода calculate_minute в коэффициент штатной единицы (FTE).
NORM_HOURS_PER_MONTH = 148.3

SUMMARY_SHEET = "Сводка"
DETAIL_SHEET = "Сверка"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "t", "1"])


def to_bool_value(value):
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return None
    return str(value).strip().lower() in ["true", "t", "1"]


def parse_calculate_param(calc_json: str):
    if pd.isna(calc_json):
        return {}
    try:
        return json.loads(calc_json)
    except Exception:
        return {}


def flatten_calc_to_dict(calc_obj: dict, prefix: str = "calc_") -> dict:
    out = {}
    for k, v in (calc_obj or {}).items():
        col = f"{prefix}{k}"
        if isinstance(v, dict):
            if "value" in v:
                out[col] = v.get("value")
            else:
                out[col] = json.dumps(v, ensure_ascii=False) if v else ""
        else:
            out[col] = v
    return out


def coerce_numeric_series(series: pd.Series) -> pd.Series:
    """pd.to_numeric (to_numeric) + повтор для строк с десятичной запятой (decimal comma), напр. \"8,5\"."""
    out = pd.to_numeric(series, errors="coerce")
    mask = out.isna() & series.notna()
    if mask.any():
        fixed = (
            series[mask]
            .astype(str)
            .str.strip()
            .str.replace(",", ".", regex=False)
        )
        out.loc[mask] = pd.to_numeric(fixed, errors="coerce")
    return out


def load_model39_like_notebook28(
    raw_paths: list[Path],
    *,
    include_excluded: bool = False,
) -> pd.DataFrame:
    """Та же логика, что ячейка загрузки ноутбука 28 (без проверки RESIST_IDS и без print calc_*)."""
    dfs = []
    for p in raw_paths:
        if p.exists():
            dfs.append(pd.read_csv(p, dtype=str))
    if not dfs:
        raw_dir = raw_paths[0].parent if raw_paths else Path(".")
        raise FileNotFoundError(f"Файлы данных не найдены в {raw_dir}")

    df_all = pd.concat(dfs, ignore_index=True)
    df_all["period"] = pd.to_datetime(df_all["period"], errors="coerce")
    df_all["resist_id"] = pd.to_numeric(df_all["resist_id"], errors="coerce").astype("Int64")

    bool_cols = ["send", "validate_one", "validate_two", "cancel_approve", "forecast"]
    for col in bool_cols:
        if col in df_all.columns:
            df_all[col] = to_bool(df_all[col])
    df_all["validate_count"] = (
        pd.to_numeric(df_all["validate_count"], errors="coerce").fillna(0).astype(int)
    )
    if "comment" in df_all.columns:
        df_all["comment"] = df_all["comment"].fillna("")
        mask_predict_record = df_all["comment"] == PREDICT_COMMENT
    else:
        mask_predict_record = pd.Series(False, index=df_all.index)

    resist_ok = (
        pd.Series(True, index=df_all.index)
        if include_excluded
        else ~df_all["resist_id"].isin(EXCLUDED_RESIST_IDS)
    )
    mask_ok = ~df_all["cancel_approve"] & ~mask_predict_record & resist_ok
    df_ok = df_all[mask_ok].copy()

    records = []
    for _, row in df_ok.iterrows():
        calc_obj = parse_calculate_param(row.get("calculate_parameter"))
        calc_flat = flatten_calc_to_dict(calc_obj)
        op_raw = row.get("operation_parameter")
        if pd.isna(op_raw):
            continue
        try:
            op_data = json.loads(op_raw)
        except Exception:
            continue
        period = row.get("period")
        if pd.isna(period):
            continue
        for op_id, payload in op_data.items():
            if not isinstance(payload, dict):
                continue
            if to_bool_value(payload.get("operation_active", payload.get("active"))) is False:
                continue
            base_record = {
                "resist_id": row.get("resist_id"),
                "month": int(period.month),
                "year": int(period.year),
                "operation_id": op_id,
                "fact_value": payload.get("fact_value"),
                "fact_predict": payload.get("fact_predict"),
                "workDayMonth_2": calc_flat.get("calc_workDayMonth_2"),
                "calculate_minute": payload.get("calculate_minute"),
            }
            records.append({**base_record, **calc_flat})

    df_model39 = pd.DataFrame(records)
    if df_model39.empty:
        return df_model39

    df_model39["fact_value"] = coerce_numeric_series(df_model39["fact_value"])
    df_model39["fact_predict"] = coerce_numeric_series(df_model39["fact_predict"])
    df_model39["workDayMonth_2"] = coerce_numeric_series(df_model39["workDayMonth_2"])
    df_model39["calculate_minute"] = coerce_numeric_series(df_model39["calculate_minute"])

    calc_cols = [c for c in df_model39.columns if c.startswith("calc_")]
    for col in calc_cols:
        df_model39[col] = coerce_numeric_series(df_model39[col])

    df_model39["date"] = pd.to_datetime(
        dict(year=df_model39["year"], month=df_model39["month"], day=1),
        errors="coerce",
    ).dt.date
    df_model39 = df_model39.dropna(subset=["fact_value"])
    df_model39 = df_model39.sort_values(["operation_id", "year", "month"]).reset_index(drop=True)
    return df_model39


def add_fte_columns(df: pd.DataFrame, norm_hours: float = NORM_HOURS_PER_MONTH) -> pd.DataFrame:
    out = df.copy()
    out["coefficient_fulltime_staff"] = out["calculate_minute"] / 60.0 / norm_hours
    out["fact_fts"] = out["fact_value"] * out["coefficient_fulltime_staff"]
    return out


def parse_months(s: str) -> list[int]:
    parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
    return [int(p) for p in parts]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Экспорт суммы ПШЕ (FTE) по resist_id за период в Excel (сводка + сверка)."
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Выходной .xlsx (нужен openpyxl).",
    )
    p.add_argument(
        "--raw",
        type=Path,
        nargs="*",
        default=None,
        help="Список CSV; по умолчанию data/raw/data-2022…2025 от корня репозитория.",
    )
    p.add_argument("--year", type=int, default=2025, help="Год отбора (по умолчанию 2025).")
    p.add_argument(
        "--months",
        type=str,
        default="7,8,9,10,11,12",
        help="Месяцы через запятую (по умолчанию 7–12).",
    )
    p.add_argument(
        "--norm-hours",
        type=float,
        default=NORM_HOURS_PER_MONTH,
        help=f"Норма часов в месяц для FTE (по умолчанию {NORM_HOURS_PER_MONTH}).",
    )
    p.add_argument(
        "--resist-ids",
        type=int,
        nargs="*",
        default=None,
        help="Ограничить список resist_id (если не задано — все в периоде).",
    )
    p.add_argument(
        "--include-excluded",
        action="store_true",
        help="Не отфильтровывать EXCLUDED_RESIST_IDS.",
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

    months = parse_months(args.months)
    df_fte = add_fte_columns(df_model39, norm_hours=args.norm_hours)

    mask_period = (df_fte["year"] == args.year) & (df_fte["month"].isin(months))
    df_win = df_fte.loc[mask_period].copy()

    if args.resist_ids:
        want = set(args.resist_ids)
        avail = set(int(x) for x in df_win["resist_id"].dropna().unique())
        missing = sorted(want - avail)
        if missing:
            sample = sorted(avail)[:15]
            print(
                f"Нет данных в периоде для resist_id={missing}. "
                f"Примеры доступных в окне: {sample}...",
                file=sys.stderr,
            )
            return 1
        df_win = df_win[df_win["resist_id"].isin(want)].copy()

    if df_win.empty:
        print("После фильтра по периоду и resist_id таблица пуста.", file=sys.stderr)
        return 1

    summary = (
        df_win.groupby("resist_id", sort=True)["fact_fts"]
        .sum()
        .reset_index()
        .rename(columns={"fact_fts": "ПШЕ"})
    )
    summary["ПШЕ"] = summary["ПШЕ"].round(2)

    detail_cols = [
        "resist_id",
        "year",
        "month",
        "operation_id",
        "fact_value",
        "calculate_minute",
        "coefficient_fulltime_staff",
        "fact_fts",
    ]
    detail = df_win[[c for c in detail_cols if c in df_win.columns]].copy()
    detail = detail.sort_values(["resist_id", "year", "month", "operation_id"], kind="mergesort")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name=SUMMARY_SHEET, index=False)
        detail.to_excel(writer, sheet_name=DETAIL_SHEET, index=False)

    print(
        f"Записано: {args.output} (листы «{SUMMARY_SHEET}»: {len(summary)} строк, "
        f"«{DETAIL_SHEET}»: {len(detail)} строк; год={args.year}, месяцы={months})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
