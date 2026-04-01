"""
Логика прогноза количества операций по скринам tz/code_ml_forecast (predict_operation_count.py).

Исходные изображения в репозитории отсутствуют; текст восстановлен по memory/ML_FORECAST_SUMMARY.md
и memory/forecast_architecture.md (имена классов и опечатки как в оригинале: PredictOparationCount,
_addition_siries_of_random_values).
"""

from __future__ import annotations

import json
import warnings
from typing import Any, Callable, Dict, List, Mapping, Optional, Union

import numpy as np
import pandas as pd

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


OperationLike = Union[int, Any]


def calc_mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """MAPE = mean(abs((actual - predicted) / actual)) * 100; только actual != 0."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mask = actual != 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask]) * 100))


class PredictOparationCount:
    """Прогноз fact_value по операциям (operations) для resist (id модели)."""

    DATE_FROM = "2022-12-31"

    def __init__(
        self,
        get_history_rows: Optional[Callable[[Any], List[Mapping[str, Any]]]] = None,
    ) -> None:
        """
        get_history_rows(resist) — сырой ответ БД для _format_data (как ResistParameterCalculateHistory).
        Если None, используется пустой список (predict вернёт {} без данных).
        """
        self.get_history_rows = get_history_rows
        self._query_override: Optional[List[Mapping[str, Any]]] = None

    def _create_query_history_params(self, resist: Any) -> List[Mapping[str, Any]]:
        if self._query_override is not None:
            return list(self._query_override)
        if self.get_history_rows is not None:
            return list(self.get_history_rows(resist))
        return []

    def _format_data(
        self,
        operations: List[OperationLike],
        query: List[Mapping[str, Any]],
    ) -> Dict[Any, Dict[pd.Timestamp, float]]:
        """
        Из записей истории извлекает по каждой operation fact_value в разрезе периодов.
        Упрощённая схема: каждый элемент query содержит 'period', 'operation_parameter' (dict/list).
        """
        op_ids = {getattr(op, "pk", op) for op in operations}
        out: Dict[Any, Dict[pd.Timestamp, float]] = {oid: {} for oid in op_ids}

        for row in query:
            period = row.get("period")
            if period is None:
                continue
            pdt = pd.to_datetime(period)
            if hasattr(pdt, "to_pydatetime"):
                pdt = pd.Timestamp(pdt)
            op_param = row.get("operation_parameter") or {}
            if isinstance(op_param, str):
                try:
                    op_param = json.loads(op_param)
                except Exception:
                    op_param = {}
            if isinstance(op_param, list):
                for chunk in op_param:
                    if not isinstance(chunk, dict):
                        continue
                    oid = chunk.get("operation_id", chunk.get("id"))
                    if oid not in out:
                        continue
                    fv = chunk.get("fact_value")
                    if fv is None:
                        continue
                    out[oid][pdt.normalize()] = float(fv)
            elif isinstance(op_param, dict):
                for oid in op_ids:
                    if str(oid) in op_param:
                        sub = op_param[str(oid)]
                    elif oid in op_param:
                        sub = op_param[oid]
                    else:
                        continue
                    if isinstance(sub, dict) and "fact_value" in sub:
                        out[oid][pdt.normalize()] = float(sub["fact_value"])
        return out

    def _delete_null_value(self, series: pd.Series) -> pd.Series:
        """Удаление ведущих нулей до первого ненулевого значения."""
        if series.empty:
            return series
        vals = series.values
        non_zero = np.where(vals != 0)[0]
        if len(non_zero) == 0:
            return series
        first_non_zero = int(non_zero[0])
        return series.iloc[first_non_zero:].copy()

    def _addition_siries_of_random_values(
        self, series: pd.Series, rng: np.random.Generator | None = None
    ) -> pd.Series:
        """
        Дополнение ряда синтетикой: копии с датами ~год назад и шумом от -20% до +20%,
        пока длина < 24 (см. forecast_architecture.md).
        """
        s = series.sort_index().copy()
        rng = np.random.default_rng() if rng is None else rng
        while len(s) < 24:
            shifted_idx = s.index - pd.DateOffset(years=1)
            noise = rng.uniform(0.8, 1.2, size=len(s))
            synth = pd.Series(s.values * noise, index=shifted_idx)
            s = pd.concat([synth, s]).sort_index()
            s = s[~s.index.duplicated(keep="last")]
        return s

    def _forecast_prophet(self, series: pd.Series, steps: int = 4) -> np.ndarray:
        if not HAS_PROPHET or len(series) < 2:
            return np.full(steps, np.nan)
        df_train = pd.DataFrame({"ds": pd.to_datetime(series.index), "y": series.values})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = Prophet(
                yearly_seasonality=False,
                seasonality_mode="additive",
                n_changepoints=10,
            )
            m.add_seasonality(name="yearly", period=12, fourier_order=5)
            m.fit(df_train)
            future = m.make_future_dataframe(periods=steps, freq="MS")
            forecast = m.predict(future)
        return forecast["yhat"].tail(steps).values.astype(float)

    def _forecast_ets(self, series: pd.Series, steps: int = 4) -> np.ndarray:
        if not HAS_ETS or len(series) < 24:
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

    def _moving_average_tail(self, series: pd.Series, window: int = 4) -> float:
        if len(series) == 0:
            return 0.0
        if len(series) < window:
            return float(series.mean())
        kernel = np.ones(window) / window
        conv = np.convolve(series.values.astype(float), kernel, mode="valid")
        return float(conv[-1])

    def _start_forecast(self, series: pd.Series, steps: int = 4) -> np.ndarray:
        """Ветвление по длине очищенной истории (как на скринах)."""
        n = len(series)
        if n == 0:
            return np.array([])

        if n < 7:
            v = float(series.mean()) if n > 0 else 0.0
            return np.full(steps, max(0.0, v))

        if n < 12:
            ma = self._moving_average_tail(series, window=4)
            return np.full(steps, max(0.0, ma))

        if n < 24:
            aug = self._addition_siries_of_random_values(series)
            if HAS_PROPHET:
                pred = self._forecast_prophet(aug, steps)
            else:
                pred = np.full(steps, max(0.0, float(series.tail(min(6, n)).mean())))
            return np.maximum(pred, 0.0)

        if n < 30:
            if HAS_PROPHET:
                pred = self._forecast_prophet(series, steps)
            else:
                pred = np.full(steps, max(0.0, self._moving_average_tail(series, 6)))
            return np.maximum(pred, 0.0)

        if HAS_PROPHET and HAS_ETS:
            train_size = int(n * 0.8)
            train_size = max(1, min(train_size, n - 1))
            hist = series.iloc[:train_size]
            actual = series.iloc[train_size:].values
            test_len = len(actual)
            pred_p = self._forecast_prophet(hist, steps=test_len)
            pred_e = self._forecast_ets(hist, steps=test_len)
            mape_p = calc_mape(actual, pred_p[:test_len])
            mape_e = calc_mape(actual, pred_e[:test_len])
            if not np.isfinite(mape_e) or (np.isfinite(mape_p) and mape_p <= mape_e):
                pred = self._forecast_prophet(series, steps)
            else:
                pred = self._forecast_ets(series, steps)
        elif HAS_PROPHET:
            pred = self._forecast_prophet(series, steps)
        elif HAS_ETS:
            pred = self._forecast_ets(series, steps)
        else:
            pred = np.full(steps, max(0.0, self._moving_average_tail(series, 6)))

        pred = np.where(np.isfinite(pred), pred, np.nan)
        if not np.all(np.isfinite(pred)):
            fallback = self._forecast_prophet(series, steps)
            pred = np.where(np.isfinite(pred), pred, fallback)
        return np.maximum(pred, 0.0)

    def _future_periods(self, last_index: pd.Timestamp, k: int = 4) -> pd.DatetimeIndex:
        last = pd.Timestamp(last_index).to_period("M").to_timestamp()
        return pd.date_range(last + pd.offsets.MonthBegin(1), periods=k, freq="MS")

    def predict(self, operations: List[OperationLike], resist: Any) -> Dict[Any, Dict[pd.Timestamp, float]]:
        """
        Возвращает по операции словарь период -> прогноз (4 следующих месяца от последнего факта).
        Операции с нулевой историей после очистки пропускаются.
        """
        query = self._create_query_history_params(resist)
        formatted = self._format_data(operations, query)
        result: Dict[Any, Dict[pd.Timestamp, float]] = {}

        for op in operations:
            op_id = getattr(op, "pk", op)
            hist_map = formatted.get(op_id, {})
            if not hist_map:
                continue
            series = pd.Series(hist_map)
            series.index = pd.to_datetime(series.index)
            series = series.sort_index()
            series = series[~series.index.duplicated(keep="last")]
            series = self._delete_null_value(series)
            if len(series) == 0:
                continue
            pred_arr = self._start_forecast(series, steps=4)
            if pred_arr.size == 0:
                continue
            periods = self._future_periods(series.index[-1], k=4)
            result[op_id] = {periods[i]: float(pred_arr[i]) for i in range(min(4, len(pred_arr)))}

        return result


predict_count_operation = PredictOparationCount()
