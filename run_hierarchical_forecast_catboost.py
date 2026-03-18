"""
Обёртка для hierarchical_forecast_catboost: итеративный прогноз на 2025,
Этап 2 (доли) — CatBoost вместо ExponentialSmoothing.

Использование:
    python run_hierarchical_forecast_catboost.py
    python run_hierarchical_forecast_catboost.py --output data/processed/hierarchical_forecast_catboost_2025.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from build_dataframe_for_dashboard import (
    clean_and_filter,
    get_calc_value,
    load_raw_data,
    parse_calculate_param,
    parse_division_title,
    to_bool_value,
)
from hierarchical_forecast import _work_hours_for_month
from hierarchical_forecast_catboost import generate_hierarchical_forecast_catboost

TARGET_YEAR = 2025


def extract_operations_for_hierarchical(df_ok: pd.DataFrame) -> pd.DataFrame:
    """Извлекает операции с полями для hierarchical_forecast."""
    records: list[dict] = []
    staff_fallback_count = 0
    staff_ok_count = 0
    for _, row in df_ok.iterrows():
        calc_obj = parse_calculate_param(row.get("calculate_parameter"))
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

        work_days = get_calc_value(calc_obj, "workDayMonth_2")
        staff_raw = get_calc_value(calc_obj, "employFact_7")
        div_title = parse_division_title(row.get("division_name"))

        for op_id, payload in op_data.items():
            if not isinstance(payload, dict):
                continue
            active_flag = to_bool_value(
                payload.get("operation_active", payload.get("active"))
            )
            if active_flag is False:
                continue

            calculate_minute = payload.get("calculate_minute")
            fact_val = payload.get("fact_value")
            fact_predict_val = payload.get("fact_predict")

            if pd.isna(calculate_minute) or float(calculate_minute or 0) <= 0:
                continue

            norm_val = float(calculate_minute) / 60.0

            if work_days is not None and pd.notna(work_days):
                try:
                    wd = float(work_days)
                    work_hours = wd * 8.0 if wd > 0 else _work_hours_for_month(period)
                except (TypeError, ValueError):
                    work_hours = _work_hours_for_month(period)
            else:
                work_hours = _work_hours_for_month(period)

            if staff_raw is not None and pd.notna(staff_raw):
                try:
                    staff = float(staff_raw)
                    staff = max(0.01, staff)
                    staff_ok_count += 1
                except (TypeError, ValueError):
                    staff = 1.0
                    staff_fallback_count += 1
            else:
                staff = 1.0
                staff_fallback_count += 1

            records.append({
                "period": period,
                "resist_id": row.get("resist_id"),
                "division_title": div_title or "",
                "operation_name": str(op_id),
                "fact_value": fact_val,
                "fact_predict": fact_predict_val,
                "norm_value": norm_val,
                "staff_count": staff,
                "work_hours_in_month": work_hours,
            })

    df = pd.DataFrame(records)
    df["fact_value"] = pd.to_numeric(df["fact_value"], errors="coerce")
    df["fact_predict"] = pd.to_numeric(df["fact_predict"], errors="coerce").fillna(0)
    df["resist_id"] = df["resist_id"].astype("Int64")

    total_staff = staff_ok_count + staff_fallback_count
    if total_staff > 0:
        pct_fallback = round(100 * staff_fallback_count / total_staff, 2)
        print(f"  staff_count: employFact_7={staff_ok_count}, fallback=1.0 — {staff_fallback_count} ({pct_fallback}%)")

    return df


def load_and_prepare_full() -> pd.DataFrame:
    """Загрузка и подготовка всех данных."""
    print("Загрузка CSV...")
    df_raw = load_raw_data()
    print(f"  Загружено строк: {len(df_raw)}")

    print("Очистка и фильтрация...")
    df_ok = clean_and_filter(df_raw)
    print(f"  После фильтрации: {len(df_ok)}")

    print("Извлечение операций...")
    df = extract_operations_for_hierarchical(df_ok)
    print(f"  Извлечено записей: {len(df)}")

    df = df.dropna(subset=["fact_value", "resist_id"])
    df = df[df["fact_value"] >= 0]
    df = df.sort_values(["resist_id", "operation_name", "period"]).reset_index(drop=True)
    return df


def run_backtest_2025(full_df: pd.DataFrame) -> pd.DataFrame:
    """Итеративный прогноз на 2025 (backtest по месяцам). Этап 2 — CatBoost."""
    hierarchical_cols = [
        "period", "resist_id", "operation_name", "fact_value", "norm_value",
        "staff_count", "work_hours_in_month",
    ]
    forecast_chunks: list[pd.DataFrame] = []

    for month in range(1, 13):
        cutoff = pd.Timestamp(year=TARGET_YEAR, month=month, day=1)
        historical = full_df[full_df["period"] < cutoff][hierarchical_cols].copy()

        if historical.empty:
            print(f"  Месяц {month}: нет истории до {cutoff.strftime('%Y-%m')}, пропуск")
            continue

        diagnose = month == 1
        forecast = generate_hierarchical_forecast_catboost(historical, diagnose_outliers=diagnose)
        forecast_first = forecast[forecast["period"] == cutoff].copy()
        if not forecast_first.empty:
            forecast_first["month"] = month
            forecast_first["year"] = TARGET_YEAR
            forecast_chunks.append(forecast_first)

        print(f"  Месяц {month}/12: история до {cutoff.strftime('%Y-%m')}, прогноз: {len(forecast_first)} строк")

    if not forecast_chunks:
        return pd.DataFrame()
    return pd.concat(forecast_chunks, ignore_index=True)


def calc_accuracy_pct(fact: np.ndarray, pred: np.ndarray) -> np.ndarray:
    fact = np.asarray(fact, dtype=float)
    pred = np.asarray(pred, dtype=float)
    acc = np.empty_like(fact)
    mask_zero = fact == 0
    acc[mask_zero] = np.where(pred[mask_zero] == 0, 100.0, 0.0)
    mask_ok = ~mask_zero
    if np.any(mask_ok):
        acc[mask_ok] = np.clip(
            100.0 - np.abs(fact[mask_ok] - pred[mask_ok]) / np.abs(fact[mask_ok]) * 100.0,
            0, 100,
        )
    return np.round(acc, 2)


def calc_mean_accuracy(acc: np.ndarray) -> float:
    return round(float(np.mean(acc)), 2)


def calc_stability(acc: np.ndarray) -> float:
    mean_acc = np.mean(acc)
    if mean_acc == 0 or not np.isfinite(mean_acc):
        return 0.0
    cv = np.std(acc, ddof=0) / mean_acc
    return round(max(0.0, (1 - cv)) * 100, 2)


def calc_quality(accuracy: float, stability: float) -> float:
    if accuracy + stability == 0:
        return 0.0
    return round(2 * accuracy * stability / (accuracy + stability), 2)


def build_output_with_metrics(
    forecast_hier: pd.DataFrame,
    actuals_2025: pd.DataFrame,
) -> pd.DataFrame:
    forecast_hier = forecast_hier.copy()
    forecast_hier["period_dt"] = pd.to_datetime(forecast_hier["period"])
    forecast_hier["month"] = forecast_hier["period_dt"].dt.month
    forecast_hier["year"] = forecast_hier["period_dt"].dt.year

    actuals = actuals_2025[["resist_id", "operation_name", "period", "fact_value", "fact_predict", "division_title"]].copy()
    actuals["period_dt"] = pd.to_datetime(actuals["period"])
    actuals["month"] = actuals["period_dt"].dt.month
    actuals["year"] = actuals["period_dt"].dt.year

    merged = forecast_hier.merge(
        actuals,
        on=["resist_id", "operation_name", "month", "year"],
        how="inner",
        suffixes=("", "_act"),
    )

    if merged.empty:
        return merged

    merged["fact_value"] = merged["fact_value_act"] if "fact_value_act" in merged.columns else merged["fact_value"]
    merged["fact_predict"] = merged["fact_predict"].fillna(0)
    merged["fact_predict_hierarchical"] = merged["fact_predict_hierarchical"].clip(lower=0)

    merged["abs_error_hierarchical"] = (merged["fact_value"] - merged["fact_predict_hierarchical"]).abs()
    merged["abs_error_fact_predict"] = (merged["fact_value"] - merged["fact_predict"]).abs()

    acc_hier = calc_accuracy_pct(merged["fact_value"].values, merged["fact_predict_hierarchical"].values)
    acc_fp = calc_accuracy_pct(merged["fact_value"].values, merged["fact_predict"].values)
    merged["accuracy_pct_hierarchical"] = acc_hier
    merged["accuracy_pct_fact_predict"] = acc_fp

    merged["date"] = merged["period_dt"].dt.date

    return merged


def write_excel_with_metrics(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cols_data = [
        "resist_id", "division_title", "operation_id", "date", "month", "year",
        "fact_value", "fact_predict_hierarchical", "fact_predict",
        "abs_error_hierarchical", "accuracy_pct_hierarchical",
        "abs_error_fact_predict", "accuracy_pct_fact_predict",
    ]
    df_out = df.copy()
    df_out["operation_id"] = df_out["operation_name"]
    cols_to_write = [c for c in cols_data if c in df_out.columns]

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_out[cols_to_write].to_excel(writer, sheet_name="Данные", index=False)

        acc_hier = calc_mean_accuracy(df["accuracy_pct_hierarchical"].values)
        stab_hier = calc_stability(df["accuracy_pct_hierarchical"].values)
        qual_hier = calc_quality(acc_hier, stab_hier)

        acc_fp = calc_mean_accuracy(df["accuracy_pct_fact_predict"].values)
        stab_fp = calc_stability(df["accuracy_pct_fact_predict"].values)
        qual_fp = calc_quality(acc_fp, stab_fp)

        metrics = pd.DataFrame([
            {"Прогноз": "Hierarchical (CatBoost доли)", "Точность, %": acc_hier, "Стабильность, %": stab_hier, "Качество, %": qual_hier},
            {"Прогноз": "fact_predict", "Точность, %": acc_fp, "Стабильность, %": stab_fp, "Качество, %": qual_fp},
        ])
        metrics.to_excel(writer, sheet_name="Метрики", index=False)

        rows_by_rid = []
        for rid, grp in df.groupby("resist_id", sort=True):
            div_title = grp["division_title"].iloc[0] if "division_title" in grp.columns else ""
            acc_h = calc_mean_accuracy(grp["accuracy_pct_hierarchical"].values)
            stab_h = calc_stability(grp["accuracy_pct_hierarchical"].values)
            qual_h = calc_quality(acc_h, stab_h)
            acc_f = calc_mean_accuracy(grp["accuracy_pct_fact_predict"].values)
            stab_f = calc_stability(grp["accuracy_pct_fact_predict"].values)
            qual_f = calc_quality(acc_f, stab_f)
            rows_by_rid.append({
                "resist_id": rid,
                "division_title": div_title,
                "Точность (Hierarchical), %": acc_h,
                "Стабильность (Hierarchical), %": stab_h,
                "Качество (Hierarchical), %": qual_h,
                "Точность (fact_predict), %": acc_f,
                "Стабильность (fact_predict), %": stab_f,
                "Качество (fact_predict), %": qual_f,
            })
        metrics_by_rid = pd.DataFrame(rows_by_rid)
        startrow = len(metrics) + 3
        metrics_by_rid.to_excel(writer, sheet_name="Метрики", index=False, startrow=startrow)

    print(f"\nМетрики:")
    print(f"  Hierarchical (CatBoost доли):  Точность={acc_hier}%, Стабильность={stab_hier}%, Качество={qual_hier}%")
    print(f"  fact_predict:  Точность={acc_fp}%, Стабильность={stab_fp}%, Качество={qual_fp}%")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Иерархический прогноз (CatBoost для долей) на 2025, сравнение с fact_predict"
    )
    parser.add_argument(
        "--output", "-o",
        default="data/processed/hierarchical_forecast_catboost_2025.xlsx",
        help="Путь к выходному xlsx",
    )
    args = parser.parse_args()

    full_df = load_and_prepare_full()
    if full_df.empty:
        print("Нет данных. Проверьте CSV и фильтрацию.", file=sys.stderr)
        sys.exit(1)

    print(f"\nИтеративный прогноз на {TARGET_YEAR} (Этап 2 — CatBoost для долей)...")
    forecast_2025 = run_backtest_2025(full_df)
    if forecast_2025.empty:
        print("Не получен прогноз.", file=sys.stderr)
        sys.exit(1)

    full_2025 = full_df[pd.to_datetime(full_df["period"]).dt.year == TARGET_YEAR].copy()
    if full_2025.empty:
        print("Нет фактических данных за 2025.", file=sys.stderr)
        sys.exit(1)

    full_2025["month"] = pd.to_datetime(full_2025["period"]).dt.month
    full_2025["year"] = pd.to_datetime(full_2025["period"]).dt.year
    actuals_2025 = (
        full_2025.sort_values("period")
        .groupby(["resist_id", "operation_name", "month", "year"], as_index=False)
        .agg(
            fact_value=("fact_value", "sum"),
            fact_predict=("fact_predict", "last"),
            division_title=("division_title", "first"),
            period=("period", "first"),
        )
    )

    result = build_output_with_metrics(forecast_2025, actuals_2025)
    if result.empty:
        print("Нет пересечения прогноза и факта.", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).with_suffix(".xlsx")
    write_excel_with_metrics(result, output_path)

    print(f"\nРезультат сохранён: {output_path}")
    print(f"Строк: {len(result)}")


if __name__ == "__main__":
    main()
