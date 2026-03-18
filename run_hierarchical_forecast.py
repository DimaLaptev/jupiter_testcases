"""
Обёртка для hierarchical_forecast: загрузка данных из CSV (как build_dataframe_for_dashboard),
подготовка в формате hierarchical_forecast и запуск иерархического прогноза.

Использование:
    python run_hierarchical_forecast.py
    python run_hierarchical_forecast.py --output data/processed/hierarchical_forecast.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from build_dataframe_for_dashboard import (
    clean_and_filter,
    get_calc_value,
    load_raw_data,
    parse_calculate_param,
    to_bool_value,
)
from hierarchical_forecast import _work_hours_for_month, generate_hierarchical_forecast


def extract_operations_for_hierarchical(df_ok: pd.DataFrame) -> pd.DataFrame:
    """
    Извлекает операции с полями, необходимыми для hierarchical_forecast:
    period, resist_id, operation_name, fact_value, norm_value, staff_count, work_hours_in_month.
    """
    records: list[dict] = []
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

            if pd.isna(calculate_minute) or float(calculate_minute or 0) <= 0:
                continue

            norm_val = float(calculate_minute) / 60.0  # минуты → часы

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
                except (TypeError, ValueError):
                    staff = 1.0
            else:
                staff = 1.0

            records.append({
                "period": period,
                "resist_id": row.get("resist_id"),
                "operation_name": str(op_id),
                "fact_value": fact_val,
                "norm_value": norm_val,
                "staff_count": staff,
                "work_hours_in_month": work_hours,
            })

    df = pd.DataFrame(records)
    df["fact_value"] = pd.to_numeric(df["fact_value"], errors="coerce")
    df["resist_id"] = df["resist_id"].astype("Int64")
    return df


def load_and_prepare_for_hierarchical() -> pd.DataFrame:
    """
    Загрузка и подготовка данных для hierarchical_forecast.
    Логика как в build_dataframe_for_dashboard: raw CSV → clean_and_filter → extract.
    """
    print("Загрузка CSV...")
    df_raw = load_raw_data()
    print(f"  Загружено строк: {len(df_raw)}")

    print("Очистка и фильтрация...")
    df_ok = clean_and_filter(df_raw)
    print(f"  После фильтрации: {len(df_ok)}")

    print("Извлечение операций для hierarchical_forecast...")
    df = extract_operations_for_hierarchical(df_ok)
    print(f"  Извлечено записей: {len(df)}")

    df = df.dropna(subset=["fact_value", "resist_id"])
    df = df[df["fact_value"] >= 0]
    print(f"  После удаления NaN/отрицательных fact_value: {len(df)}")

    df = df.sort_values(["resist_id", "operation_name", "period"]).reset_index(drop=True)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Иерархический прогноз: загрузка данных и вызов generate_hierarchical_forecast"
    )
    parser.add_argument(
        "--output", "-o",
        default="data/processed/hierarchical_forecast.xlsx",
        help="Путь к выходному файлу (xlsx или csv)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["xlsx", "csv"],
        default="xlsx",
        help="Формат вывода: xlsx или csv",
    )
    args = parser.parse_args()

    historical_df = load_and_prepare_for_hierarchical()

    if historical_df.empty:
        print("Нет данных для прогноза. Проверьте CSV и фильтрацию.", file=sys.stderr)
        sys.exit(1)

    print("\nЗапуск иерархического прогноза...")
    forecast_df = generate_hierarchical_forecast(historical_df)
    print(f"  Прогноз: {len(forecast_df)} строк")

    output_path = Path(args.output)
    if args.format == "csv" or str(output_path).lower().endswith(".csv"):
        output_path = output_path.with_suffix(".csv")
        forecast_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    else:
        output_path = output_path.with_suffix(".xlsx")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        forecast_df.to_excel(output_path, index=False)

    print(f"\nРезультат сохранён: {output_path}")
    print(f"\nКолонки: {list(forecast_df.columns)}")
    if len(forecast_df) > 0:
        print(f"\nПервые строки:")
        print(forecast_df.head(10).to_string())


if __name__ == "__main__":
    main()
