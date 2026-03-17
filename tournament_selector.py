"""
Модуль выбора победителя турнира Prophet vs ETS в production-прогнозе.

Теория 1: вместо MAPE используется взвешенная метрика (WMAE), где вес = норматив
времени операции (calculate_minute). Модель борется за точность в трудозатратах,
а не в штуках операций (forecast_architecture.md §7.2).

WMAE = sum(w_i * |actual_i - pred_i|) / sum(w_i), w_i = норматив в минутах.
Ошибка в трудозатратах: sum(|actual_i - pred_i| * w_i) — минимизируем её.
"""

from typing import Optional, Union

import numpy as np


def calc_weighted_mae(
    actual: np.ndarray,
    predicted: np.ndarray,
    weights: Optional[Union[np.ndarray, float]] = None,
) -> float:
    """
    Взвешенный MAE (Weighted MAE).

    WMAE = sum(w_i * |actual_i - pred_i|) / sum(w_i).

    - weights=None или все нули: fallback на обычный MAE.
    - weights — массив той же длины, что actual, или скаляр (одинаковый вес для всех).
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    n = len(actual)
    if n == 0:
        return 0.0

    if weights is None:
        return float(np.mean(np.abs(actual - predicted)))

    w = np.asarray(weights, dtype=float)
    if np.isscalar(w) or w.size == 1:
        w = np.full(n, float(w))
    w = np.broadcast_to(w, n)

    w_sum = np.sum(w)
    if w_sum <= 0 or not np.isfinite(w_sum):
        return float(np.mean(np.abs(actual - predicted)))

    return float(np.sum(w * np.abs(actual - predicted)) / w_sum)


def select_tournament_winner_by_wmae(
    actual: np.ndarray,
    pred_prophet: np.ndarray,
    pred_ets: np.ndarray,
    weight_minutes: Optional[float] = None,
) -> bool:
    """
    Выбор победителя турнира: Prophet vs ETS.

    Сравнение по WMAE (или MAE при weight_minutes=None).
    Returns True если Prophet лучше или равен, иначе False.
    """
    n = min(len(actual), len(pred_prophet), len(pred_ets))
    if n == 0:
        return True

    act = actual[:n]
    pp = pred_prophet[:n]
    pe = pred_ets[:n]

    if weight_minutes is not None and weight_minutes > 0 and np.isfinite(weight_minutes):
        w = np.full(n, float(weight_minutes))
        wmae_p = calc_weighted_mae(act, pp, w)
        wmae_e = calc_weighted_mae(act, pe, w)
    else:
        wmae_p = calc_weighted_mae(act, pp, None)
        wmae_e = calc_weighted_mae(act, pe, None)

    return wmae_p <= wmae_e
