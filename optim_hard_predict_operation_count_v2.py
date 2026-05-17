# -*- coding: utf-8 -*-
"""Production прогноз количества операций.

Замена ``predict_operation_count.py``:
переиспользует production-набор per-series моделей
``optim_hard_tsa_per_series_nb37_trainers`` (без ``neuralforecast``)

Бизнес-логика:

1. История (history) операций тянется из ``ResistParameterCalculateHistory``
   за период с ``2022-12-31`` до начала текущего месяца.
2. Для каждой ``operation_id`` режутся ведущие нули до первого
   ненулевого ``fact_value``.
3. **Walk-forward hold-out** на хвосте истории: последние ``HOLDOUT_SIZE`` месяцев
   служат тестом, всё остальное — train. По метрике «Качество» выбирается
   победившая конфигурация per ``operation_id``.
4. Winner рефитится на полной истории и строит прогноз на
   ``FORECAST_HORIZON`` месяцев вперёд (h=4, freq=``MS``).
5. Выход — словарь per ``operation_id``: история + прогнозные точки + ключ
   ``"model"`` с именем выбранной конфигурации (см. ``predict`` ниже).

Вход совпадает с ``PredictOparationCount.predict(operations, resist)``.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from scripts.optim_hard_tsa_per_series_nb37_trainers import (
    SERIES_CONFIGS,
    cleanup_memory,
    train_auto_arima_per_series,
    train_ets_per_series,
    train_glm_count_per_series,
    train_local_supervised_per_series,
    train_sarimax_per_series,
    train_statsforecast_intermittent_per_series,
    train_statsforecast_per_series,
    train_theta_per_series,
    train_ucm_per_series,
    train_window_median_per_series,
)

try:
    from app_history.models import ResistParameterCalculateHistory 
except ImportError:  
    ResistParameterCalculateHistory = None 


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Бизнес-константы (business constants)
HOLDOUT_SIZE: int = 6
FORECAST_HORIZON: int = 4
MIN_LEN_FOR_TOURNAMENT: int = 12  # >= HOLDOUT_SIZE + 6, чтобы оставалось ≥6 на train
MIN_LEN_FOR_WINDOW_MEDIAN: int = 7

FALLBACK_AVERAGE_LABEL: str = "Fallback-Average"
FALLBACK_WINDOW_MEDIAN_3_LABEL: str = "Fallback-WindowMedian-3"
MODEL_KEY: str = "model"
DATE_FMT: str = "%Y-%m-%d"
HISTORY_START_DATE: datetime = datetime(2022, 12, 31)


def allowed_configs() -> Dict[str, dict]:
    """Все production-конфиги (production configs) из ``SERIES_CONFIGS``."""
    return dict(SERIES_CONFIGS)


# ---------------------------------------------------------------------------
# Utility helpers


def _normalize_month(value: Any) -> pd.Timestamp:
    """Первое число месяца, timezone-naive (как ``MS``)."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return pd.Timestamp(ts.to_period("M").to_timestamp())


def _format_date_key(value: Any) -> str:
    """Унифицированный строковый ключ ``YYYY-MM-DD`` для итогового словаря."""
    return _normalize_month(value).strftime(DATE_FMT)


def _calc_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Tuple[float, float, float]:
    """Точность/Стабильность/Качество."""
    y_true = np.asarray(y_true, dtype=float).ravel()
    y_pred = np.asarray(y_pred, dtype=float).ravel()
    if len(y_true) != len(y_pred) or len(y_true) == 0:
        return 0.0, 0.0, 0.0

    df = pd.DataFrame({"fact_value": y_true, "fact_predict": y_pred})
    for col in ("fact_value", "fact_predict"):
        df[col] = (
            pd.to_numeric(df[col], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0)
        )
    df["abs_error"] = (df["fact_value"] - df["fact_predict"]).abs()
    acc = np.where(
        df["fact_value"] == 0,
        np.where(df["fact_predict"] == 0, 100.0, 0.0),
        np.clip(100.0 - df["abs_error"] / df["fact_value"] * 100.0, 0, 100),
    )
    df["accuracy_pct"] = np.round(acc, 2)

    tochnost = round(float(df["accuracy_pct"].mean()), 2)
    if tochnost == 0 or pd.isna(tochnost):
        stab = 0.0
    else:
        mean_acc = float(df["accuracy_pct"].mean())
        std_acc = float(df["accuracy_pct"].std(ddof=0))
        cv = std_acc / mean_acc if mean_acc != 0 else 0.0
        stab = round(max(0.0, (1 - cv)) * 100, 2)

    kachestvo = 0.0
    if tochnost + stab != 0:
        kachestvo = round(2 * tochnost * stab / (tochnost + stab), 2)
    return tochnost, stab, kachestvo


def _add_nb37_features(df: pd.DataFrame, mask_train_scope: pd.Series) -> pd.DataFrame:
    """Лаги и rolling_mean_3; медиан-fill по train."""
    out = df.copy()
    out["op_code"] = out["operation_id"].astype("category").cat.codes
    group = out.groupby("operation_id")
    out["lag_1"] = group["fact_value"].shift(1)
    for k in range(2, 7):
        out[f"lag_{k}"] = group["fact_value"].shift(k)
    out["lag_12"] = group["fact_value"].shift(12)
    out["rolling_mean_3"] = group["fact_value"].transform(
        lambda s: s.shift(1).rolling(window=3, min_periods=1).mean()
    )
    half_year_lag_cols = [f"lag_{i}" for i in range(1, 7)]
    train_med = out.loc[mask_train_scope].groupby("operation_id")["fact_value"].median()
    for col in half_year_lag_cols:
        out[col] = out[col].fillna(out["operation_id"].map(train_med)).fillna(0.0)
    num_cols = out.select_dtypes(include=["number"]).columns
    out[num_cols] = out[num_cols].fillna(0)
    out = out.infer_objects()
    if out.isnull().any().any():
        out = out.fillna(0)
    return out


# ---------------------------------------------------------------------------
# Service classes


class ConfigDispatcher:
    """Диспетчер семейств (families) моделей по ``cfg['fn']``.

    Маршрутизирует вызов в соответствующий ``train_*_per_series`` тренер из
    ``optim_hard_tsa_per_series_nb37_trainers``.
    """

    def dispatch(
        self,
        df: pd.DataFrame,
        mask_train: pd.Series,
        mask_test: pd.Series,
        rid: int,
        config_name: str,
        cfg: dict,
        warning_rows: list,
    ) -> np.ndarray:
        fn = cfg.get("fn")
        if fn == "ets":
            return train_ets_per_series(
                df, mask_train, mask_test, rid, config_name, warning_rows,
                trend=cfg["trend"],
                damped_trend=cfg["damped_trend"],
                seasonal=cfg.get("seasonal"),
                seasonal_periods=cfg.get("seasonal_periods"),
                ets_fit_kwargs=cfg.get("ets_fit_kwargs"),
            )
        if fn == "theta":
            return train_theta_per_series(
                df, mask_train, mask_test, rid, config_name, warning_rows,
                theta_deseasonalize=cfg.get("theta_deseasonalize", True),
                theta_method=cfg.get("theta_method", "auto"),
                theta_period=cfg.get("theta_period", 12),
            )
        if fn == "sarimax":
            return train_sarimax_per_series(
                df, mask_train, mask_test, rid, config_name, warning_rows,
                sarimax_preset=cfg.get("sarimax_preset", "default"),
                sarimax_order=cfg.get("sarimax_order"),
                sarimax_seasonal_order=cfg.get("sarimax_seasonal_order"),
                sarimax_fit_kwargs=cfg.get("sarimax_fit_kwargs"),
            )
        if fn == "auto_arima":
            return train_auto_arima_per_series(
                df, mask_train, mask_test, rid, config_name, warning_rows,
                auto_arima_kwargs=cfg.get("auto_arima_kwargs"),
            )
        if fn == "statsforecast":
            return train_statsforecast_per_series(
                df, mask_train, mask_test, rid, config_name, warning_rows,
                sf_model_name=cfg["sf_model"],
                season_len=cfg["season_len"],
                sf_window_size=cfg.get("sf_window_size"),
                sf_tsb_kwargs=cfg.get("sf_tsb_kwargs"),
            )
        if fn == "statsforecast_intermittent":
            return train_statsforecast_intermittent_per_series(
                df, mask_train, mask_test, rid, config_name, warning_rows,
                sf_model_name=cfg["sf_model"],
                season_len=cfg["season_len"],
                sf_tsb_kwargs=cfg.get("sf_tsb_kwargs"),
            )
        if fn == "ucm":
            return train_ucm_per_series(
                df, mask_train, mask_test, rid, config_name, warning_rows,
                ucm_level=cfg.get("ucm_level", "local linear trend"),
                ucm_stochastic_level=cfg.get("ucm_stochastic_level"),
                ucm_stochastic_seasonal=cfg.get("ucm_stochastic_seasonal"),
            )
        if fn == "local_supervised":
            return train_local_supervised_per_series(
                df, mask_train, mask_test, rid, config_name, warning_rows,
                sk_model=cfg["sk_model"],
                local_sk_params=cfg.get("local_sk_params"),
            )
        if fn == "glm_count":
            return train_glm_count_per_series(
                df, mask_train, mask_test, rid, config_name, warning_rows,
                family_name=cfg["family"],
                glm_fit_kwargs=cfg.get("glm_fit_kwargs"),
                glm_use_regularized=cfg.get("glm_use_regularized", False),
                glm_reg_alpha=cfg.get("glm_reg_alpha", 0.1),
                glm_reg_l1_wt=cfg.get("glm_reg_l1_wt", 0.0),
            )
        if fn == "window_median":
            return train_window_median_per_series(
                df, mask_train, mask_test, rid, config_name, warning_rows,
                window_size=int(cfg["window_size"]),
            )
        raise ValueError(f"неизвестный fn={fn!r} для {config_name!r}")


class HistoryRepository:
    """Доступ (access) к ``ResistParameterCalculateHistory``.

    Метод ``fetch`` возвращает QuerySet/iterable записей — формат идентичен
    ``_create_query_history_params``.
    """

    def fetch(self, resist: str) -> Iterable[Mapping[str, Any]]:
        if ResistParameterCalculateHistory is None:
            raise ImportError(
                "Нужен app_history.models.ResistParameterCalculateHistory"
            )
        now_period = (datetime.today().replace(day=1) - timedelta(days=1)).replace(day=1)
        return (
            ResistParameterCalculateHistory.objects
            .filter(resist=int(resist), period__gt=HISTORY_START_DATE, period__lt=now_period)
            .values("period", "operation_parameter")
            .order_by("period")
        )


class OperationHistoryCleaner:
    """Сбор и очистка истории per ``operation_id``: format + drop_leading_zeros."""

    @staticmethod
    def format_data(
        operations: List[Any],
        query_history_params: Iterable[Mapping[str, Any]],
    ) -> Dict[Any, Dict[Any, float]]:
        """Заполняет ``oper_data[op][period] = fact_value`` из истории.
        """
        oper_data: Dict[Any, Dict[Any, float]] = {op: {} for op in operations}
        for row in query_history_params:
            period = row.get("period")
            param = row.get("operation_parameter") or {}
            if period is None or not isinstance(param, dict):
                continue
            for oper in oper_data.keys():
                payload = param.get(str(oper))
                if not payload:
                    continue
                oper_data[oper][period] = payload.get("fact_value")
        return oper_data

    @staticmethod
    def drop_leading_zeros(
        oper_data: Dict[Any, Dict[Any, float]],
    ) -> Dict[Any, Dict[Any, float]]:
        """Срез ведущих нулей до первого ненулевого ``fact_value``.
        """
        valid: Dict[Any, Dict[Any, float]] = {}
        for op_id, data in oper_data.items():
            pairs = list(data.items())
            i_valid: Optional[int] = None
            for i, (_, value) in enumerate(pairs):
                try:
                    if value is not None and float(value) > 0:
                        i_valid = i
                        break
                except (TypeError, ValueError):
                    continue
            if i_valid is not None:
                valid[op_id] = dict(pairs[i_valid:])
        return valid

    @staticmethod
    def to_dataframe(
        history: Mapping[Any, float],
        operation_id: Any,
        resist_id: int,
    ) -> pd.DataFrame:
        """Per-operation словарь → нормализованный ``pd.DataFrame``.

        Колонки: ``resist_id, operation_id, date, fact_value, year, month``.
        """
        rows: List[dict] = []
        for period, value in history.items():
            ts = _normalize_month(period)
            try:
                fv = float(value) if value is not None else np.nan
            except (TypeError, ValueError):
                fv = np.nan
            rows.append({
                "resist_id": resist_id,
                "operation_id": operation_id,
                "date": ts,
                "fact_value": fv,
                "year": int(ts.year),
                "month": int(ts.month),
            })
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df = df.drop_duplicates(["operation_id", "date"], keep="last")
        df = df.sort_values(["operation_id", "date"]).reset_index(drop=True)
        df["fact_value"] = pd.to_numeric(df["fact_value"], errors="coerce")
        return df


class WalkForwardSelector:
    """Выбор winner-конфигурации per ``operation_id``.

    Walk-forward hold-out: на хвосте истории длиной ``HOLDOUT_SIZE`` считается
    «Качество», лучший конфиг определяется по убыванию метрики;
    """

    def __init__(
        self,
        dispatcher: ConfigDispatcher,
        configs: Optional[Mapping[str, dict]] = None,
        holdout_size: int = HOLDOUT_SIZE,
        min_len_for_tournament: int = MIN_LEN_FOR_TOURNAMENT,
        min_len_for_window_median: int = MIN_LEN_FOR_WINDOW_MEDIAN,
    ) -> None:
        self._dispatcher = dispatcher
        self._configs = dict(configs) if configs is not None else allowed_configs()
        self._cfg_order = list(self._configs.keys())
        self._holdout = int(holdout_size)
        self._min_tour = int(min_len_for_tournament)
        self._min_wm = int(min_len_for_window_median)

    def select(self, df_op: pd.DataFrame, resist_id: int) -> str:
        """Возвращает имя конфигурации для прогноза по операции.

        Лестница длин (length ladder):
        - ``N < MIN_LEN_FOR_WINDOW_MEDIAN`` → ``Fallback-Average``;
        - ``MIN_LEN_FOR_WINDOW_MEDIAN ≤ N < MIN_LEN_FOR_TOURNAMENT``
          → ``Fallback-WindowMedian-3``;
        - ``N ≥ MIN_LEN_FOR_TOURNAMENT`` → walk-forward tournament по Качеству.
        """
        n = len(df_op)
        if n < self._min_wm:
            return FALLBACK_AVERAGE_LABEL
        if n < self._min_tour:
            return FALLBACK_WINDOW_MEDIAN_3_LABEL

        df_sorted = df_op.sort_values("date").reset_index(drop=True)
        cutoff_idx = n - self._holdout
        mask_train = pd.Series(False, index=df_sorted.index)
        mask_train.iloc[:cutoff_idx] = True
        mask_test = ~mask_train

        if mask_train.sum() < 6 or mask_test.sum() == 0:
            return FALLBACK_WINDOW_MEDIAN_3_LABEL

        df_feat = _add_nb37_features(df_sorted, mask_train)
        y_true = df_sorted.loc[mask_test, "fact_value"].astype(float).values

        best_q: float = -1.0
        best_name: Optional[str] = None
        for cfg_name in self._cfg_order:
            cfg = self._configs[cfg_name]
            try:
                y_hat = self._dispatcher.dispatch(
                    df_feat, mask_train, mask_test, int(resist_id),
                    cfg_name, cfg, warning_rows=[],
                )
            except Exception as exc:
                logger.debug(
                    "selector: пропуск config=%s op=%s rid=%s: %s",
                    cfg_name, df_sorted["operation_id"].iloc[0], resist_id, exc,
                )
                continue
            _, _, kachestvo = _calc_metrics(y_true, np.asarray(y_hat, dtype=float))
            if kachestvo > best_q or (
                abs(kachestvo - best_q) < 1e-9 and (best_name is None or cfg_name < best_name)
            ):
                best_q = kachestvo
                best_name = cfg_name
            cleanup_memory()

        if best_name is None:
            return FALLBACK_WINDOW_MEDIAN_3_LABEL
        return best_name


class ProductionForecaster:
    """Финальный прогноз на ``FORECAST_HORIZON`` месяцев вперёд."""

    def __init__(
        self,
        dispatcher: ConfigDispatcher,
        configs: Optional[Mapping[str, dict]] = None,
        horizon: int = FORECAST_HORIZON,
    ) -> None:
        self._dispatcher = dispatcher
        self._configs = dict(configs) if configs is not None else allowed_configs()
        self._horizon = int(horizon)

    def forecast(
        self,
        df_op: pd.DataFrame,
        resist_id: int,
        winner_config: str,
    ) -> Dict[str, float]:
        """Возвращает словарь ``{date_str: forecast_value}`` длиной ``horizon``."""
        if df_op.empty:
            return {}
        df_sorted = df_op.sort_values("date").reset_index(drop=True)
        last_date = df_sorted["date"].iloc[-1]
        future_dates = pd.date_range(
            start=_normalize_month(last_date) + pd.DateOffset(months=1),
            periods=self._horizon,
            freq="MS",
        )

        if winner_config in (FALLBACK_AVERAGE_LABEL, FALLBACK_WINDOW_MEDIAN_3_LABEL):
            y_hat = self._fallback_forecast(df_sorted, winner_config)
        else:
            y_hat = self._series_forecast(df_sorted, resist_id, winner_config)

        return {
            future_dates[i].strftime(DATE_FMT): self._round_nonneg(y_hat[i])
            for i in range(self._horizon)
        }

    @staticmethod
    def _round_nonneg(value: float) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not np.isfinite(v) or v < 0:
            return 0.0
        return round(v, 2)

    def _fallback_forecast(self, df_sorted: pd.DataFrame, winner: str) -> np.ndarray:
        y_hist = df_sorted["fact_value"].astype(float).fillna(0.0).values
        if len(y_hist) == 0:
            return np.zeros(self._horizon, dtype=float)
        if winner == FALLBACK_AVERAGE_LABEL:
            const = float(np.mean(y_hist))
            return np.full(self._horizon, max(0.0, const), dtype=float)
        # Fallback-WindowMedian-3: рекурсивное окно
        history = list(y_hist)
        out: List[float] = []
        for _ in range(self._horizon):
            tail = history[-3:] if len(history) >= 3 else history
            v = float(np.median(tail)) if tail else 0.0
            out.append(max(0.0, v))
            history.append(out[-1])
        return np.asarray(out, dtype=float)

    def _series_forecast(
        self, df_sorted: pd.DataFrame, resist_id: int, winner: str,
    ) -> np.ndarray:
        if winner not in self._configs:
            logger.warning(
                "forecaster: winner=%r отсутствует в configs; fallback на WindowMedian-3",
                winner,
            )
            return self._fallback_forecast(df_sorted, FALLBACK_WINDOW_MEDIAN_3_LABEL)

        op_id = df_sorted["operation_id"].iloc[0]
        last_date = _normalize_month(df_sorted["date"].iloc[-1])
        future_rows = []
        for k in range(1, self._horizon + 1):
            ts = last_date + pd.DateOffset(months=k)
            future_rows.append({
                "resist_id": int(resist_id),
                "operation_id": op_id,
                "date": pd.Timestamp(ts),
                "fact_value": np.nan,
                "year": int(ts.year),
                "month": int(ts.month),
            })
        df_full = pd.concat(
            [df_sorted, pd.DataFrame(future_rows)],
            ignore_index=True,
        )
        df_full = df_full.sort_values(["operation_id", "date"]).reset_index(drop=True)
        mask_train = df_full["fact_value"].notna()
        mask_test = ~mask_train
        if mask_test.sum() == 0:
            return np.zeros(self._horizon, dtype=float)

        df_feat = _add_nb37_features(df_full, mask_train)
        try:
            y_hat = self._dispatcher.dispatch(
                df_feat, mask_train, mask_test, int(resist_id),
                winner, self._configs[winner], warning_rows=[],
            )
        except Exception as exc:
            logger.warning(
                "forecaster: ошибка дисп. для winner=%s op=%s rid=%s: %s; fallback",
                winner, op_id, resist_id, exc,
            )
            return self._fallback_forecast(df_sorted, FALLBACK_WINDOW_MEDIAN_3_LABEL)
        finally:
            cleanup_memory()
        y_arr = np.asarray(y_hat, dtype=float).ravel()
        if y_arr.shape[0] != self._horizon:
            y_arr = np.resize(y_arr, self._horizon)
        return y_arr


# ---------------------------------------------------------------------------
# Фасад


class PredictOparationCountV2:
    """Production-фасад прогноза количества операций per ``operation_id``.
       Импорт такой же ``predict_count_operation``.
    """

    def __init__(
        self,
        repository: Optional[HistoryRepository] = None,
        cleaner: Optional[OperationHistoryCleaner] = None,
        dispatcher: Optional[ConfigDispatcher] = None,
        selector: Optional[WalkForwardSelector] = None,
        forecaster: Optional[ProductionForecaster] = None,
    ) -> None:
        self._repository = repository or HistoryRepository()
        self._cleaner = cleaner or OperationHistoryCleaner()
        self._dispatcher = dispatcher or ConfigDispatcher()
        self._configs = allowed_configs()
        self._selector = selector or WalkForwardSelector(
            self._dispatcher, configs=self._configs,
        )
        self._forecaster = forecaster or ProductionForecaster(
            self._dispatcher, configs=self._configs,
        )

    def predict(self, operations: List[Any], resist: str) -> Dict[Any, Dict[str, Any]]:
        """Прогноз количества операций.

        Args:
            operations: список ``id`` операций для прогноза.
            resist: ``id`` модели нагрузки (resist).

        Returns:
            ``{operation_id: {"YYYY-MM-DD": float, ..., "model": str}}``;
            операции с пустой историей пропускаются.
        """
        query_rows = self._repository.fetch(resist)
        oper_data = self._cleaner.format_data(operations, query_rows)
        oper_data_valid = self._cleaner.drop_leading_zeros(oper_data)

        result: Dict[Any, Dict[str, Any]] = {}
        try:
            rid = int(resist)
        except (TypeError, ValueError):
            rid = 0
        for op_id, history in oper_data_valid.items():
            if not history:
                continue
            df_op = self._cleaner.to_dataframe(history, op_id, rid)
            if df_op.empty:
                continue

            try:
                winner = self._selector.select(df_op, rid)
            except Exception as exc:
                logger.exception(
                    "predict: ошибка selector op=%s rid=%s: %s; fallback WM-3",
                    op_id, rid, exc,
                )
                winner = FALLBACK_WINDOW_MEDIAN_3_LABEL
            try:
                forecast_map = self._forecaster.forecast(df_op, rid, winner)
            except Exception as exc:
                logger.exception(
                    "predict: ошибка forecaster op=%s rid=%s winner=%s: %s",
                    op_id, rid, winner, exc,
                )
                forecast_map = {}

            result[op_id] = self._merge_history_and_forecast(history, forecast_map, winner)
        return result

    @staticmethod
    def _merge_history_and_forecast(
        history: Mapping[Any, float],
        forecast_map: Mapping[str, float],
        winner: str,
    ) -> Dict[str, Any]:
        """История + прогноз в единый словарь со строковыми (``YYYY-MM-DD``) ключами."""
        merged: Dict[str, Any] = {}
        for period, value in history.items():
            try:
                fv = float(value) if value is not None else 0.0
            except (TypeError, ValueError):
                fv = 0.0
            merged[_format_date_key(period)] = fv
        for date_key, value in forecast_map.items():
            merged[date_key] = float(value)
        merged[MODEL_KEY] = winner
        return merged


predict_count_operation = PredictOparationCountV2()