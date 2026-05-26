# -*- coding: utf-8 -*-
"""Дашборд: сравнение нового прогноза (JSON comp_predict) с fact_predict за выбранные месяцы.

Читает ``forecast_all_result.json`` (формат ``comp_predict_operation_count_v2``) и факт/текущий
прогноз из ``data-2026.csv`` (через ``load_df_model39_from_nb37_raw_files``), строит xlsx как
``build_model_comparison_dashboard`` (листы Данные, Оценка прогноза, Тепловая карта).

Использование:
    python scripts/build_forecast_all_result_dashboard.py
    python scripts/build_forecast_all_result_dashboard.py --forecast-json path.json --fact-csv path.csv
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from scripts.comparison_operation_count_v2 import DATE_FMT, MODEL_KEY  # noqa: E402
from scripts.nb37_raw_model39_load import load_df_model39_from_nb37_raw_files  # noqa: E402


def _load_build_model_comparison_dashboard():
    path = _ROOT / "scripts" / "build_model_comparison_dashboard.py"
    if not path.is_file():
        raise FileNotFoundError(f"Не найден модуль: {path}")
    spec = importlib.util.spec_from_file_location("build_model_comparison_dashboard", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Не удалось загрузить {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _coerce_operation_id(value: object) -> Any:
    try:
        x = float(value)
        return int(x) if x == int(x) else x
    except (TypeError, ValueError):
        return value


def _normalize_id_series(s: pd.Series) -> pd.Series:
    """Сводит numeric id к int где возможно (для join)."""
    out = pd.to_numeric(s, errors="coerce")
    return out.apply(lambda x: int(x) if pd.notna(x) and float(x) == int(float(x)) else x)


def load_facts_from_csv(csv_path: Path, year: int, months: list[int]) -> pd.DataFrame:
    df = load_df_model39_from_nb37_raw_files([csv_path])
    month_set = set(months)
    df = df.loc[(df["year"] == year) & (df["month"].isin(month_set))].copy()
    cols = ["resist_id", "operation_id", "year", "month", "fact_value"]
    if "fact_predict" not in df.columns:
        df["fact_predict"] = 0.0
    cols.append("fact_predict")
    df = df[cols]
    df["fact_value"] = pd.to_numeric(df["fact_value"], errors="coerce").fillna(0.0)
    df["fact_predict"] = pd.to_numeric(df["fact_predict"], errors="coerce").fillna(0.0)
    df["resist_id"] = _normalize_id_series(df["resist_id"])
    df["operation_id"] = df["operation_id"].map(_coerce_operation_id)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)
    df["month"] = pd.to_numeric(df["month"], errors="coerce").fillna(0).astype(int)
    key = ["resist_id", "operation_id", "year", "month"]
    dup = df.duplicated(subset=key, keep=False)
    if dup.any():
        print(
            f"Предупреждение: дубликаты в факте по {key}, оставлена последняя запись ({dup.sum()} строк).",
            file=sys.stderr,
        )
        df = df.drop_duplicates(subset=key, keep="last")
    return df.reset_index(drop=True)


def flatten_forecast_json(json_path: Path, year: int, months: list[int]) -> pd.DataFrame:
    text = json_path.read_text(encoding="utf-8")
    root = json.loads(text)
    if not isinstance(root, dict):
        raise SystemExit(f"Корень JSON должен быть объектом, получено: {type(root)}")

    month_set = set(months)
    rows: list[dict[str, Any]] = []

    for rid_key, by_op in root.items():
        try:
            rid = int(rid_key)
        except (TypeError, ValueError):
            continue
        if not isinstance(by_op, dict):
            continue
        for op_key, payload in by_op.items():
            if not isinstance(payload, dict):
                continue
            op_id = _coerce_operation_id(op_key)
            model_name = str(payload.get(MODEL_KEY, "") or "")
            for dk, raw_val in payload.items():
                if dk == MODEL_KEY:
                    continue
                if not isinstance(dk, str):
                    continue
                try:
                    ts = pd.Timestamp(dk)
                except (ValueError, TypeError):
                    continue
                if ts.year != year or ts.month not in month_set:
                    continue
                try:
                    v = float(raw_val) if raw_val is not None else float("nan")
                except (TypeError, ValueError):
                    continue
                if not np.isfinite(v):
                    continue
                rows.append({
                    "resist_id": rid,
                    "operation_id": op_id,
                    "year": int(ts.year),
                    "month": int(ts.month),
                    "predict_new": float(v),
                    "best_model_name": model_name,
                })

    if not rows:
        return pd.DataFrame(
            columns=["resist_id", "operation_id", "year", "month", "predict_new", "best_model_name"],
        )

    df = pd.DataFrame(rows)
    key = ["resist_id", "operation_id", "year", "month"]
    dup = df.duplicated(subset=key, keep=False)
    if dup.any():
        print(
            f"Предупреждение: дубликаты прогноза в JSON по {key}, оставлена последняя ({dup.sum()} строк).",
            file=sys.stderr,
        )
        df = df.drop_duplicates(subset=key, keep="last")
    df["resist_id"] = _normalize_id_series(df["resist_id"])
    df["operation_id"] = df["operation_id"].map(_coerce_operation_id)
    return df.reset_index(drop=True)


def build_evaluation_dataframe(
    facts: pd.DataFrame,
    forecast: pd.DataFrame,
    bmcd: Any,
) -> pd.DataFrame:
    key = ["resist_id", "operation_id", "year", "month"]
    merged = facts.merge(forecast, on=key, how="inner")
    n_facts, n_fc = len(facts), len(forecast)
    n_m = len(merged)
    if n_m == 0:
        raise SystemExit(
            f"Пустой join: facts={n_facts} строк, forecast={n_fc} строк, пересечение=0. "
            f"Проверьте resist_id / operation_id / год-месяц."
        )

    bad = merged["predict_new"].isna() | ~np.isfinite(pd.to_numeric(merged["predict_new"], errors="coerce"))
    n_bad = int(bad.sum())
    if n_bad:
        print(
            f"Предупреждение: исключено {n_bad} строк с нечисловым predict_new после join.",
            file=sys.stderr,
        )
        merged = merged.loc[~bad].copy()

    if merged.empty:
        raise SystemExit("После фильтра NaN в predict_new не осталось строк.")

    _accuracy_col = bmcd._accuracy_col

    merged["fact_value"] = pd.to_numeric(merged["fact_value"], errors="coerce").fillna(0.0)
    merged["fact_predict"] = pd.to_numeric(merged["fact_predict"], errors="coerce").fillna(0.0)
    merged["predict_new"] = pd.to_numeric(merged["predict_new"], errors="coerce").fillna(0.0)

    merged["abs_error"] = (merged["fact_value"] - merged["fact_predict"]).abs()
    merged["accuracy_pct"] = _accuracy_col(merged["fact_value"], merged["fact_predict"])

    merged["abs_error_new"] = (merged["fact_value"] - merged["predict_new"]).abs()
    merged["accuracy_pct_new"] = _accuracy_col(merged["fact_value"], merged["predict_new"])

    merged["predict_chosen"] = merged["predict_new"]
    merged["abs_error_chosen"] = (merged["fact_value"] - merged["predict_chosen"]).abs()
    merged["accuracy_pct_chosen"] = _accuracy_col(merged["fact_value"], merged["predict_chosen"])

    if "division_title" not in merged.columns:
        merged["division_title"] = ""
    merged["best_model_name"] = merged["best_model_name"].fillna("").astype(str)

    merged["resist_id"] = pd.to_numeric(merged["resist_id"], errors="coerce")
    merged["resist_id"] = merged["resist_id"].apply(
        lambda x: int(x) if pd.notna(x) and float(x) == int(x) else x
    )

    return merged.reset_index(drop=True)


def _report_month_coverage(df: pd.DataFrame, months: list[int]) -> None:
    present = sorted(int(x) for x in df["month"].unique().tolist())
    missing = [m for m in months if m not in present]
    if missing:
        print(
            f"Предупреждение: в результате нет месяцев {missing} (есть: {present}).",
            file=sys.stderr,
        )
    counts = df.groupby("month").size()
    print("Строк по месяцам (month):", counts.to_dict(), flush=True)


def build_dashboard(
    forecast_json: Path,
    fact_csv: Path,
    output_path: Path,
    *,
    year: int,
    months: list[int],
    second_forecast_label: str,
    second_block_table_label: str,
) -> Path:
    bmcd = _load_build_model_comparison_dashboard()
    facts = load_facts_from_csv(fact_csv, year, months)
    forecast = flatten_forecast_json(forecast_json, year, months)

    if facts.empty:
        raise SystemExit(f"Нет строк факта: {fact_csv} для year={year}, months={months}")
    if forecast.empty:
        raise SystemExit(
            f"Нет строк прогноза в JSON: {forecast_json} для year={year}, months={months}. "
            f"Проверьте горизонт и формат ключей дат ({DATE_FMT}).",
        )

    df = build_evaluation_dataframe(facts, forecast, bmcd)
    _report_month_coverage(df, months)

    div_stats = bmcd._division_stats_dual(df)

    wb = Workbook()
    wb.remove(wb.active)

    bmcd.build_data_sheet(wb, df)
    bmcd.build_dashboard_sheet(
        wb,
        df,
        div_stats,
        main_title=(
            f"Оценка качества прогноза (forecast_all_result vs fact_predict, {year} "
            f"мес. {','.join(str(m) for m in sorted(months))})"
        ),
        second_forecast_label=second_forecast_label,
        second_block_table_label=second_block_table_label,
    )
    bmcd.build_heatmap_sheet(
        wb,
        df,
        title_baseline="Тепловая карта: Качество (%) по fact_predict (текущий)",
        title_chosen=f"Тепловая карта: Качество (%) по {second_block_table_label}",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    print(f"Дашборд сохранён: {output_path.resolve()}")
    print(f"  строк данных: {len(df)}", flush=True)
    return output_path


def _default_forecast_json() -> Path:
    return _ROOT / "data" / "processed" / "forecast_all_result.json"


def _default_fact_csv() -> Path:
    return _ROOT / "data" / "raw" / "data-2026.csv"


def _default_output() -> Path:
    return _ROOT / "data" / "processed" / "forecast_all_result_dashboard.xlsx"


def main() -> None:
    p = argparse.ArgumentParser(
        description="Excel-дашборд: JSON прогноз (comp_predict) vs fact_predict из CSV за заданные месяцы.",
    )
    p.add_argument(
        "--forecast-json",
        type=Path,
        default=_default_forecast_json(),
        help="Путь к forecast_all_result.json (default: data/processed/forecast_all_result.json)",
    )
    p.add_argument(
        "--fact-csv",
        type=Path,
        default=_default_fact_csv(),
        help="CSV raw как nb37 (default: data/raw/data-2026.csv)",
    )
    p.add_argument("--year", type=int, default=2026)
    p.add_argument(
        "--months",
        type=str,
        default="1,2,3,4",
        help="Месяцы через запятую (default: 1,2,3,4)",
    )
    p.add_argument(
        "--output",
        "-o",
        type=Path,
        default=_default_output(),
        help="Выходной xlsx (default: data/processed/forecast_all_result_dashboard.xlsx)",
    )
    p.add_argument(
        "--second-forecast-label",
        type=str,
        default="Комбайн",
        help="Подпись второго прогноза на KPI (default: Комбайн)",
    )
    p.add_argument(
        "--second-block-table-label",
        type=str,
        default="комбайн",
        help="Суффикс в заголовках таблиц для второго прогноза (default: комбайн)",
    )
    args = p.parse_args()

    months = [int(x.strip()) for x in args.months.split(",") if x.strip()]

    if not args.forecast_json.is_file():
        print(f"Файл не найден: {args.forecast_json}", file=sys.stderr)
        sys.exit(1)
    if not args.fact_csv.is_file():
        print(f"Файл не найден: {args.fact_csv}", file=sys.stderr)
        sys.exit(1)

    build_dashboard(
        args.forecast_json,
        args.fact_csv,
        args.output,
        year=args.year,
        months=months,
        second_forecast_label=args.second_forecast_label,
        second_block_table_label=args.second_block_table_label,
    )


if __name__ == "__main__":
    main()
