"""
Иерархический прогноз с CatBoost для долей операций (Этап 2).

Этап 1: Прогноз нагрузки (load %) — ExponentialSmoothing (без изменений).
Этап 2: Прогноз долей — CatBoostRegressor (одна глобальная модель на все операции).
Этап 3: Финальный расчёт fact_predict — без изменений.

Признаки для CatBoost (доли): resist_id, operation_name, month, quarter,
lag_1_share, lag_2_share, lag_3_share, rolling_mean_3_share.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    HAS_ETS = True
except ImportError:
    HAS_ETS = False

try:
    from catboost import CatBoostRegressor
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False


_MIN_SEASONAL_LEN = 12
FORECAST_STEPS = 4

SHARE_FEATURES = [
    "resist_id",
    "operation_name",
    "month",
    "quarter",
    "lag_1_share",
    "lag_2_share",
    "lag_3_share",
    "rolling_mean_3_share",
]

CAT_FEATURES = ["resist_id", "operation_name"]


def _forecast_exponential_smoothing(series: pd.Series, steps: int = FORECAST_STEPS) -> np.ndarray:
    """Прогноз нагрузки (load %) — ExponentialSmoothing (Этап 1)."""
    if series.empty:
        return np.full(steps, np.nan)

    n = len(series)
    vals = np.asarray(series.values, dtype=float)
    finite = vals[np.isfinite(vals)]

    if n == 1:
        return np.full(steps, float(vals[0]))

    if not HAS_ETS:
        fallback = float(np.mean(finite)) if len(finite) > 0 else np.nan
        return np.full(steps, fallback)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if n >= _MIN_SEASONAL_LEN:
                model = ExponentialSmoothing(
                    vals, trend="add", seasonal="add", seasonal_periods=12,
                )
            else:
                model = ExponentialSmoothing(vals, trend="add", seasonal=None)
            fit = model.fit()
            pred = fit.forecast(steps=steps)
        return np.asarray(pred, dtype=float)
    except Exception:
        return np.full(steps, float(np.nanmean(vals)) if np.any(np.isfinite(vals)) else np.nan)


def _get_last_values_per_resist(df: pd.DataFrame, resist_ids: list) -> pd.DataFrame:
    """Последние staff_count и work_hours по resist_id."""
    subset = df[df["resist_id"].isin(resist_ids)][
        ["resist_id", "period", "staff_count", "work_hours_in_month"]
    ]
    idx = subset.groupby("resist_id")["period"].idxmax()
    return subset.loc[idx][["resist_id", "staff_count", "work_hours_in_month"]].reset_index(drop=True)


def _generate_future_periods(last_period: pd.Timestamp, steps: int) -> pd.DatetimeIndex:
    return pd.date_range(start=last_period + pd.DateOffset(months=1), periods=steps, freq="MS")


def _work_hours_for_month(period: pd.Timestamp, hours_per_day: float = 8.0) -> float:
    ru_calendar = {
        (2023, 1): 17, (2023, 2): 18, (2023, 3): 22, (2023, 4): 20, (2023, 5): 20, (2023, 6): 21,
        (2023, 7): 21, (2023, 8): 23, (2023, 9): 21, (2023, 10): 22, (2023, 11): 21, (2023, 12): 21,
        (2024, 1): 17, (2024, 2): 20, (2024, 3): 20, (2024, 4): 21, (2024, 5): 20, (2024, 6): 19,
        (2024, 7): 23, (2024, 8): 22, (2024, 9): 21, (2024, 10): 23, (2024, 11): 21, (2024, 12): 21,
        (2025, 1): 17, (2025, 2): 20, (2025, 3): 21, (2025, 4): 22, (2025, 5): 18, (2025, 6): 20,
        (2025, 7): 23, (2025, 8): 21, (2025, 9): 22, (2025, 10): 23, (2025, 11): 19, (2025, 12): 22,
    }
    n_days = ru_calendar.get((period.year, period.month))
    if n_days is None:
        start = period.replace(day=1)
        end = start + pd.offsets.MonthEnd(0)
        n_days = len(pd.bdate_range(start, end))
    return float(n_days) * hours_per_day


def _build_share_features(share_df: pd.DataFrame) -> pd.DataFrame:
    """
    Строит признаки для CatBoost по долям.
    Лаги и rolling — per (resist_id, operation_name), shift(1) чтобы не было утечки.
    """
    share_df = share_df.sort_values(["resist_id", "operation_name", "period"]).copy()
    share_df["month"] = pd.to_datetime(share_df["period"]).dt.month
    share_df["quarter"] = (share_df["month"] - 1) // 3 + 1

    def add_lags_rolling(grp: pd.DataFrame) -> pd.DataFrame:
        s = grp["share"]
        grp = grp.copy()
        grp["lag_1_share"] = s.shift(1)
        grp["lag_2_share"] = s.shift(2)
        grp["lag_3_share"] = s.shift(3)
        grp["rolling_mean_3_share"] = s.shift(1).rolling(3, min_periods=1).mean()
        return grp

    feat_df = share_df.groupby(["resist_id", "operation_name"], group_keys=False).apply(add_lags_rolling)
    feat_df = feat_df.dropna(subset=["share"])
    for c in ["lag_1_share", "lag_2_share", "lag_3_share", "rolling_mean_3_share"]:
        feat_df[c] = feat_df[c].fillna(0.0)
    return feat_df


def _predict_shares_catboost(
    feat_df: pd.DataFrame,
    last_share_by_op: dict[tuple, pd.Series],
    last_periods: dict,
    resist_ids: list,
    op_by_resist: dict,
) -> dict[tuple, dict[pd.Timestamp, float]]:
    """
    Прогноз долей CatBoost.
    Возвращает: result[(rid, op_name)][period] = predicted_share.
    Каждый resist_id имеет свой last_period и свои 4 будущих месяца.
    """
    if not HAS_CATBOOST or feat_df.empty:
        return {}

    X_cols = [c for c in SHARE_FEATURES if c in feat_df.columns]
    if not X_cols:
        return {}

    X_train = feat_df[X_cols].copy()
    y_train = feat_df["share"].values

    for c in CAT_FEATURES:
        if c in X_train.columns:
            X_train[c] = X_train[c].astype(str)

    model = CatBoostRegressor(
        iterations=500,
        depth=6,
        learning_rate=0.1,
        loss_function="RMSE",
        verbose=0,
        allow_writing_files=False,
    )
    model.fit(X_train, y_train, cat_features=CAT_FEATURES if CAT_FEATURES[0] in X_train.columns else [])

    result: dict[tuple, dict[pd.Timestamp, float]] = {}
    for rid in resist_ids:
        future_periods = _generate_future_periods(last_periods[rid], FORECAST_STEPS)
        for op_name in op_by_resist.get(rid, []):
            key = (rid, op_name)
            last_s = last_share_by_op.get(key, pd.Series(dtype=float))
            if last_s.empty:
                lag1, lag2, lag3, roll3 = 0.0, 0.0, 0.0, 0.0
            else:
                vals = last_s.values
                n = len(vals)
                lag1 = float(vals[-1]) if n >= 1 else 0.0
                lag2 = float(vals[-2]) if n >= 2 else 0.0
                lag3 = float(vals[-3]) if n >= 3 else 0.0
                roll3 = float(np.mean(vals[-3:])) if n >= 1 else lag1

            result[key] = {}
            for period in future_periods:
                row = {
                    "resist_id": str(rid),
                    "operation_name": str(op_name),
                    "month": period.month,
                    "quarter": (period.month - 1) // 3 + 1,
                    "lag_1_share": lag1,
                    "lag_2_share": lag2,
                    "lag_3_share": lag3,
                    "rolling_mean_3_share": roll3,
                }
                X_pred = pd.DataFrame([row])
                pred = model.predict(X_pred)[0]
                result[key][period] = float(pred) if np.isfinite(pred) and pred >= 0 else 0.0

    return result


def generate_hierarchical_forecast_catboost(
    historical_df: pd.DataFrame,
    *,
    diagnose_outliers: bool = False,
) -> pd.DataFrame:
    """
    Иерархический прогноз: Этап 1 (ETS) + Этап 2 (CatBoost для долей) + Этап 3.
    """
    required_cols = {
        "period", "resist_id", "operation_name", "fact_value", "norm_value",
        "staff_count", "work_hours_in_month",
    }
    if historical_df.empty:
        return pd.DataFrame(columns=["period", "resist_id", "operation_name", "fact_predict_hierarchical"])

    missing = required_cols - set(historical_df.columns)
    if missing:
        raise ValueError(f"Отсутствуют колонки: {missing}")

    df = historical_df.copy()
    df["period"] = pd.to_datetime(df["period"])
    df = df.sort_values(["resist_id", "operation_name", "period"])

    # --- Этап 1: Прогноз нагрузки ---
    df["operation_hours"] = df["fact_value"] * df["norm_value"]
    total_hours = (
        df.groupby(["resist_id", "period"], as_index=False)["operation_hours"]
        .sum()
        .rename(columns={"operation_hours": "total_hours"})
    )
    load_df = df[["resist_id", "period", "staff_count", "work_hours_in_month"]].drop_duplicates()
    load_df = load_df.merge(total_hours, on=["resist_id", "period"])
    load_df["capacity"] = load_df["staff_count"] * load_df["work_hours_in_month"]
    load_df["load_percent"] = np.where(
        load_df["capacity"] > 0,
        (load_df["total_hours"] / load_df["capacity"]) * 100.0,
        np.nan,
    )
    load_df = load_df[["resist_id", "period", "load_percent"]].dropna(subset=["load_percent"])

    if diagnose_outliers and not load_df.empty:
        print("\n--- Анализ выбросов load_percent ---")
        print(load_df["load_percent"].describe(percentiles=[0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]))
        problem = load_df[load_df["load_percent"] > 200]
        if not problem.empty:
            pr = problem["resist_id"].unique()
            print(f"Подразделения с нагрузкой > 200%: {len(pr)} — {pr[:10].tolist()}")

    load_forecasts: dict = {}
    last_periods: dict = {}
    for rid, grp in load_df.groupby("resist_id"):
        grp = grp.sort_values("period")
        series = grp.set_index("period")["load_percent"]
        last_periods[rid] = series.index.max()
        load_forecasts[rid] = _forecast_exponential_smoothing(series, steps=FORECAST_STEPS)

    if not load_forecasts:
        return pd.DataFrame(columns=["period", "resist_id", "operation_name", "fact_predict_hierarchical"])

    resist_ids = list(load_forecasts.keys())
    last_values = _get_last_values_per_resist(df, resist_ids)

    # --- Этап 2: Прогноз долей (CatBoost) ---
    df = df.merge(total_hours.rename(columns={"total_hours": "total_resist_hours"}), on=["resist_id", "period"])
    df["share"] = np.where(
        df["total_resist_hours"] > 0,
        df["operation_hours"] / df["total_resist_hours"],
        0.0,
    )
    share_df = df[["resist_id", "operation_name", "period", "share", "norm_value"]].copy()

    feat_df = _build_share_features(share_df)
    last_share_by_op: dict[tuple, pd.Series] = {}
    for (rid, op_name), grp in share_df.groupby(["resist_id", "operation_name"]):
        grp = grp.sort_values("period")
        last_share_by_op[(rid, op_name)] = grp["share"]

    op_by_resist = share_df.groupby("resist_id")["operation_name"].unique().to_dict()
    norm_lookup = (
        df.sort_values("period")
        .groupby(["resist_id", "operation_name"], as_index=False)["norm_value"]
        .last()
    )
    norm_lookup = norm_lookup.set_index(["resist_id", "operation_name"])["norm_value"].to_dict()

    share_forecasts: dict[tuple, dict] = {}
    if HAS_CATBOOST and not feat_df.empty:
        share_forecasts = _predict_shares_catboost(
            feat_df, last_share_by_op, last_periods, resist_ids, op_by_resist,
        )

    # Fallback: ExponentialSmoothing при отсутствии CatBoost
    if not share_forecasts and op_by_resist:
        for (rid, op_name), grp in share_df.groupby(["resist_id", "operation_name"]):
            grp = grp.sort_values("period")
            series = grp.set_index("period")["share"]
            pred_arr = _forecast_exponential_smoothing(series, steps=FORECAST_STEPS)
            future_periods = _generate_future_periods(last_periods[rid], FORECAST_STEPS)
            share_forecasts[(rid, op_name)] = {
                period: float(pred_arr[i]) if i < len(pred_arr) and np.isfinite(pred_arr[i]) and pred_arr[i] >= 0 else 0.0
                for i, period in enumerate(future_periods)
            }

    # --- Этап 3: Финальный расчёт ---
    forecast_rows: list[dict] = []
    for rid in resist_ids:
        last_period = last_periods[rid]
        future_periods = _generate_future_periods(last_period, FORECAST_STEPS)
        load_pred = load_forecasts[rid]
        last_row = last_values[last_values["resist_id"] == rid]
        if last_row.empty:
            continue
        staff = float(last_row["staff_count"].iloc[0])
        if staff <= 0:
            continue

        operations = op_by_resist.get(rid, [])
        for step_idx, period in enumerate(future_periods):
            work_hours = _work_hours_for_month(period)
            capacity = staff * work_hours
            if capacity <= 0:
                continue

            load_pct = load_pred[step_idx]
            if not np.isfinite(load_pct) or load_pct < 0:
                load_pct = 0.0
            predicted_total_hours = (load_pct / 100.0) * capacity

            raw_shares: dict[str, float] = {}
            for op_name in operations:
                pred_by_period = share_forecasts.get((rid, op_name), {})
                s = pred_by_period.get(period, 0.0)
                raw_shares[op_name] = float(s) if np.isfinite(s) and s >= 0 else 0.0

            total_raw = sum(raw_shares.values())
            if total_raw > 0:
                norm_shares = {k: v / total_raw for k, v in raw_shares.items()}
            else:
                n_ops = len(raw_shares) or 1
                norm_shares = {k: 1.0 / n_ops for k in raw_shares}

            for op_name, norm_share in norm_shares.items():
                norm_val = norm_lookup.get((rid, op_name), np.nan)
                norm_val = float(norm_val) if np.isfinite(norm_val) and norm_val > 0 else np.nan
                if not np.isfinite(norm_val) or norm_val <= 0:
                    fact_pred = np.nan
                else:
                    predicted_operation_hours = predicted_total_hours * norm_share
                    fact_pred = predicted_operation_hours / norm_val

                forecast_rows.append({
                    "period": period,
                    "resist_id": rid,
                    "operation_name": op_name,
                    "fact_predict_hierarchical": fact_pred,
                })

    if not forecast_rows:
        return pd.DataFrame(columns=["period", "resist_id", "operation_name", "fact_predict_hierarchical"])

    forecast_df = pd.DataFrame(forecast_rows)
    forecast_df["fact_predict_hierarchical"] = forecast_df["fact_predict_hierarchical"].clip(lower=0.0)
    return forecast_df
