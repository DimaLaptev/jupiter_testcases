"""
Production-прогноз с регрессором workDayMonth_2 (Prophet add_regressor).
Поддержка фильтрации по месяцам и resist_id для тестирования.
"""

import warnings
from typing import Optional

import numpy as np
import pandas as pd

from production_forecast import (
    HAS_ETS,
    HAS_PROPHET,
    calc_mape_production,
    drop_leading_zeros,
    _forecast_ets,
    _forecast_ma,
    _forecast_average,
)

if HAS_PROPHET:
    from prophet import Prophet


def _build_workday_lookup(df: pd.DataFrame) -> dict:
    """(resist_id, year, month) -> workDayMonth_2. fillna с глобальным средним."""
    if "workDayMonth_2" not in df.columns:
        return {}
    g = df.groupby(["resist_id", "year", "month"], dropna=False)["workDayMonth_2"].first()
    lookup = g.to_dict()
    mean_wd = float(g.mean())
    if pd.isna(mean_wd):
        mean_wd = 21.0
    return {k: (v if pd.notna(v) else mean_wd) for k, v in lookup.items()}


def _forecast_prophet_workday(
    series: pd.Series,
    workday_series: pd.Series,
    future_workday: float,
    steps: int = 4,
) -> np.ndarray:
    """Prophet с add_regressor('workDayMonth_2')."""
    if not HAS_PROPHET or len(series) < 2:
        return np.full(steps, float(series.mean()) if len(series) == 1 else np.nan)
    df_train = pd.DataFrame({"ds": series.index, "y": series.values})
    df_train["ds"] = pd.to_datetime(df_train["ds"])
    df_train["workDayMonth_2"] = workday_series.reindex(series.index).values
    if df_train["workDayMonth_2"].isna().all():
        df_train["workDayMonth_2"] = 21.0
    df_train["workDayMonth_2"] = df_train["workDayMonth_2"].fillna(21.0)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = Prophet(yearly_seasonality=True)
        m.add_regressor("workDayMonth_2", mode="multiplicative")
        m.fit(df_train)

    future = m.make_future_dataframe(periods=steps, freq="MS")
    future["workDayMonth_2"] = future_workday
    forecast = m.predict(future)
    pred = forecast["yhat"].tail(steps).values
    return pred


def forecast_production_one_series_workday(
    series: pd.Series,
    workday_series: pd.Series,
    future_workday: float,
    steps: int = 4,
    variant: str = "vanilla",
) -> np.ndarray:
    """
    Прогноз с workDayMonth_2. Prophet использует регрессор; остальная логика как в production.
    """
    series = drop_leading_zeros(series)
    n = len(series)
    workday_series = workday_series.reindex(series.index).ffill().bfill().fillna(21.0)

    if n == 0:
        return np.full(steps, 0.0)

    if n <= 6:
        avg = _forecast_average(series)
        return np.full(steps, max(0.0, avg))

    if n <= 11:
        ma = _forecast_ma(series, window=3)
        return np.full(steps, max(0.0, ma))

    if n <= 23:
        if HAS_PROPHET:
            pred = _forecast_prophet_workday(series, workday_series, future_workday, steps)
        else:
            ma = _forecast_ma(series, window=min(6, n))
            pred = np.full(steps, max(0.0, ma))
        return np.maximum(pred, 0.0)

    if n <= 29:
        if variant == "ets_more" and HAS_ETS:
            pred = _forecast_ets(series, steps)
        elif variant == "prophet_always" or HAS_PROPHET:
            pred = _forecast_prophet_workday(series, workday_series, future_workday, steps)
        else:
            pred = _forecast_ma(series, window=6)
            pred = np.full(steps, max(0.0, pred))
        return np.maximum(pred, 0.0)

    if variant == "prophet_always":
        if HAS_PROPHET:
            pred = _forecast_prophet_workday(series, workday_series, future_workday, steps)
        else:
            pred = _forecast_ma(series, window=6)
            pred = np.full(steps, max(0.0, pred))
        return np.maximum(pred, 0.0)

    if variant == "ets_more":
        if HAS_ETS:
            pred = _forecast_ets(series, steps)
        elif HAS_PROPHET:
            pred = _forecast_prophet_workday(series, workday_series, future_workday, steps)
        else:
            pred = _forecast_ma(series, window=6)
            pred = np.full(steps, max(0.0, pred))
        return np.maximum(pred, 0.0)

    # vanilla: Prophet vs ETS по MAPE
    if HAS_PROPHET and HAS_ETS and n >= 24:
        last_n = min(4, n - 1)
        if last_n >= 1:
            hist = series.iloc[:-last_n]
            hist_wd = workday_series.iloc[:-last_n]
            actual_last = series.iloc[-last_n:].values
            fw = workday_series.iloc[-1] if len(workday_series) > 0 else 21.0
            pred_p = _forecast_prophet_workday(hist, hist_wd, fw, steps=last_n)
            pred_e = _forecast_ets(hist, steps=last_n)
            mape_p = calc_mape_production(actual_last, pred_p[:last_n])
            mape_e = calc_mape_production(actual_last, pred_e[:last_n])
            if mape_p <= mape_e:
                pred = _forecast_prophet_workday(series, workday_series, future_workday, steps)
            else:
                pred = _forecast_ets(series, steps)
        else:
            pred = _forecast_prophet_workday(series, workday_series, future_workday, steps)
    elif HAS_PROPHET:
        pred = _forecast_prophet_workday(series, workday_series, future_workday, steps)
    elif HAS_ETS and n >= 24:
        pred = _forecast_ets(series, steps)
    else:
        ma = _forecast_ma(series, window=6)
        pred = np.full(steps, max(0.0, ma))

    return np.maximum(pred, 0.0)


def run_production_workday_experiment(
    df: pd.DataFrame,
    last_year: int,
    test_months: Optional[list[int]] = None,
    test_resist_ids: Optional[list[int]] = None,
    variant: str = "vanilla",
) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Production-прогноз с workDayMonth_2. Фильтрация теста:
    - test_months: None = все месяцы, иначе [1,2,3] и т.д.
    - test_resist_ids: None = все resist_id, иначе [31, 47, 49] и т.д.
    Возвращает (test_df_filtered, predictions).
    """
    workday_lookup = _build_workday_lookup(df)
    default_wd = 21.0
    if workday_lookup:
        default_wd = float(np.mean(list(workday_lookup.values())))

    train_df = df[df["year"] < last_year].copy()
    test_df_full = df[df["year"] == last_year].copy().reset_index(drop=True)

    test_df = test_df_full.copy()
    if test_months is not None:
        test_df = test_df[test_df["month"].isin(test_months)]
    if test_resist_ids is not None:
        test_df = test_df[test_df["resist_id"].isin(test_resist_ids)]
    test_df = test_df.reset_index(drop=True)

    if test_df.empty:
        return test_df, np.array([])

    all_data = pd.concat([train_df, test_df_full], ignore_index=True)
    all_data = all_data.sort_values(["resist_id", "operation_id", "year", "month"])

    pred_dict = {}
    grouped = all_data.groupby(["resist_id", "operation_id"])

    for (rid, oid), grp in grouped:
        grp = grp.sort_values(["year", "month"])
        dates = pd.to_datetime(
            dict(year=grp["year"], month=grp["month"], day=1),
            errors="coerce",
        )
        series_full = pd.Series(grp["fact_value"].values, index=dates)
        series_full.index = series_full.index.to_period("M").to_timestamp()

        workday_vals = grp["workDayMonth_2"] if "workDayMonth_2" in grp.columns else pd.Series([default_wd] * len(grp))
        workday_series_full = pd.Series(workday_vals.values, index=series_full.index)
        workday_series_full = workday_series_full.fillna(default_wd)

        test_rows = grp[grp["year"] == last_year]
        for _, row in test_rows.iterrows():
            month_val = int(row["month"])
            if test_months is not None and month_val not in test_months:
                continue
            if test_resist_ids is not None and int(row["resist_id"]) not in test_resist_ids:
                continue

            ym = pd.Timestamp(year=int(row["year"]), month=month_val, day=1)
            hist = series_full[series_full.index < ym]
            hist_wd = workday_series_full[workday_series_full.index < ym]

            if len(hist) == 0:
                pred_val = 0.0
            else:
                hist_series = hist.copy()
                hist_series = hist_series[~hist_series.index.duplicated(keep="last")]
                hist_series = hist_series.sort_index()
                hist_wd = hist_wd[~hist_wd.index.duplicated(keep="last")]
                hist_wd = hist_wd.reindex(hist_series.index).ffill().bfill().fillna(default_wd)

                future_wd = workday_lookup.get((rid, last_year, month_val), default_wd)

                pred_arr = forecast_production_one_series_workday(
                    hist_series,
                    hist_wd,
                    future_wd,
                    steps=4,
                    variant=variant,
                )
                pred_val = float(pred_arr[0]) if len(pred_arr) > 0 else 0.0

            pred_dict[(rid, oid, month_val)] = pred_val

    preds = np.array([
        pred_dict[(r["resist_id"], r["operation_id"], r["month"])]
        for _, r in test_df.iterrows()
    ])
    return test_df, preds
