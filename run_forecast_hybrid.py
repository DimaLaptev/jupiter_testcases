"""
Прогноз: гибридная модель (block12_hybrid).

Для крупных операций (lag_1 >= 50) и непроблемных resist_id — block9_sample_weight_sqrt.
Для мелких операций (lag_1 < 50) в resist_id 31, 49, 159, 195 — отдельная модель,
обученная только на (resist_id in FOCUS, fact_value < 50).

Пайплайн: загрузка → feature engineering → train/test → 2 модели → комбинированный прогноз
→ Excel дашборд.

Использование:
    python run_forecast_hybrid.py
    python run_forecast_hybrid.py --output data/processed/forecast_hybrid_dashboard.xlsx
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

FOCUS_RESIST_IDS = [31, 49, 159, 195]


def train_xgb(X_train, y_train, X_test, y_test, sample_weight, **kwargs):
    from xgboost import XGBRegressor
    params = dict(
        n_estimators=kwargs.get("n_estimators", 1000),
        max_depth=kwargs.get("max_depth", 6),
        learning_rate=kwargs.get("learning_rate", 0.1),
        objective="reg:absoluteerror",
        random_state=42,
        verbosity=0,
    )
    model = XGBRegressor(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        sample_weight=sample_weight,
        verbose=False,
    )
    return model


def main():
    parser = argparse.ArgumentParser(
        description="Прогноз гибрид (block9 + спецмодель для мелких FOCUS) → дашборд"
    )
    parser.add_argument("--output", "-o", default=None, help="Путь к выходному xlsx дашборда")
    args = parser.parse_args()

    print("Загрузка и подготовка данных...")
    df = load_and_prepare_data()
    print(f"  Данных: {len(df)} строк")

    last_year = df["year"].max()
    train_orig = df[df["year"] < last_year].copy()
    test_orig = df[df["year"] == last_year].copy()

    print("Разбиение train/test по году...")
    train_df, test_df_enc, test_df_orig, feats = prepare_train_test(df)
    print(f"  Train: {len(train_df)}, Test: {len(test_df_enc)}")

    X_train = train_df[feats]
    X_test = test_df_enc[feats]
    y_train = train_df[TARGET_COL]
    y_test = test_df_enc[TARGET_COL]

    cm = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    sw_base = np.sqrt(np.maximum(cm, 0.1))

    print("Обучение базовой модели (block9 sqrt)...")
    model_base = train_xgb(X_train, y_train.values, X_test, y_test.values, sw_base)
    pred_base = np.maximum(model_base.predict(X_test), 0)

    mask_small_focus_train = (
        train_orig["resist_id"].isin(FOCUS_RESIST_IDS).values
        & (train_df[TARGET_COL].values < 50)
    )
    if np.sum(mask_small_focus_train) >= 5:
        print("Обучение спецмодели для мелких FOCUS...")
        X_small = train_df.loc[mask_small_focus_train, feats]
        y_small = train_df.loc[mask_small_focus_train, TARGET_COL]
        cm_small = train_df.loc[mask_small_focus_train, "calculate_minute"].fillna(cm.mean())
        sw_small = np.sqrt(np.maximum(cm_small, 0.1))
        model_small = train_xgb(X_small, y_small.values, X_test, y_test.values, sw_small)
        pred_small = np.maximum(model_small.predict(X_test), 0)
    else:
        print("  Спецмодель пропущена (мало данных), используется базовая")
        pred_small = pred_base.copy()

    mask_use_small = (
        test_orig["resist_id"].isin(FOCUS_RESIST_IDS).values
        & (test_orig["lag_1"].values < 50)
    )
    pred_final = pred_base.copy()
    pred_final[mask_use_small] = pred_small[mask_use_small]
    print("  Готово")

    print("Формирование датафрейма для дашборда...")
    df_dash = test_df_orig.copy()
    df_dash["fact_predict"] = pred_final
    dash_cols = ["resist_id", "division_title", "operation_id", "date", "month", "year", "fact_value", "fact_predict", "fact_fts"]
    df_dash = df_dash[[c for c in dash_cols if c in df_dash.columns]]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dashboard_input = OUTPUT_DIR / "forecast_input_hybrid.xlsx"
    df_dash.to_excel(dashboard_input, index=False)
    print(f"  Сохранено: {dashboard_input}")

    output_path = Path(args.output) if args.output else OUTPUT_DIR / "forecast_dashboard_hybrid.xlsx"
    if output_path.suffix not in (".xlsx", ".xls"):
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Сборка дашборда...")
    from build_metrics_dashboard_simple import build_dashboard
    build_dashboard(dashboard_input, output_path=output_path, forecast_col="fact_predict")
    print(f"Дашборд сохранён: {output_path}")


if __name__ == "__main__":
    main()
