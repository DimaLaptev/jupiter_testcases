"""Вспомогательные функции для ноутбука 21: построение df и FEATURE_SETS по resist_id."""
from __future__ import annotations

import pandas as pd

from scripts.calc_lag_features import add_calc_shift_lags, calc_lag_columns_for_sets


def build_df_and_feature_sets(
    df_model39: pd.DataFrame,
    rid: int,
    *,
    calc_whitelist: list[str],
    lag_features: list[str],
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    df = df_model39[df_model39["resist_id"] == rid].copy()
    df["op_code"] = df["operation_id"].astype("category").cat.codes

    group = df.groupby("operation_id")
    df["lag_1"] = group["fact_value"].shift(1)
    df["lag_12"] = group["fact_value"].shift(12)
    df["rolling_mean_3"] = group["fact_value"].transform(
        lambda s: s.shift(1).rolling(window=3, min_periods=1).mean()
    )
    num_cols = df.select_dtypes(include=["number"]).columns
    df[num_cols] = df[num_cols].fillna(0)
    df = df.infer_objects(copy=False)

    miss = df.isnull().sum()
    miss = miss[miss > 0]
    if len(miss) > 0:
        df = df.fillna(0)

    df, _lag_calc_cols, calc_keys_used = add_calc_shift_lags(df, drop_scalar_calc=True)
    b_flat, c_flat = calc_lag_columns_for_sets(calc_keys_used, whitelist=calc_whitelist)

    base_core = ["op_code", "month", "year", "workDayMonth_2"]
    base_with_minute = base_core + ["calculate_minute"]
    feature_sets: dict[str, list[str]] = {
        "A": base_core,
        "B": base_with_minute + b_flat,
        "C": base_with_minute + c_flat,
        "A+lags": base_core + lag_features,
        "B+lags": base_with_minute + b_flat + lag_features,
        "C+lags": base_with_minute + c_flat + lag_features,
    }
    return df, feature_sets
