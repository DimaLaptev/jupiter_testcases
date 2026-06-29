# -*- coding: utf-8 -*-
"""Production comparison-сервис: турнир конфигов (tournament), JSON победителей и прогноз (forecast).

История из БД через ``ResistParameterCalculateHistory`` (как в ``optim_2_predict_operation_count_v2``).
Тренеры и реестр ``SERIES_CONFIGS``: ``production_comparison_tsa_per_series_nb37_trainers``.

Точка входа (entry point): singleton ``predict_count_operation``.

- ``predict_count_operation.predict(operations, resist, comparison=False)`` — прогноз (forecast)
  по JSON победителей; формат выхода как у ``optim_2_predict_operation_count_v2``.
- ``predict_count_operation.predict(operations, resist, comparison=True)`` — турнир конфигов
  и merge-запись в JSON победителей.

``WINNER_CONFIG_JSON`` — путь к merge-JSON ``\"<rid>_<op>\": \"<config_name>\"`` (по умолчанию
текущая директория процесса: ``./comparison_winner_configs.json``).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

WINNER_CONFIG_FILENAME: str = "comparison_winner_configs.json"
WINNER_CONFIG_DIR: Path = Path(".")
WINNER_CONFIG_JSON: Path = WINNER_CONFIG_DIR / WINNER_CONFIG_FILENAME

from scripts.production_comparison_tsa_per_series_nb37_trainers import (  # noqa: E402
    FORECAST_REL_CAP,
    SERIES_CONFIGS,
    _sanitize_forecast,
    cleanup_memory,
    holdout_forecast_is_valid,
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
    ResistParameterCalculateHistory = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

HOLDOUT_SIZE: int = 6
FORECAST_HORIZON: int = 4
MIN_LEN_FOR_TOURNAMENT: int = 12
MIN_LEN_FOR_WINDOW_MEDIAN: int = 7

FALLBACK_AVERAGE_LABEL: str = "Fallback-Average"
FALLBACK_WINDOW_MEDIAN_3_LABEL: str = "Fallback-WindowMedian-3"
MODEL_KEY: str = "model"
DATE_FMT: str = "%Y-%m-%d"
HISTORY_START_DATE: datetime = datetime(2022, 12, 31)


class HistoryRepository:
    """Production: ``ResistParameterCalculateHistory`` (как в optim_2)."""

    def fetch(self, resist: str) -> Iterable[Mapping[str, Any]]:
        if ResistParameterCalculateHistory is None:
            raise ImportError(
                "Нужен app_history.models.ResistParameterCalculateHistory",
            )
        now_period = (datetime.today().replace(day=1) - timedelta(days=1)).replace(day=1)
        return (
            ResistParameterCalculateHistory.objects.filter(
                resist=int(resist),
                period__gt=HISTORY_START_DATE,
                period__lt=now_period,
            )
            .values("period", "operation_parameter")
            .order_by("period")
        )


def allowed_configs() -> Dict[str, dict]:
    return dict(SERIES_CONFIGS)


def _normalize_month(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return pd.Timestamp(ts.to_period("M").to_timestamp())


def _format_date_key(value: Any) -> str:
    return _normalize_month(value).strftime(DATE_FMT)


def _calc_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Tuple[float, float, float]:
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


def _normalize_operation_token(operation_id: Any) -> Union[int, float, str]:
    if pd.isna(operation_id):  # type: ignore[arg-type]
        return str(operation_id)
    try:
        x = float(operation_id)
        return int(x) if x == int(x) else x
    except (TypeError, ValueError):
        return str(operation_id)


def operations_discovered_from_rows(
    query_history_params: Iterable[Mapping[str, Any]],
) -> List[Any]:
    """Ключи operation_parameter из строк истории — для режима без явного списка операций."""
    seen = set()
    ordered: List[Any] = []
    for row in query_history_params:
        param = row.get("operation_parameter") or {}
        if not isinstance(param, dict):
            continue
        for k in param.keys():
            op = _normalize_operation_token(k)
            if op not in seen:
                seen.add(op)
                ordered.append(op)
    ordered.sort(key=lambda z: (str(type(z)), str(z)))
    return ordered


class ConfigDispatcher:
    """Маршрутизация семейства по ``cfg['fn']`` в ``production_comparison_tsa_*`` trainers."""

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


class OperationHistoryCleaner:
    """Сбор и очистка истории per ``operation_id``."""

    @staticmethod
    def format_data(
        operations: List[Any],
        query_history_params: Iterable[Mapping[str, Any]],
    ) -> Dict[Any, Dict[Any, float]]:
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


class ConfigTournamentRunner:
    """Турнир всех конфигов из SERIES_CONFIGS по метрике «Качество» на HOLDOUT."""

    def __init__(
        self,
        dispatcher: Optional[ConfigDispatcher] = None,
        configs: Optional[Mapping[str, dict]] = None,
        holdout_size: int = HOLDOUT_SIZE,
        min_len_for_tournament: int = MIN_LEN_FOR_TOURNAMENT,
        min_len_for_window_median: int = MIN_LEN_FOR_WINDOW_MEDIAN,
    ) -> None:
        self._dispatcher = dispatcher or ConfigDispatcher()
        self._configs = dict(configs) if configs is not None else allowed_configs()
        self._cfg_order = list(self._configs.keys())
        self._holdout = int(holdout_size)
        self._min_tour = int(min_len_for_tournament)
        self._min_wm = int(min_len_for_window_median)

    def winner_for_series(self, df_op: pd.DataFrame, resist_id: int) -> str:
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
                    "tournament skip config=%s op=%s rid=%s: %s",
                    cfg_name, df_sorted["operation_id"].iloc[0], resist_id, exc,
                )
                continue
            y_hat_arr = np.asarray(y_hat, dtype=float)
            y_train_arr = df_sorted.loc[mask_train, "fact_value"].astype(float).values
            if not holdout_forecast_is_valid(
                y_hat_arr, y_train_arr, rel_cap=FORECAST_REL_CAP,
            ):
                logger.debug(
                    "tournament reject config=%s op=%s rid=%s: holdout exceeds cap",
                    cfg_name, df_sorted["operation_id"].iloc[0], resist_id,
                )
                cleanup_memory()
                continue
            _, _, kachestvo = _calc_metrics(y_true, y_hat_arr)
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
    """Финальный прогноз на FORECAST_HORIZON месяцев."""

    def __init__(
        self,
        dispatcher: Optional[ConfigDispatcher] = None,
        configs: Optional[Mapping[str, dict]] = None,
        horizon: int = FORECAST_HORIZON,
    ) -> None:
        self._dispatcher = dispatcher or ConfigDispatcher()
        self._configs = dict(configs) if configs is not None else allowed_configs()
        self._horizon = int(horizon)

    def forecast(
        self,
        df_op: pd.DataFrame,
        resist_id: int,
        winner_config: str,
    ) -> Dict[str, float]:
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
            raw = np.full(self._horizon, max(0.0, const), dtype=float)
            return _sanitize_forecast(raw, y_hist, rel_cap=FORECAST_REL_CAP)
        history = list(y_hist)
        out: List[float] = []
        for _ in range(self._horizon):
            tail = history[-3:] if len(history) >= 3 else history
            v = float(np.median(tail)) if tail else 0.0
            out.append(max(0.0, v))
            history.append(out[-1])
        return _sanitize_forecast(np.asarray(out, dtype=float), y_hist, rel_cap=FORECAST_REL_CAP)

    def _series_forecast(self, df_sorted: pd.DataFrame, resist_id: int, winner: str) -> np.ndarray:
        if winner not in self._configs:
            logger.warning(
                "ProductionForecaster: winner=%r нет в configs; Fallback-WindowMedian-3",
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
                "ProductionForecaster dispatch error winner=%s op=%s rid=%s: %s",
                winner, op_id, resist_id, exc,
            )
            return self._fallback_forecast(df_sorted, FALLBACK_WINDOW_MEDIAN_3_LABEL)
        finally:
            cleanup_memory()
        y_hist = df_sorted["fact_value"].astype(float).fillna(0.0).values
        y_arr = _sanitize_forecast(
            np.asarray(y_hat, dtype=float).ravel(),
            y_hist,
            rel_cap=FORECAST_REL_CAP,
        )
        if y_arr.shape[0] != self._horizon:
            y_arr = np.resize(y_arr, self._horizon)
        return y_arr


class WinnerConfigStore:
    """Чтение/запись JSON ``\"<resist_id>_<operation_id>\": \"<config_name>\"``."""

    @staticmethod
    def compose_json_key(resist_id: int, operation_id: Any) -> str:
        tok = _normalize_operation_token(operation_id)
        return f"{int(resist_id)}_{tok}"

    @staticmethod
    def load_mapping(path: Path) -> Dict[str, str]:
        if not path.exists():
            logger.warning("WinnerConfigStore: файл %s отсутствует", path)
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in raw.items()}

    @staticmethod
    def save_merge(path: Path, updates: Mapping[str, str]) -> None:
        existing: Dict[str, str] = {}
        if path.exists():
            raw_txt = path.read_text(encoding="utf-8").strip()
            if raw_txt:
                try:
                    parsed = json.loads(raw_txt)
                    existing = {str(k): str(v) for k, v in parsed.items()}
                except json.JSONDecodeError:
                    logger.warning("WinnerConfigStore: повреждённый JSON, перезапись")
            # пустой файл — трактуем как {}
        existing.update({str(k): str(v) for k, v in updates.items()})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_comparison(
    resist_ids: Sequence[int],
    repository: Any,
    *,
    config_json_path: Union[str, Path],
    operations: Optional[Sequence[Any]] = None,
    holdout_size: Optional[int] = None,
    tournament: Optional[ConfigTournamentRunner] = None,
    cleaner: Optional[OperationHistoryCleaner] = None,
) -> Dict[str, str]:
    """Турнир по нескольким resist_id; сохраняет результат в JSON (merge).

    ``repository``: объект с методом ``fetch(resist: str)`` как у ``HistoryRepository``.
    """
    cfg_path = Path(config_json_path)
    runner = tournament or ConfigTournamentRunner(
        holdout_size=holdout_size if holdout_size is not None else HOLDOUT_SIZE,
    )
    cl = cleaner or OperationHistoryCleaner()
    merged: Dict[str, str] = {}

    for rid in resist_ids:
        resist_str = str(int(rid))
        rows_materialized = list(repository.fetch(resist_str))
        ops = (
            list(operations)
            if operations is not None
            else operations_discovered_from_rows(rows_materialized)
        )
        if not ops:
            logger.warning("run_comparison: нет операций для resist_id=%s", rid)
            continue
        oper_data = cl.format_data(list(ops), rows_materialized)
        oper_valid = cl.drop_leading_zeros(oper_data)
        rid_int = int(rid)

        for op_id, history in oper_valid.items():
            if not history:
                continue
            df_op = cl.to_dataframe(history, op_id, rid_int)
            if df_op.empty:
                continue
            try:
                winner = runner.winner_for_series(df_op, rid_int)
            except Exception as exc:
                logger.exception(
                    "run_comparison resist=%s op=%s: %s; Fallback-WM-3",
                    rid_int, op_id, exc,
                )
                winner = FALLBACK_WINDOW_MEDIAN_3_LABEL
            key = WinnerConfigStore.compose_json_key(rid_int, op_id)
            merged[key] = winner

    WinnerConfigStore.save_merge(cfg_path, merged)
    return merged


class JsonConfigSelector:
    """Поиск конфига по ключу из JSON-словаря."""

    def __init__(self, mapping: Mapping[str, str]) -> None:
        self._mapping = dict(mapping)

    def get(self, resist_id: int, operation_id: Any) -> str:
        keys = []
        keys.append(WinnerConfigStore.compose_json_key(resist_id, operation_id))
        try:
            keys.append(WinnerConfigStore.compose_json_key(resist_id, int(operation_id)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
        for k in keys:
            if k in self._mapping:
                return self._mapping[k]
        logger.warning(
            "JsonConfigSelector: ключ не найден для rid=%s op=%s пробовали=%s → Fallback-WM-3",
            resist_id,
            operation_id,
            keys,
        )
        return FALLBACK_WINDOW_MEDIAN_3_LABEL


class PredictOparationCountCombo:
    """Прогноз или турнир конфигов: режим задаётся аргументом ``comparison`` в ``predict``."""

    def __init__(
        self,
        *,
        winner_mapping: Mapping[str, str],
        repository: Any,
        config_json_path: Union[str, Path] = WINNER_CONFIG_JSON,
        cleaner: Optional[OperationHistoryCleaner] = None,
        dispatcher: Optional[ConfigDispatcher] = None,
        forecaster: Optional[ProductionForecaster] = None,
        tournament: Optional[ConfigTournamentRunner] = None,
    ) -> None:
        self._repository = repository
        self._config_json_path = Path(config_json_path)
        self._cleaner = cleaner or OperationHistoryCleaner()
        self._dispatcher = dispatcher or ConfigDispatcher()
        self._forecaster = forecaster or ProductionForecaster(self._dispatcher)
        self._tournament = tournament
        self._selector = JsonConfigSelector(winner_mapping)

    def predict(
        self,
        operations: List[Any],
        resist: str,
        *,
        comparison: bool = False,
    ) -> Union[Dict[str, str], Dict[Any, Dict[str, Any]]]:
        """Прогноз или турнир конфигов для одного ``resist``.

        Args:
            operations: список ``operation_id``.
            resist: ``id`` модели нагрузки (resist).
            comparison: ``True`` — турнир и merge в JSON победителей;
                ``False`` — прогноз по JSON (по умолчанию).

        Returns:
            При ``comparison=True``: ``{\"<rid>_<op>\": \"<config_name>\", ...}``.
            При ``comparison=False``: ``{operation_id: {\"YYYY-MM-DD\": float, ..., \"model\": str}}``.
        """
        try:
            rid = int(resist)
        except (TypeError, ValueError):
            rid = 0

        if comparison:
            merged = run_comparison(
                [rid],
                self._repository,
                config_json_path=self._config_json_path,
                operations=operations,
                tournament=self._tournament,
                cleaner=self._cleaner,
            )
            self._selector._mapping.update(merged)
            return merged

        query_rows = self._repository.fetch(resist)
        oper_data = self._cleaner.format_data(operations, query_rows)
        oper_data_valid = self._cleaner.drop_leading_zeros(oper_data)

        result: Dict[Any, Dict[str, Any]] = {}
        for op_id, history in oper_data_valid.items():
            if not history:
                continue
            df_op = self._cleaner.to_dataframe(history, op_id, rid)
            if df_op.empty:
                continue
            winner = self._selector.get(rid, op_id)
            try:
                forecast_map = self._forecaster.forecast(df_op, rid, winner)
            except Exception as exc:
                logger.exception("predict_combo op=%s rid=%s winner=%s: %s", op_id, rid, winner, exc)
                forecast_map = {}

            merged: Dict[str, Any] = {}
            for period, value in history.items():
                try:
                    fv = float(value) if value is not None else 0.0
                except (TypeError, ValueError):
                    fv = 0.0
                merged[_format_date_key(period)] = fv
            for dk, fv in forecast_map.items():
                merged[str(dk)] = float(fv)
            merged[MODEL_KEY] = winner
            result[op_id] = merged
        return result


def run_winner_comparison(
    resist_ids: Sequence[int],
    operations: Optional[Sequence[Any]] = None,
    *,
    repository: Optional[Any] = None,
    config_json_path: Optional[Union[str, Path]] = None,
    holdout_size: Optional[int] = None,
    tournament: Optional[ConfigTournamentRunner] = None,
    cleaner: Optional[OperationHistoryCleaner] = None,
) -> Dict[str, str]:
    """Турнир по истории Django и запись победителей в ``WINNER_CONFIG_JSON`` (merge).

    Для одного ``resist`` удобнее ``predict_count_operation.predict(..., comparison=True)``."""
    repo = repository or HistoryRepository()
    cfg_path = Path(config_json_path) if config_json_path is not None else WINNER_CONFIG_JSON
    return run_comparison(
        resist_ids,
        repo,
        config_json_path=cfg_path,
        operations=operations,
        holdout_size=holdout_size,
        tournament=tournament,
        cleaner=cleaner,
    )


_winner_mapping_at_import = WinnerConfigStore.load_mapping(WINNER_CONFIG_JSON)
if not _winner_mapping_at_import:
    logger.warning(
        "predict_count_operation: пустой или отсутствующий JSON победителей (%s); "
        "неизвестные пары resist/operation получат Fallback-WindowMedian-3 через JsonConfigSelector.",
        WINNER_CONFIG_JSON,
    )

predict_count_operation = PredictOparationCountCombo(
    winner_mapping=_winner_mapping_at_import,
    repository=HistoryRepository(),
    config_json_path=WINNER_CONFIG_JSON,
)
