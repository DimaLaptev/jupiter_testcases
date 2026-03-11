"""
Комбинированный прогноз: разные конфигурации для разных resist_id.

Маршрутизация по resist_id:
  - [31, 59, 195] → xgb_hyperparams (n=1500, depth=8, lr=0.05, sample_weight=calculate_minute)
  - [88]          → xgb_sqrt       (n=1000, depth=6, lr=0.1, sample_weight=sqrt)
  - [47, 49, 84, 128, 159, 161] и остальные → xgb_log1p (n=1000, depth=6, lr=0.1, sample_weight=log1p)

Пайплайн: загрузка CSV → feature engineering → train/test (тест = 2025)
→ обучение 3 моделей → комбинированный прогноз по resist_id → Excel дашборд.

Использование:
    python run_forecast_combined.py
    python run_forecast_combined.py --output data/processed/forecast_combined_dashboard.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from run_forecast_xgb_sqrt import (
    FEATURE_COLS,
    OUTPUT_DIR,
    TARGET_COL,
    load_and_prepare_data,
    prepare_train_test,
)

RESIST_HYPERPARAMS = [31, 59, 195]
RESIST_SQRT = [88]
RESIST_LOG1P = [47, 49, 84, 128, 159, 161]
# Остальные resist_id — тоже log1p


def _train_hyperparams(train_df, test_df, feats):
    from xgboost import XGBRegressor
    X_train, X_test = train_df[feats], test_df[feats]
    y_train = train_df[TARGET_COL]
    cm = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    sw = np.maximum(cm.values.astype(float), 0)
    model = XGBRegressor(
        n_estimators=1500, max_depth=8, learning_rate=0.05,
        objective="reg:absoluteerror", random_state=42, verbosity=0,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, test_df[TARGET_COL])],
              sample_weight=sw, verbose=False)
    return np.maximum(model.predict(X_test), 0)


def _train_sqrt(train_df, test_df, feats):
    from xgboost import XGBRegressor
    X_train, X_test = train_df[feats], test_df[feats]
    y_train = train_df[TARGET_COL]
    cm = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    sw = np.sqrt(np.maximum(cm.values.astype(float), 0.1))
    model = XGBRegressor(
        n_estimators=1000, max_depth=6, learning_rate=0.1,
        objective="reg:absoluteerror", random_state=42, verbosity=0,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, test_df[TARGET_COL])],
              sample_weight=sw, verbose=False)
    return np.maximum(model.predict(X_test), 0)


def _train_log1p(train_df, test_df, feats):
    from xgboost import XGBRegressor
    X_train, X_test = train_df[feats], test_df[feats]
    y_train = train_df[TARGET_COL]
    cm = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    sw = np.log1p(np.maximum(cm.values.astype(float), 0.1))
    model = XGBRegressor(
        n_estimators=1000, max_depth=6, learning_rate=0.1,
        objective="reg:absoluteerror", random_state=42, verbosity=0,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, test_df[TARGET_COL])],
              sample_weight=sw, verbose=False)
    return np.maximum(model.predict(X_test), 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Комбинированный прогноз (hyperparams/sqrt/log1p по resist_id) → дашборд"
    )
    parser.add_argument("--output", "-o", default=None, help="Путь к выходному xlsx дашборда")
    args = parser.parse_args()

    print("Загрузка и подготовка данных...")
    df = load_and_prepare_data()
    print(f"  Данных: {len(df)} строк")

    print("Разбиение train/test по году...")
    train_df, test_df_enc, test_df_orig, feats = prepare_train_test(df)
    print(f"  Train: {len(train_df)}, Test: {len(test_df_enc)}")

    test_resist = test_df_orig["resist_id"].values

    print("Обучение модели hyperparams (resist_id 31, 59, 195)...")
    pred_hyperparams = _train_hyperparams(train_df, test_df_enc, feats)

    print("Обучение модели sqrt (resist_id 88)...")
    pred_sqrt = _train_sqrt(train_df, test_df_enc, feats)

    print("Обучение модели log1p (resist_id 47,49,84,128,159,161 и остальные)...")
    pred_log1p = _train_log1p(train_df, test_df_enc, feats)

    mask_hyperparams = np.isin(test_resist, RESIST_HYPERPARAMS)
    mask_sqrt = np.isin(test_resist, RESIST_SQRT)
    mask_log1p = ~mask_hyperparams & ~mask_sqrt

    pred_final = np.empty(len(test_resist), dtype=float)
    pred_final[mask_hyperparams] = pred_hyperparams[mask_hyperparams]
    pred_final[mask_sqrt] = pred_sqrt[mask_sqrt]
    pred_final[mask_log1p] = pred_log1p[mask_log1p]

    print("Формирование датафрейма для дашборда...")
    df_dash = test_df_orig.copy()
    df_dash["fact_predict"] = pred_final
    dash_cols = [
        "resist_id", "division_title", "operation_id", "date",
        "month", "year", "fact_value", "fact_predict", "fact_fts",
    ]
    df_dash = df_dash[[c for c in dash_cols if c in df_dash.columns]]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dashboard_input = OUTPUT_DIR / "forecast_input_combined.xlsx"
    df_dash.to_excel(dashboard_input, index=False)
    print(f"  Сохранено: {dashboard_input}")

    output_path = Path(args.output) if args.output else OUTPUT_DIR / "forecast_dashboard_combined.xlsx"
    if output_path.suffix not in (".xlsx", ".xls"):
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Сборка дашборда...")
    from build_metrics_dashboard_simple import build_dashboard
    build_dashboard(dashboard_input, output_path=output_path, forecast_col="fact_predict")


if __name__ == "__main__":
    main()
