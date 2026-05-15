# -*- coding: utf-8 -*-
"""Локальный тест optim_2 production-прогноза через ``df_model39`` и ``CsvHistoryRepository``.

Пайплайн (pipeline) совпадает с ``optim_2_predict_operation_count_v2.py``: тренеры (trainers)
и ``SERIES_CONFIGS`` из ``optim_2_tsa_per_series_nb37_trainers`` (копия baseline без ``neuralforecast``).

История в том же формате, что и в ``test_predict_operation_count_v2`` — класс
``CsvHistoryRepository`` импортируется оттуда (окно дат как у production
``HistoryRepository.fetch``: ``period > 2022-12-31``, ``period < now_period``).

Файл ``optim_2_predict_operation_count_v2.py`` не дублируется и не меняется.
"""

from __future__ import annotations

from typing import Optional

from scripts.test_predict_operation_count_v2 import CsvHistoryRepository

from scripts.optim_2_predict_operation_count_v2 import (
    ConfigDispatcher,
    HISTORY_START_DATE,
    OperationHistoryCleaner,
    PredictOparationCountV2 as _Optim2PredictFacade,
    ProductionForecaster,
    WalkForwardSelector,
)


class PredictOparationCountV2(_Optim2PredictFacade):
    """Фасад прогноза с обязательным ``CsvHistoryRepository`` (локальный CSV-режим)."""

    def __init__(
        self,
        repository: CsvHistoryRepository,
        cleaner: Optional[OperationHistoryCleaner] = None,
        dispatcher: Optional[ConfigDispatcher] = None,
        selector: Optional[WalkForwardSelector] = None,
        forecaster: Optional[ProductionForecaster] = None,
    ) -> None:
        if not isinstance(repository, CsvHistoryRepository):
            raise TypeError("нужен CsvHistoryRepository(df_model39)")
        super().__init__(
            repository=repository,
            cleaner=cleaner,
            dispatcher=dispatcher,
            selector=selector,
            forecaster=forecaster,
        )
