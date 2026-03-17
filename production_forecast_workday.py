"""
Production-прогноз с регрессором workDayMonth_2 (Prophet add_regressor).
Поддержка фильтрации по месяцам и resist_id для тестирования.
"""

import json
import warnings
from pathlib import Path
from typing import Any, Optional

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
    _forecast_prophet,
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
    yearly_seasonality: bool = True,
    use_regressor: bool = True,
    return_workday_contrib: bool = False,
):
    """Prophet с опциональным add_regressor('workDayMonth_2').
    return_workday_contrib=True: возвращает (pred, contrib), иначе только pred.
    contrib — вклад регрессора для первого прогнозного шага (multiplicative).
    """
    if not HAS_PROPHET or len(series) < 2:
        out = np.full(steps, float(series.mean()) if len(series) == 1 else np.nan)
        return (out, None) if return_workday_contrib else out
    df_train = pd.DataFrame({"ds": series.index, "y": series.values})
    df_train["ds"] = pd.to_datetime(df_train["ds"])
    workday_contrib_out = None
    if use_regressor:
        df_train["workDayMonth_2"] = workday_series.reindex(series.index).values
        if df_train["workDayMonth_2"].isna().all():
            df_train["workDayMonth_2"] = 21.0
        df_train["workDayMonth_2"] = df_train["workDayMonth_2"].fillna(21.0)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = Prophet(yearly_seasonality=yearly_seasonality)
        if use_regressor:
            m.add_regressor("workDayMonth_2", mode="multiplicative")
        m.fit(df_train)

    future = m.make_future_dataframe(periods=steps, freq="MS")
    if use_regressor:
        future["workDayMonth_2"] = future_workday
    forecast = m.predict(future)
    pred = forecast["yhat"].tail(steps).values
    if return_workday_contrib and use_regressor and "workDayMonth_2" in forecast.columns:
        workday_contrib_out = float(forecast["workDayMonth_2"].iloc[-steps])
    if return_workday_contrib:
        return pred, workday_contrib_out
    return pred


def _calc_quality_production(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Качество = 2 * Точность * Стабильность / (Точность + Стабильность)."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    acc = np.empty_like(actual)
    mask_zero = actual == 0
    acc[mask_zero] = np.where(predicted[mask_zero] == 0, 100.0, 0.0)
    mask_ok = ~mask_zero
    if np.any(mask_ok):
        acc[mask_ok] = np.clip(
            100.0 - np.abs(actual[mask_ok] - predicted[mask_ok]) / np.abs(actual[mask_ok]) * 100.0, 0, 100
        )
    mean_acc = float(np.mean(acc))
    if mean_acc == 0:
        return 0.0
    cv = np.std(acc, ddof=0) / mean_acc
    stab = max(0.0, (1 - cv)) * 100
    return 2 * mean_acc * stab / (mean_acc + stab)


def forecast_production_one_series_workday(
    series: pd.Series,
    workday_series: pd.Series,
    future_workday: float,
    steps: int = 4,
    variant: str = "vanilla",
    yearly_seasonality: bool = True,
    workday_only_if_n30: bool = False,
    tournament_by_quality: bool = False,
    return_workday_contrib: bool = False,
):
    """
    Прогноз с workDayMonth_2. Параметры экспериментов:
    - yearly_seasonality: False = отключить сезонность при workday (Теория 1)
    - workday_only_if_n30: True = регрессор только при n>=30 (Теория 2)
    - tournament_by_quality: True = турнир Prophet vs ETS по Quality вместо MAPE (Теория 4)
    - return_workday_contrib: возвращать (pred, contrib) для сбора статистики коэффициентов
    """
    series = drop_leading_zeros(series)
    n = len(series)
    workday_series = workday_series.reindex(series.index).ffill().bfill().fillna(21.0)
    use_regressor = not workday_only_if_n30 or n >= 30

    def _prophet_call(hist, hist_wd, fw, st, ret_contrib=False):
        if use_regressor:
            return _forecast_prophet_workday(
                hist, hist_wd, fw, steps=st,
                yearly_seasonality=yearly_seasonality,
                use_regressor=True,
                return_workday_contrib=ret_contrib,
            )
        pred = _forecast_prophet(hist, steps=st)
        return (pred, None) if ret_contrib else pred

    def _unpack_pred(p, want_contrib: bool):
        if not want_contrib:
            return (p[0] if isinstance(p, tuple) else p), None
        if isinstance(p, tuple):
            return p[0], (p[1] if len(p) > 1 else None)
        return p, None

    if n == 0:
        out = np.full(steps, 0.0)
        return (out, None) if return_workday_contrib else out

    if n <= 6:
        avg = _forecast_average(series)
        out = np.full(steps, max(0.0, avg))
        return (out, None) if return_workday_contrib else out

    if n <= 11:
        ma = _forecast_ma(series, window=3)
        out = np.full(steps, max(0.0, ma))
        return (out, None) if return_workday_contrib else out

    if n <= 23:
        if HAS_PROPHET:
            p = _prophet_call(series, workday_series, future_workday, steps, return_workday_contrib)
            pred, contrib = _unpack_pred(p, return_workday_contrib)
        else:
            ma = _forecast_ma(series, window=min(6, n))
            pred, contrib = np.full(steps, max(0.0, ma)), None
        out = np.maximum(pred, 0.0)
        return (out, contrib) if return_workday_contrib else out

    if n <= 29:
        if variant == "ets_more" and HAS_ETS:
            pred, contrib = _forecast_ets(series, steps), None
        elif variant == "prophet_always" or HAS_PROPHET:
            p = _prophet_call(series, workday_series, future_workday, steps, return_workday_contrib)
            pred, contrib = _unpack_pred(p, return_workday_contrib)
        else:
            pred, contrib = _forecast_ma(series, window=6), None
            pred = np.full(steps, max(0.0, pred))
        out = np.maximum(pred, 0.0)
        return (out, contrib) if return_workday_contrib else out

    if variant == "prophet_always":
        if HAS_PROPHET:
            p = _prophet_call(series, workday_series, future_workday, steps, return_workday_contrib)
            pred, contrib = _unpack_pred(p, return_workday_contrib)
        else:
            pred, contrib = _forecast_ma(series, window=6), None
            pred = np.full(steps, max(0.0, pred))
        out = np.maximum(pred, 0.0)
        return (out, contrib) if return_workday_contrib else out

    if variant == "ets_more":
        if HAS_ETS:
            pred, contrib = _forecast_ets(series, steps), None
        elif HAS_PROPHET:
            p = _prophet_call(series, workday_series, future_workday, steps, return_workday_contrib)
            pred, contrib = _unpack_pred(p, return_workday_contrib)
        else:
            pred, contrib = _forecast_ma(series, window=6), None
            pred = np.full(steps, max(0.0, pred))
        out = np.maximum(pred, 0.0)
        return (out, contrib) if return_workday_contrib else out

    # vanilla: Prophet vs ETS
    if HAS_PROPHET and HAS_ETS and n >= 24:
        last_n = min(4, n - 1)
        if last_n >= 1:
            hist = series.iloc[:-last_n]
            hist_wd = workday_series.iloc[:-last_n]
            actual_last = series.iloc[-last_n:].values
            fw = workday_series.iloc[-1] if len(workday_series) > 0 else 21.0
            pred_p = _prophet_call(hist, hist_wd, fw, last_n, False)
            pred_p = pred_p[0] if isinstance(pred_p, tuple) else pred_p
            pred_e = _forecast_ets(hist, steps=last_n)
            if tournament_by_quality:
                qual_p = _calc_quality_production(actual_last, pred_p[:last_n])
                qual_e = _calc_quality_production(actual_last, pred_e[:last_n])
                use_prophet = qual_p >= qual_e
            else:
                mape_p = calc_mape_production(actual_last, pred_p[:last_n])
                mape_e = calc_mape_production(actual_last, pred_e[:last_n])
                use_prophet = mape_p <= mape_e
            if use_prophet:
                p = _prophet_call(series, workday_series, future_workday, steps, return_workday_contrib)
                pred, contrib = _unpack_pred(p, return_workday_contrib)
            else:
                pred, contrib = _forecast_ets(series, steps), None
        else:
            p = _prophet_call(series, workday_series, future_workday, steps, return_workday_contrib)
            pred, contrib = _unpack_pred(p, return_workday_contrib)
    elif HAS_PROPHET:
        p = _prophet_call(series, workday_series, future_workday, steps, return_workday_contrib)
        pred, contrib = _unpack_pred(p, return_workday_contrib)
    elif HAS_ETS and n >= 24:
        pred, contrib = _forecast_ets(series, steps), None
    else:
        ma = _forecast_ma(series, window=6)
        pred, contrib = np.full(steps, max(0.0, ma)), None

    out = np.maximum(pred, 0.0)
    return (out, contrib) if return_workday_contrib else out


def run_production_workday_experiment(
    df: pd.DataFrame,
    last_year: int,
    test_months: Optional[list[int]] = None,
    test_resist_ids: Optional[list[int]] = None,
    variant: str = "vanilla",
    yearly_seasonality: bool = True,
    workday_only_if_n30: bool = False,
    tournament_by_quality: bool = False,
    collect_coeff_stats: bool = False,
    coeff_output_path: Optional[Path] = None,
) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Production-прогноз с workDayMonth_2. Фильтрация теста:
    - test_months: None = все месяцы, иначе [1,2,3] и т.д.
    - test_resist_ids: None = все resist_id, иначе [31, 47, 49] и т.д.
    - yearly_seasonality: False = отключить сезонность при workday (эксп. Теория 1)
    - workday_only_if_n30: True = регрессор только при n>=30 (эксп. Теория 2)
    - tournament_by_quality: True = турнир по Quality вместо MAPE (эксп. Теория 4)
    - collect_coeff_stats: собирать вклад workday для анализа коэффициентов
    - coeff_output_path: путь для сохранения JSON/CSV статистики (если collect_coeff_stats)
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
    coeff_records: list[dict[str, Any]] = []
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

                result = forecast_production_one_series_workday(
                    hist_series,
                    hist_wd,
                    future_wd,
                    steps=4,
                    variant=variant,
                    yearly_seasonality=yearly_seasonality,
                    workday_only_if_n30=workday_only_if_n30,
                    tournament_by_quality=tournament_by_quality,
                    return_workday_contrib=collect_coeff_stats,
                )
                if collect_coeff_stats and isinstance(result, tuple):
                    pred_arr, workday_contrib = result
                    if workday_contrib is not None:
                        coeff_records.append({
                            "resist_id": rid,
                            "operation_id": oid,
                            "month": month_val,
                            "workday_contrib": workday_contrib,
                            "n_history": len(hist_series),
                        })
                else:
                    pred_arr = result
                pred_val = float(pred_arr[0]) if len(pred_arr) > 0 else 0.0

            pred_dict[(rid, oid, month_val)] = pred_val

    if collect_coeff_stats and coeff_records and coeff_output_path:
        coeff_output_path = Path(coeff_output_path)
        coeff_output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(coeff_output_path.with_suffix(".json"), "w", encoding="utf-8") as f:
            contribs = [r["workday_contrib"] for r in coeff_records]
            summary = {
                "n_total": len(coeff_records),
                "n_negative": sum(1 for c in contribs if c < 1.0),
                "pct_negative": 100.0 * sum(1 for c in contribs if c < 1.0) / len(contribs) if contribs else 0,
                "mean_contrib": float(np.mean(contribs)) if contribs else None,
                "std_contrib": float(np.std(contribs)) if len(contribs) > 1 else None,
                "records": coeff_records[:500],
            }
            json.dump(summary, f, ensure_ascii=False, indent=2)
        pd.DataFrame(coeff_records).to_csv(coeff_output_path.with_suffix(".csv"), index=False, encoding="utf-8-sig")

    preds = np.array([
        pred_dict[(r["resist_id"], r["operation_id"], r["month"])]
        for _, r in test_df.iterrows()
    ])
    return test_df, preds
