#!/usr/bin/env python3
"""
Скрипт production-прогноза с регрессором workDayMonth_2.
Тестирование на выбранных месяцах и resist_id.
Подготовка данных — как в forecast_experiments_catboost.ipynb и forecast_experiments_production.ipynb.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# --- Конфиг ---
RAW_DIR = ROOT / "data" / "raw"
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]
FILTER_YEAR = 2025

# Месяцы для теста: None = все 12, иначе [1, 2, 3] и т.д.
TEST_MONTHS = None  # пример: [1, 2, 3] для января–марта

# resist_id для теста: None = все, иначе [31, 47, 49] и т.д.
TEST_RESIST_IDS = None  # пример: [31, 47, 49]

PREDICT_COMMENT = "first_predict_value_record"
EXCLUDED_RESIST_IDS = [
    25, 26, 27, 29, 54, 57, 61, 63, 66, 68, 80, 81, 82, 83, 100, 101, 102, 103,
    104, 105, 106, 109, 112, 113, 115, 116, 119, 120, 121, 122, 123, 125, 126,
    129, 131, 132, 134, 135, 136, 137, 138, 140, 141, 143, 144, 146, 147, 148,
    149, 150, 151, 152, 153, 154, 156, 157, 158, 162, 165, 169, 170, 171, 172,
    173, 174, 175, 176, 177, 178, 179, 181, 196, 51, 65, 139,
]


def to_bool_value(value):
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return None
    return str(value).strip().lower() in ["true", "t", "1"]


def parse_division_title(div_json):
    if pd.isna(div_json):
        return None
    try:
        obj = json.loads(div_json)
    except Exception:
        return None
    return obj.get("name")


def parse_calculate_param(calc_json):
    if pd.isna(calc_json):
        return {}
    try:
        return json.loads(calc_json)
    except Exception:
        return {}


def get_calc_value(calc_obj, key):
    val = calc_obj.get(key)
    if isinstance(val, dict):
        return val.get("value")
    return val


def load_and_prepare_data():
    """Загрузка и подготовка данных, как в ноутбуках."""
    dfs = []
    for p in RAW_FILES:
        if p.exists():
            dfs.append(pd.read_csv(p, dtype=str))
    if not dfs:
        raise FileNotFoundError("Нет CSV-файлов для загрузки.")

    df_raw = pd.concat(dfs, ignore_index=True)
    df_raw["period"] = pd.to_datetime(df_raw["period"], errors="coerce")
    df_raw["resist_id"] = pd.to_numeric(df_raw["resist_id"], errors="coerce").astype("Int64")

    if "cancel_approve" in df_raw.columns:
        df_raw["cancel_approve"] = df_raw["cancel_approve"].astype(str).str.lower().isin(["true", "t", "1"])
    else:
        df_raw["cancel_approve"] = False
    if "comment" in df_raw.columns:
        df_raw["comment"] = df_raw["comment"].fillna("")
        mask_predict = df_raw["comment"] == PREDICT_COMMENT
    else:
        mask_predict = pd.Series(False, index=df_raw.index)
    mask_ok = ~df_raw["cancel_approve"] & ~mask_predict & ~df_raw["resist_id"].isin(EXCLUDED_RESIST_IDS)
    df_ok = df_raw[mask_ok].copy()

    records = []
    for _, row in df_ok.iterrows():
        calc_obj = parse_calculate_param(row.get("calculate_parameter"))
        workday = get_calc_value(calc_obj, "workDayMonth_2")
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
            active = to_bool_value(payload.get("operation_active", payload.get("active")))
            if active is False:
                continue
            records.append({
                "resist_id": row.get("resist_id"),
                "division_title": parse_division_title(row.get("division_name")),
                "id": row.get("id"),
                "month": int(period.month),
                "year": int(period.year),
                "operation_id": op_id,
                "fact_value": payload.get("fact_value"),
                "fact_predict": payload.get("fact_predict"),
                "workDayMonth_2": workday,
                "calculate_minute": payload.get("calculate_minute"),
            })

    df = pd.DataFrame(records)
    df["fact_value"] = pd.to_numeric(df["fact_value"], errors="coerce")
    df["fact_predict"] = pd.to_numeric(df["fact_predict"], errors="coerce")
    df["workDayMonth_2"] = pd.to_numeric(df["workDayMonth_2"], errors="coerce")
    df["calculate_minute"] = pd.to_numeric(df["calculate_minute"], errors="coerce")

    df["coefficient_fulltime_staff"] = df["calculate_minute"] / 60 / 148.3
    df["fact_fts"] = df["fact_value"] * df["coefficient_fulltime_staff"]
    df["date"] = pd.to_datetime(dict(year=df["year"], month=df["month"], day=1), errors="coerce").dt.date
    df = df.dropna(subset=["fact_value"])

    df["_grp"] = df["resist_id"].astype(str) + "|" + df["division_title"].astype(str) + "|" + df["operation_id"].astype(str)
    yr_mask = df["year"] == FILTER_YEAR
    drop_idx = set()
    for g in df["_grp"].unique():
        grp = df[(df["_grp"] == g) & yr_mask].sort_values("month")
        for idx in grp.index:
            fv, fp = df.at[idx, "fact_value"], df.at[idx, "fact_predict"]
            if (pd.isna(fv) or float(fv) == 0) and (pd.isna(fp) or float(fp) == 0):
                drop_idx.add(idx)
            else:
                break
    df = df.drop(index=list(drop_idx)).drop(columns=["_grp"]).reset_index(drop=True)
    df = df.sort_values(["operation_id", "year", "month"]).reset_index(drop=True)

    group = df.groupby("operation_id")
    df["lag_1"] = group["fact_value"].shift(1)
    df["lag_12"] = group["fact_value"].shift(12)
    df["roll_mean_3"] = group["fact_value"].transform(lambda s: s.shift(1).rolling(3, min_periods=3).mean())
    df["roll_mean_6"] = group["fact_value"].transform(lambda s: s.shift(1).rolling(6, min_periods=6).mean())
    df["trend"] = df["lag_1"] / df["roll_mean_3"]
    df["trend"] = df["trend"].replace([np.inf, -np.inf], 0)
    num_cols = df.select_dtypes(include=["number"]).columns
    df[num_cols] = df[num_cols].fillna(0)
    df = df.infer_objects(copy=False)

    return df


def calc_mae(y_true, y_pred):
    return np.mean(np.abs(np.array(y_true) - np.array(y_pred)))


def calc_mape(y_true, y_pred):
    y_true, y_pred = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    err = np.empty_like(y_true)
    mask_zero = y_true == 0
    err[mask_zero] = np.where(y_pred[mask_zero] == 0, 0.0, 100.0)
    mask_ok = ~mask_zero
    if np.any(mask_ok):
        err[mask_ok] = np.abs(y_true[mask_ok] - y_pred[mask_ok]) / np.abs(y_true[mask_ok]) * 100
    return float(np.mean(err))


def calc_quality(y_true, y_pred):
    y_true, y_pred = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    acc = np.empty_like(y_true)
    mask_zero = y_true == 0
    acc[mask_zero] = np.where(y_pred[mask_zero] == 0, 100.0, 0.0)
    mask_ok = ~mask_zero
    if np.any(mask_ok):
        acc[mask_ok] = np.clip(100.0 - np.abs(y_true[mask_ok] - y_pred[mask_ok]) / np.abs(y_true[mask_ok]) * 100.0, 0, 100)
    mean_acc = float(np.mean(acc))
    if mean_acc == 0:
        return 0.0
    cv = np.std(acc, ddof=0) / mean_acc
    stab = max(0.0, (1 - cv)) * 100
    return 2 * mean_acc * stab / (mean_acc + stab)


def main():
    print("Загрузка данных...")
    df = load_and_prepare_data()
    print(f"Данных: {len(df)} строк")

    last_year = int(df["year"].max())

    print(f"\nТест: год={last_year}, месяцы={TEST_MONTHS or 'все'}, resist_id={TEST_RESIST_IDS or 'все'}")

    from production_forecast_workday import run_production_workday_experiment

    test_df, pred = run_production_workday_experiment(
        df,
        last_year,
        test_months=TEST_MONTHS,
        test_resist_ids=TEST_RESIST_IDS,
        variant="vanilla",
    )

    if test_df.empty or len(pred) == 0:
        print("Нет данных для теста при заданных фильтрах.")
        return

    y_true = test_df["fact_value"].values

    mae = calc_mae(y_true, pred)
    mape = calc_mape(y_true, pred)
    qi = calc_quality(y_true, pred)

    print(f"\nМетрики (workDayMonth_2 regressor, n={len(pred)}):")
    print(f"  MAE:     {mae:.2f}")
    print(f"  MAPE:    {mape:.2f}%")
    print(f"  Качество: {qi:.2f}")

    comp = test_df.copy()
    comp["pred_new"] = pred
    comp["fact_predict"] = comp["fact_predict"].fillna(0)

    def quality_by_resist(g):
        return calc_quality(g["fact_value"].values, g["pred_new"].values)

    def quality_fp_by_resist(g):
        return calc_quality(g["fact_value"].values, g["fact_predict"].values)

    q_new = comp.groupby("resist_id").apply(quality_by_resist)
    q_fp = comp.groupby("resist_id").apply(quality_fp_by_resist)

    diff = pd.DataFrame({
        "resist_id": q_fp.index,
        "Качество fact_predict": q_fp.values,
        "Качество новый прогноз": q_new.values,
    })
    diff["Δ Качество"] = diff["Качество новый прогноз"] - diff["Качество fact_predict"]
    diff = diff.sort_values("resist_id").reset_index(drop=True)
    print("\nСравнение по resist_id:")
    print(diff.to_string(index=False))


if __name__ == "__main__":
    main()
