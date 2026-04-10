"""
WindowMedian-3.

Вызов: ``window_median_3_operation.start_forecast(operations, resist)``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

try:
    from app_history.models import ResistParameterCalculateHistory
except ImportError:
    ResistParameterCalculateHistory = None


class WindowMedian_3:
    """Предсказывает значения количества операций."""

    WINDOW_SIZE = 3

    def start_forecast(self, operations: list, resist: str) -> dict:
        """Публичная точка входа для прогноза: `operations`, `resist`.

        Загружает историю, готовит словарь и записывает прогноз WindowMedian-3.
        """
        oper_data = {}
        for id_oper in operations:
            oper_data[id_oper] = {}

        query_history_params = self._create_query_history_params(resist)
        oper_data = self._format_data(oper_data, query_history_params)
        oper_data_valid = self._delete_null_value(oper_data)
        self._apply_window_median_forecast(oper_data_valid)
        return oper_data_valid

    def _conversions_dictionary_in_siries(self, dict_stoty_one_id: dict) -> pd.Series:
        """
        Функция преобразует словарь с историческими данными по одной операции.
        Преобразование в объект Siries необходимо для обучения модели

        Parameters
        ----------
        dict_stoty_one_id : dict
            Словарь, где ключи — даты, значения — количество операций в месяц.

        Returns
        -------
        training_data : pandas.core.series.Series
            Одномерный массив, где индекс — даты, значения — количество операций.
        """
        training_data = pd.Series(dict_stoty_one_id)
        training_data.index = pd.to_datetime(training_data.index)
        return training_data

    def _forecast_window_median(
        self, series: pd.Series, steps: int = 4, *, window_size: int | None = None
    ) -> np.ndarray:
        """Рекурсивный прогноз: на каждом шаге median последних window_size значений history."""
        ws = self.WINDOW_SIZE if window_size is None else window_size
        if len(series) == 0:
            return np.array([])
        history = list(series.values.astype(float))
        fc: list[float] = []
        for _ in range(steps):
            tail = history[-ws:] if len(history) >= ws else history
            if len(tail) == 0:
                fc.append(0.0)
            else:
                fc.append(float(np.median(tail)))
            history.append(fc[-1])
        return np.maximum(np.asarray(fc, dtype=float), 0.0)

    def _apply_window_median_forecast(self, data_operation: dict) -> None:
        """Вносит прогноз WindowMedian-3 в словари истории по операциям (после `_delete_null_value`)."""
        for _, history in data_operation.items():
            training_data = self._conversions_dictionary_in_siries(history)
            training_data = training_data.sort_index()
            training_data = training_data[~training_data.index.duplicated(keep="last")]
            if len(training_data) == 0:
                continue

            fc = self._forecast_window_median(training_data, steps=4)
            if fc.size == 0:
                continue

            last = pd.Timestamp(training_data.index[-1]).to_period("M").to_timestamp()
            periods = pd.date_range(last + pd.offsets.MonthBegin(1), periods=4, freq="MS")
            forecast = pd.Series(fc, index=periods)

            for date_in_dict, value in forecast.items():
                if isinstance(date_in_dict, datetime):
                    if value >= 0:
                        history[date_in_dict.date()] = round(value, 2)
                    else:
                        history[date_in_dict.date()] = 0
                else:
                    print(" ERROR !!! datetime !!! ")
                    print(date_in_dict, value)

    def _create_query_history_params(self, resist: str):
        """Формирует запрос для получения исторических данных по операциям до текущего отчетного периода в рамках определенной модели нагрузки.

        Args:
            resist: id модели нагрузки
        """
        if ResistParameterCalculateHistory is None:
            raise ImportError(
                "Ошибка импорта: app_history.models.ResistParameterCalculateHistory"
            )
        start_date = datetime.strptime("2022-12-31", r"%Y-%m-%d")
        now_period = (datetime.today().replace(day=1) - timedelta(days=1)).replace(
            day=1
        )
        return ResistParameterCalculateHistory.objects.filter(
            resist=int(resist),
            period__gt=start_date,
            period__lt=now_period,
        ).values("period", "operation_parameter").order_by("period")

    def _format_data(self, oper_data: dict, query_history_params) -> dict:
        """Формируем данные количества операций в разбивке по отчетным периодам для каждой отдельной операции.

        Args:
            oper_data: словарь с соперациями для заполенения историческими значениями количества операций
                в рамках каждой отдельной операции по датам
            query_history_params: Запрос для получения исторических данных параметром операций
        Return:
            dict: заполненный oper_data словарь
        """
        for data in query_history_params:
            period = data["period"]
            param = data["operation_parameter"]
            for oper in oper_data.keys():
                if param.get(str(oper)):
                    oper_data[oper][period] = param.get(str(oper)).get("fact_value")

        return oper_data

    def _delete_null_value(self, oper_data: dict) -> dict:
        """Убираем все даты с нулевыми значениями количества операций до первого не нулевого значения.

        Args:
            oper_data: словарь с количеством операций.
        Return:
            dict: очищенные данные
        """
        oper_data_valid = {}
        for oper_id, data in oper_data.items():
            pairs = list(data.items())
            i_valid = None
            for i, d in enumerate(pairs):
                if d[1] > 0:
                    i_valid = i
                    break
            if i_valid is not None:
                oper_data_valid[oper_id] = dict(pairs[i_valid:])

        return oper_data_valid


window_median_3_operation = WindowMedian_3()
