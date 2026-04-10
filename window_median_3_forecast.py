"""
Автономный модуль: рекурсивный прогноз WindowMedian-3 (как train_window_median_per_series в ноутбуках).

Не импортирует другие модули проекта. Внешние зависимости: numpy, pandas.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Union

import numpy as np
import pandas as pd

OperationLike = Union[int, Any]


class WindowMedian_3:
    """
    Прогноз fact_value по операциям (operations) для resist (id модели):
    рекурсивная медиана (recursive median) по последним WINDOW_SIZE наблюдениям,
    горизонт 4 месяца (month start), как в predict у типового production-пайплайна.
    """

    WINDOW_SIZE = 3

    def __init__(
        self,
        get_history_rows: Optional[Callable[[Any], List[Mapping[str, Any]]]] = None,
    ) -> None:
        """
        get_history_rows(resist) — сырой ответ БД для _format_data.
        Если None, используется пустой список (start вернёт {} без данных).
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

    def _forecast_window_median(
        self, series: pd.Series, steps: int = 4, *, window_size: Optional[int] = None
    ) -> np.ndarray:
        """Рекурсивный прогноз: на каждом шаге median последних window_size значений history."""
        ws = self.WINDOW_SIZE if window_size is None else window_size
        if len(series) == 0:
            return np.array([])
        history = list(series.values.astype(float))
        fc: List[float] = []
        for _ in range(steps):
            tail = history[-ws:] if len(history) >= ws else history
            if len(tail) == 0:
                fc.append(0.0)
            else:
                fc.append(float(np.median(tail)))
            history.append(fc[-1])
        return np.maximum(np.asarray(fc, dtype=float), 0.0)

    def _future_periods(self, last_index: pd.Timestamp, k: int = 4) -> pd.DatetimeIndex:
        last = pd.Timestamp(last_index).to_period("M").to_timestamp()
        return pd.date_range(last + pd.offsets.MonthBegin(1), periods=k, freq="MS")

    def start(self, operations: List[OperationLike], resist: Any) -> Dict[Any, Dict[pd.Timestamp, float]]:
        """
        Возвращает по операции словарь период -> прогноз (4 следующих месяца от последнего факта).
        Операции без факта или с нулевой историей после очистки пропускаются.
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
            pred_arr = self._forecast_window_median(series, steps=4)
            if pred_arr.size == 0:
                continue
            periods = self._future_periods(series.index[-1], k=4)
            result[op_id] = {periods[i]: float(pred_arr[i]) for i in range(min(4, len(pred_arr)))}

        return result
