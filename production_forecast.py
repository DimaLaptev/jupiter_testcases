"""
Модуль production-прогноза по логике predict_operation_count.py (ML_FORECAST_SUMMARY.md).
Prophet / ExponentialSmoothing / скользящее среднее / среднее в зависимости от длины истории.
"""

import warnings
import numpy as np
import pandas as pd

# Опциональные зависимости
try:
    from prophet import Prophet
    HAS_PROPHET = True
except ImportError:
    HAS_PROPHET = False

try:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    HAS_ETS = True
except ImportError:
    HAS_ETS = False


def calc_mape_production(actual: np.ndarray, predicted: np.ndarray) -> float:
    """MAPE = mean(abs((actual - predicted)/actual))*100. actual != 0."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mask = actual != 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask]) * 100))


def drop_leading_zeros(series: pd.Series) -> pd.Series:
    """Удаление ведущих нулей до первого ненулевого значения."""
    if series.empty:
        return series
    vals = series.values
    non_zero = np.where(vals != 0)[0]
    if len(non_zero) == 0:
        return series
    first_non_zero = int(non_zero[0])
    return series.iloc[first_non_zero:].copy()


def _forecast_prophet(series: pd.Series, steps: int = 4) -> np.ndarray:
    """Prophet: future_df на steps месяцев, yhat."""
    if not HAS_PROPHET:
        return np.full(steps, np.nan)
    if len(series) < 2:
        return np.full(steps, float(series.mean()) if len(series) == 1 else np.nan)
    df_train = pd.DataFrame({"ds": series.index, "y": series.values})
    df_train["ds"] = pd.to_datetime(df_train["ds"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = Prophet(yearly_seasonality=True)
        m.fit(df_train)
    future = m.make_future_dataframe(periods=steps, freq="MS")
    forecast = m.predict(future)
    pred = forecast["yhat"].tail(steps).values
    return pred


def _forecast_ets(series: pd.Series, steps: int = 4) -> np.ndarray:
    """ExponentialSmoothing: seasonal_periods=12, trend='add', seasonal='add'."""
    if not HAS_ETS:
        return np.full(steps, np.nan)
    n = len(series)
    if n < 24:
        return np.full(steps, np.nan)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ExponentialSmoothing(
                series.values,
                seasonal_periods=12,
                trend="add",
                seasonal="add",
            )
            fit = model.fit()
            pred = fit.forecast(steps=steps)
        return np.asarray(pred, dtype=float)
    except Exception:
        return np.full(steps, np.nan)


def _forecast_ma(series: pd.Series, window: int = 3) -> float:
    """Скользящее среднее по последним window наблюдениям."""
    if len(series) < window:
        return float(series.mean()) if len(series) > 0 else 0.0
    return float(series.tail(window).mean())


def _forecast_average(series: pd.Series) -> float:
    """Среднее по всему ряду."""
    if len(series) == 0:
        return 0.0
    return float(series.mean())


def forecast_production_one_series(
    series: pd.Series,
    steps: int = 4,
    variant: str = "vanilla",
) -> np.ndarray:
    """
    Прогноз на steps шагов по логике production.
    variant: "vanilla" | "prophet_always" | "ets_more"
    """
    series = drop_leading_zeros(series)
    n = len(series)

    if n == 0:
        return np.full(steps, 0.0)

    # 1–6: среднее
    if n <= 6:
        avg = _forecast_average(series)
        return np.full(steps, max(0.0, avg))

    # 7–11: скользящее среднее
    if n <= 11:
        ma = _forecast_ma(series, window=3)
        return np.full(steps, max(0.0, ma))

    # 12–23: Prophet (вариант B — без дополнения случайными точками)
    if n <= 23:
        if HAS_PROPHET:
            pred = _forecast_prophet(series, steps)
        else:
            ma = _forecast_ma(series, window=min(6, n))
            pred = np.full(steps, max(0.0, ma))
        return np.maximum(pred, 0.0)

    # 24–29: Prophet (или ETS при ets_more)
    if n <= 29:
        if variant == "ets_more" and HAS_ETS:
            pred = _forecast_ets(series, steps)
        elif variant == "prophet_always" or HAS_PROPHET:
            pred = _forecast_prophet(series, steps)
        else:
            pred = _forecast_ma(series, window=6)
            pred = np.full(steps, max(0.0, pred))
        return np.maximum(pred, 0.0)

    # ≥30: Prophet vs ETS, выбор лучшего по MAPE (vanilla)
    if variant == "prophet_always":
        if HAS_PROPHET:
            pred = _forecast_prophet(series, steps)
        else:
            pred = _forecast_ma(series, window=6)
            pred = np.full(steps, max(0.0, pred))
        return np.maximum(pred, 0.0)

    if variant == "ets_more":
        if HAS_ETS:
            pred = _forecast_ets(series, steps)
        elif HAS_PROPHET:
            pred = _forecast_prophet(series, steps)
        else:
            pred = _forecast_ma(series, window=6)
            pred = np.full(steps, max(0.0, pred))
        return np.maximum(pred, 0.0)

    # vanilla: Prophet vs ETS по MAPE
    if HAS_PROPHET and HAS_ETS and n >= 24:
        last_n = min(4, n - 1)
        if last_n >= 1:
            hist = series.iloc[:-last_n]
            actual_last = series.iloc[-last_n:].values
            pred_p = _forecast_prophet(hist, steps=last_n)
            pred_e = _forecast_ets(hist, steps=last_n)
            mape_p = calc_mape_production(actual_last, pred_p[:last_n])
            mape_e = calc_mape_production(actual_last, pred_e[:last_n])
            if mape_p <= mape_e:
                pred = _forecast_prophet(series, steps)
            else:
                pred = _forecast_ets(series, steps)
        else:
            pred = _forecast_prophet(series, steps)
    elif HAS_PROPHET:
        pred = _forecast_prophet(series, steps)
    elif HAS_ETS and n >= 24:
        pred = _forecast_ets(series, steps)
    else:
        ma = _forecast_ma(series, window=6)
        pred = np.full(steps, max(0.0, ma))

    return np.maximum(pred, 0.0)


def run_production_experiment(
    df: pd.DataFrame,
    last_year: int,
    variant: str = "vanilla",
) -> np.ndarray:
    """
    Прогноз по test (last_year) для каждой строки. Expanding window.
    Возвращает массив предсказаний в порядке строк test_df.
    """
    train_df = df[df["year"] < last_year].copy()
    test_df = df[df["year"] == last_year].copy().reset_index(drop=True)

    if test_df.empty:
        return np.array([])

    all_data = pd.concat([train_df, test_df], ignore_index=True)
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

        test_rows = grp[grp["year"] == last_year]
        for _, row in test_rows.iterrows():
            ym = pd.Timestamp(year=int(row["year"]), month=int(row["month"]), day=1)
            hist = series_full[series_full.index < ym]
            if len(hist) == 0:
                pred_val = 0.0
            else:
                hist_series = hist.copy()
                hist_series = hist_series[~hist_series.index.duplicated(keep="last")]
                hist_series = hist_series.sort_index()
                pred_arr = forecast_production_one_series(
                    hist_series, steps=4, variant=variant
                )
                pred_val = float(pred_arr[0]) if len(pred_arr) > 0 else 0.0
            pred_dict[(rid, oid, int(row["month"]))] = pred_val

    return np.array([
        pred_dict[(r["resist_id"], r["operation_id"], r["month"])]
        for _, r in test_df.iterrows()
    ])
