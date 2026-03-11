"""
Прогноз количества операций: XGBoost MAE с линейными весами.

Пайплайн: загрузка CSV → фильтрация → feature engineering → train/test (тест = 2025)
→ обучение XGBoost → прогноз → Excel дашборд.

Конфигурация (block3_xgb_mae):
  - XGBoost, objective=reg:absoluteerror (MAE)
  - sample_weight = calculate_minute (линейный вес по нормативу времени)
  - n_estimators=1000, max_depth=6, learning_rate=0.1

Использование:
    python run_forecast_xgb_mae.py
    python run_forecast_xgb_mae.py --output data/processed/forecast_xgb_mae_dashboard.xlsx
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

from run_forecast_xgb_sqrt import (
    FEATURE_COLS,
    OUTPUT_DIR,
    TARGET_COL,
    load_and_prepare_data,
    prepare_train_test,
)


def train_and_predict(train_df: pd.DataFrame, test_df: pd.DataFrame, feats: list[str]) -> tuple[np.ndarray, object]:
    from xgboost import XGBRegressor

    X_train = train_df[feats]
    X_test = test_df[feats]
    y_train = train_df[TARGET_COL]
    cm = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    sample_weight = np.maximum(cm.values.astype(float), 0)

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Прогноз XGBoost (MAE, sample_weight=calculate_minute) → дашборд")
    parser.add_argument("--output", "-o", default=None, help="Путь к выходному xlsx дашборда")
    args = parser.parse_args()

    print("Загрузка и подготовка данных...")
    df = load_and_prepare_data()
    print(f"  Данных: {len(df)} строк")

    print("Разбиение train/test по году...")
    train_df, test_df_enc, test_df_orig, feats = prepare_train_test(df)
    print(f"  Train: {len(train_df)}, Test: {len(test_df_enc)}")

    print("Обучение XGBoost (objective=MAE, sample_weight=calculate_minute)...")
    pred, _ = train_and_predict(train_df, test_df_enc, feats)
    print("  Готово")

    print("Формирование датафрейма для дашборда...")
    df_dash = test_df_orig.copy()
    df_dash["fact_predict"] = pred
    dash_cols = ["resist_id", "division_title", "operation_id", "date", "month", "year", "fact_value", "fact_predict", "fact_fts"]
    df_dash = df_dash[[c for c in dash_cols if c in df_dash.columns]]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dashboard_input = OUTPUT_DIR / "forecast_input_xgb_mae.xlsx"
    df_dash.to_excel(dashboard_input, index=False)
    print(f"  Сохранено: {dashboard_input}")

    output_path = Path(args.output) if args.output else OUTPUT_DIR / "forecast_dashboard_xgb_mae.xlsx"
    if output_path.suffix not in (".xlsx", ".xls"):
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Сборка дашборда...")
    from build_metrics_dashboard_simple import build_dashboard
    build_dashboard(dashboard_input, output_path=output_path, forecast_col="fact_predict")
    print(f"Дашборд сохранён: {output_path}")


if __name__ == "__main__":
    main()
