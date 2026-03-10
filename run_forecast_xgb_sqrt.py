"""
Прогноз количества операций: XGBoost с sample_weight=sqrt(calculate_minute).

Пайплайн: загрузка CSV → фильтрация → извлечение операций → feature engineering
→ train/test split по году (тест = 2025) → обучение XGBoost → прогноз на тест
→ сохранение Excel → сборка дашборда build_metrics_dashboard_simple.

Конфигурация модели (block9_sample_weight_sqrt):
  - XGBoost, objective=reg:absoluteerror (MAE)
  - sample_weight = sqrt(calculate_minute)

Использование:
    python run_forecast_xgb_sqrt.py
    python run_forecast_xgb_sqrt.py --output data/processed/forecast_xgb_sqrt_dashboard.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

# ---------------------------------------------------------------------------
#  Конфиг
# ---------------------------------------------------------------------------

RAW_DIR = Path("data/raw")
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]
FILTER_YEAR = 2025
OUTPUT_DIR = Path("data/processed")

EXCLUDED_RESIST_IDS = [
    25, 26, 27, 29, 54, 57, 61, 63, 66, 68, 80, 81, 82, 83, 100, 101, 102, 103,
    104, 105, 106, 109, 112, 113, 115, 116, 119, 120, 121, 122, 123, 125, 126,
    129, 131, 132, 134, 135, 136, 137, 138, 140, 141, 143, 144, 146, 147, 148,
    149, 150, 151, 152, 153, 154, 156, 157, 158, 162, 165, 169, 170, 171, 172,
    173, 174, 175, 176, 177, 178, 179, 181, 196, 51, 65, 139,
]
PREDICT_COMMENT = "first_predict_value_record"

CAT_COLS = ["operation_id", "division_title", "resist_id"]
NUM_COLS = [
    "month", "year", "workDayMonth_2", "calculate_minute", "coefficient_fulltime_staff",
    "lag_1", "lag_12", "roll_mean_3", "roll_mean_6", "trend",
]
FEATURE_COLS = CAT_COLS + NUM_COLS
TARGET_COL = "fact_value"


# ---------------------------------------------------------------------------
#  Загрузка и подготовка данных
# ---------------------------------------------------------------------------


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


def load_and_prepare_data() -> pd.DataFrame:
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
        df_raw["cancel_approve"] = to_bool(df_raw["cancel_approve"])
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
    df["date"] = pd.to_datetime(
        dict(year=df["year"], month=df["month"], day=1),
        errors="coerce",
    ).dt.date
    df = df.dropna(subset=["fact_value"])

    # filter_leading_zeros
    df["_grp"] = (
        df["resist_id"].astype(str) + "|"
        + df["division_title"].astype(str) + "|"
        + df["operation_id"].astype(str)
    )
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

    # Feature engineering
    group = df.groupby("operation_id")
    df["lag_1"] = group["fact_value"].shift(1)
    df["lag_12"] = group["fact_value"].shift(12)
    df["roll_mean_3"] = group["fact_value"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=3).mean()
    )
    df["roll_mean_6"] = group["fact_value"].transform(
        lambda s: s.shift(1).rolling(6, min_periods=6).mean()
    )
    df["trend"] = df["lag_1"] / df["roll_mean_3"]
    df["trend"] = df["trend"].replace([np.inf, -np.inf], 0)
    num_cols = df.select_dtypes(include=["number"]).columns
    df[num_cols] = df[num_cols].fillna(0)
    df = df.infer_objects(copy=False)

    return df


def prepare_train_test(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """Возвращает (train_df, test_df_encoded, test_df_orig, feats).
    test_df_orig — с оригинальными resist_id, division_title, operation_id для дашборда."""
    last_year = df["year"].max()
    train_df = df[df["year"] < last_year].copy()
    test_df = df[df["year"] == last_year].copy()
    test_df_orig = test_df.copy()

    for c in CAT_COLS:
        le = LabelEncoder()
        all_vals = pd.concat([train_df[c], test_df[c]], ignore_index=True).astype(str)
        le.fit(all_vals)
        train_df[c] = le.transform(train_df[c].astype(str))
        test_df[c] = le.transform(test_df[c].astype(str))

    return train_df, test_df, test_df_orig, FEATURE_COLS


# ---------------------------------------------------------------------------
#  Обучение и прогноз
# ---------------------------------------------------------------------------


def train_and_predict(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feats: list[str],
) -> tuple[np.ndarray, object]:
    from xgboost import XGBRegressor

    X_train = train_df[feats]
    X_test = test_df[feats]
    y_train = train_df[TARGET_COL]

    cm = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    sample_weight = np.sqrt(np.maximum(cm, 0.1))

    model = XGBRegressor(
        n_estimators=1000,
        max_depth=6,
        learning_rate=0.1,
        objective="reg:absoluteerror",
        random_state=42,
        verbosity=0,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, test_df[TARGET_COL])],
        sample_weight=sample_weight,
        verbose=False,
    )

    pred = np.maximum(model.predict(X_test), 0)
    return pred, model


# ---------------------------------------------------------------------------
#  Главная функция
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Прогноз XGBoost (sample_weight=sqrt) → дашборд"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Путь к выходному xlsx дашборда",
    )
    args = parser.parse_args()

    print("Загрузка и подготовка данных...")
    df = load_and_prepare_data()
    print(f"  Данных: {len(df)} строк")

    print("Разбиение train/test по году...")
    train_df, test_df_enc, test_df_orig, feats = prepare_train_test(df)
    print(f"  Train: {len(train_df)}, Test: {len(test_df_enc)}")

    print("Обучение XGBoost (objective=MAE, sample_weight=sqrt)...")
    pred, model = train_and_predict(train_df, test_df_enc, feats)
    print("  Готово")

    print("Формирование датафрейма для дашборда...")
    df_dash = test_df_orig.copy()
    df_dash["fact_predict"] = pred

    dash_cols = [
        "resist_id", "division_title", "operation_id", "date",
        "month", "year", "fact_value", "fact_predict", "fact_fts",
    ]
    df_dash = df_dash[[c for c in dash_cols if c in df_dash.columns]]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dashboard_input = OUTPUT_DIR / "forecast_input_xgb_sqrt.xlsx"
    df_dash.to_excel(dashboard_input, index=False)
    print(f"  Сохранено: {dashboard_input}")

    if args.output is None:
        output_path = OUTPUT_DIR / "forecast_dashboard_xgb_sqrt.xlsx"
    else:
        output_path = Path(args.output)
        if output_path.suffix not in (".xlsx", ".xls"):
            output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Сборка дашборда...")
    from build_metrics_dashboard_simple import build_dashboard

    build_dashboard(
        dashboard_input,
        output_path=output_path,
        forecast_col="fact_predict",
    )
    print(f"Дашборд сохранён: {output_path}")


if __name__ == "__main__":
    main()
