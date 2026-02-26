"""
Сборка датафрейма для дашборда build_metrics_dashboard_simple.py.

Извлекает из CSV (raw) данные по всем resist_id, парсит JSON-поля,
применяет фильтрацию начальных нулевых месяцев 2025 года
и сохраняет xlsx с минимальным набором столбцов, необходимых для дашборда.

Использование:
    python build_dataframe_for_dashboard.py
    python build_dataframe_for_dashboard.py --output data/processed/dashboard_input.xlsx
    python build_dataframe_for_dashboard.py --year 2025
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


RAW_DIR = Path("data/raw")
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]

EXCLUDED_RESIST_IDS = [
    25, 26, 27, 29, 54, 57, 61, 63, 66, 68, 80, 81, 82, 83, 100, 101, 102, 103,
    104, 105, 106, 109, 112, 113, 115, 116, 119, 120, 121, 122, 123, 125, 126,
    129, 131, 132, 134, 135, 136, 137, 138, 140, 141, 143, 144, 146, 147, 148,
    149, 150, 151, 152, 153, 154, 156, 157, 158, 162, 165, 169, 170, 171, 172,
    173, 174, 175, 176, 177, 178, 179, 181, 196,
]

PREDICT_COMMENT = "first_predict_value_record"

OUTPUT_COLS = [
    "resist_id",
    "division_title",
    "date",
    "operation_id",
    "month",
    "year",
    "fact_value",
    "fact_predict",
    "fact_fts",
]


def to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "t", "1"])


def to_bool_value(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return None
    return str(value).strip().lower() in ["true", "t", "1"]


def parse_division_title(div_json: str) -> str | None:
    if pd.isna(div_json):
        return None
    try:
        obj = json.loads(div_json)
    except Exception:
        return None
    return obj.get("name")


def parse_calculate_param(calc_json: str) -> dict:
    if pd.isna(calc_json):
        return {}
    try:
        return json.loads(calc_json)
    except Exception:
        return {}


def get_calc_value(calc_obj: dict, key: str):
    val = calc_obj.get(key)
    if isinstance(val, dict):
        return val.get("value")
    return val


def load_raw_data() -> pd.DataFrame:
    dfs = []
    for p in RAW_FILES:
        if not p.exists():
            print(f"Файл не найден, пропуск: {p}", file=sys.stderr)
            continue
        dfs.append(pd.read_csv(p, dtype=str))
    if not dfs:
        print("Нет CSV-файлов для загрузки.", file=sys.stderr)
        sys.exit(1)
    df = pd.concat(dfs, ignore_index=True)
    df["period"] = pd.to_datetime(df["period"], errors="coerce")
    df["resist_id"] = pd.to_numeric(df["resist_id"], errors="coerce").astype("Int64")
    return df


def clean_and_filter(df: pd.DataFrame) -> pd.DataFrame:
    if "cancel_approve" in df.columns:
        df["cancel_approve"] = to_bool(df["cancel_approve"])
    else:
        df["cancel_approve"] = False

    if "comment" in df.columns:
        df["comment"] = df["comment"].fillna("")
        mask_predict_record = df["comment"] == PREDICT_COMMENT
    else:
        mask_predict_record = pd.Series(False, index=df.index)

    mask_not_cancelled = ~df["cancel_approve"]
    mask_resist_allowed = ~df["resist_id"].isin(EXCLUDED_RESIST_IDS)

    return df[mask_not_cancelled & ~mask_predict_record & mask_resist_allowed].copy()


def extract_operations(df_ok: pd.DataFrame) -> pd.DataFrame:
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

        calc_minute_raw = get_calc_value(calc_obj, "workDayMonth_2")

        for op_id, payload in op_data.items():
            if not isinstance(payload, dict):
                continue
            active_flag = to_bool_value(
                payload.get("operation_active", payload.get("active"))
            )
            if active_flag is False:
                continue

            calculate_minute = payload.get("calculate_minute")

            records.append({
                "resist_id": row.get("resist_id"),
                "division_title": parse_division_title(row.get("division_name")),
                "month": int(period.month),
                "year": int(period.year),
                "operation_id": op_id,
                "fact_value": payload.get("fact_value"),
                "fact_predict": payload.get("fact_predict"),
                "calculate_minute": calculate_minute,
            })

    df_ops = pd.DataFrame(records)
    df_ops["fact_value"] = pd.to_numeric(df_ops["fact_value"], errors="coerce")
    df_ops["fact_predict"] = pd.to_numeric(df_ops["fact_predict"], errors="coerce")
    df_ops["calculate_minute"] = pd.to_numeric(df_ops["calculate_minute"], errors="coerce")
    return df_ops


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    df["coefficient_fulltime_staff"] = df["calculate_minute"] / 60 / 148.3
    df["fact_fts"] = df["fact_value"] * df["coefficient_fulltime_staff"]

    df["date"] = pd.to_datetime(
        dict(year=df["year"], month=df["month"], day=1),
        errors="coerce",
    ).dt.date

    return df


def filter_leading_zeros(df: pd.DataFrame, filter_year: int) -> pd.DataFrame:
    """Для каждой операции: последовательно проверяем месяцы filter_year
    начиная с января. Пока fact_value=0 и fact_predict=0 — удаляем строку.
    Как только встретился месяц с fact_value!=0 или fact_predict!=0 —
    прекращаем проверку, остальные месяцы не трогаем.
    Данные других лет не затрагиваются."""

    def _filter_group(group: pd.DataFrame) -> pd.DataFrame:
        group = group.sort_values(["year", "month"]).reset_index(drop=True)
        yr_mask = group["year"] == filter_year
        yr_rows = group.loc[yr_mask].sort_values("month")
        if yr_rows.empty:
            return group
        drop_indices = []
        for idx in yr_rows.index:
            r = group.loc[idx]
            if r["fact_value"] != 0 or r["fact_predict"] != 0:
                break
            drop_indices.append(idx)
        if not drop_indices:
            return group
        return group.drop(index=drop_indices).reset_index(drop=True)

    return (
        df
        .groupby("operation_id", group_keys=False)
        .apply(_filter_group)
        .reset_index(drop=True)
    )


def build_dataframe(filter_year: int) -> pd.DataFrame:
    print("Загрузка CSV...")
    df_raw = load_raw_data()
    print(f"  Загружено строк: {len(df_raw)}")

    print("Очистка и фильтрация...")
    df_ok = clean_and_filter(df_raw)
    print(f"  После фильтрации: {len(df_ok)}")

    print("Извлечение операций из JSON...")
    df_ops = extract_operations(df_ok)
    print(f"  Операций извлечено: {len(df_ops)}")

    df_ops = add_derived_columns(df_ops)

    df_ops = df_ops.dropna(subset=["fact_value"])
    print(f"  После удаления строк без fact_value: {len(df_ops)}")

    print(f"Фильтрация начальных нулевых месяцев {filter_year}...")
    df_ops = filter_leading_zeros(df_ops, filter_year)
    print(f"  После фильтрации нулей: {len(df_ops)}")

    df_ops = df_ops.sort_values(
        ["resist_id", "division_title", "operation_id", "year", "month"]
    ).reset_index(drop=True)

    present = [c for c in OUTPUT_COLS if c in df_ops.columns]
    return df_ops[present]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Сборка датафрейма для build_metrics_dashboard_simple.py"
    )
    parser.add_argument(
        "--output", "-o",
        default="data/processed/dashboard_input.xlsx",
        help="Путь к выходному xlsx",
    )
    parser.add_argument(
        "--year", "-y",
        type=int,
        default=2025,
        help="Год для фильтрации начальных нулевых месяцев (default: 2025)",
    )
    args = parser.parse_args()

    df = build_dataframe(args.year)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(str(output_path), index=False)
    print(f"\nФайл сохранён: {output_path}")
    print(f"Строк: {len(df)}")
    print(f"\nДля построения дашборда:")
    print(f"  python build_metrics_dashboard_simple.py --input {output_path}")


if __name__ == "__main__":
    main()
