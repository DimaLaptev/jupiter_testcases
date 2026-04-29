# -*- coding: utf-8 -*-
"""Помесячный итеративный прогноз (iterative forecast) с полным рефитом (full refit).

В отличие от одношотного (batch) прогноза на весь горизонт теста, здесь на каждом шаге
модель заново обучается только на истории с датами строго раньше целевого месяца
(после подстановки факта за предыдущий закрытый месяц), и выдаётся ровно один шаг вперёд
(horizon h=1 per iteration).

Режим «как ноутбук 37» (по умолчанию): для **каждой** записи ``SERIES_CONFIGS``
выполняется полный итеративный цикл; затем по каждому ``operation_id`` выбирается конфигурация
с лучшим **Качество** (tie-break по имени), склеивается ряд «Комбайн 37».
Укажите ``--config NAME`` для одной модели вместо комбайна.

Политика фактов: в рабочей колонке ``fact_value`` для тестовых месяцев сначала стоят NaN;
перед прогнозом на месяц T факт за месяц T-1 подставляется из истины (backtest), заменяя
любой предыдущий прогноз для того же периода — без дублирования «факт + старый прогноз».
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from openpyxl import load_workbook

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from scripts.nb37_raw_model39_load import (  # noqa: E402
    describe_missing_raw_paths,
    load_df_model39_from_nb37_raw_files,
)
from scripts.tsa_per_series_nb37_trainers import (  # noqa: E402
    SERIES_CONFIGS,
    train_auto_arima_per_series,
    train_ets_per_series,
    train_glm_count_per_series,
    train_greykite_per_series,
    train_local_supervised_per_series,
    train_neuralforecast_per_series,
    train_prophet_per_series,
    train_sarimax_per_series,
    train_statsforecast_intermittent_per_series,
    train_statsforecast_per_series,
    train_tbats_per_series,
    train_theta_per_series,
    train_ucm_per_series,
    train_window_median_per_series,
    train_zip_per_series,
)

# ---------------------------------------------------------------------------
# Учёт периодов: дубликаты (operation_id, date) — keep="last"
DEDUPE_POLICY = "last"

COMBINE_NAME = "Комбайн 37"
RECORD_MODEL_WARNINGS = False
OUT_XLSX_DEFAULT = _ROOT / "data" / "processed" / "37_forecast_test.xlsx"

# Как в ``notebooks/37_comparison_per_resist_per_op_best_quality_combine.ipynb`` (RAW_DIR / RAW_FILES).
RAW_DIR = _ROOT / "data" / "raw"
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]

WARN_COLS = [
    "resist_id",
    "operation_id",
    "model_kind",
    "model_label",
    "phase",
    "warning_category",
    "message",
    "interpretation",
    "n_train_points",
    "statsmodels_module",
]

# Отключённые семейства (family) моделей для этого скрипта (не попадают в комбайн и недоступны в --config).
DISABLED_FN_FOR_SCRIPT: frozenset[str] = frozenset({"prophet", "tbats", "zip", "greykite"})


def series_configs_allowed_in_forecast_script() -> Dict[str, dict]:
    """Подмножество ``SERIES_CONFIGS``: имена конфигураций без отключённых ``fn``."""
    return {
        name: cfg
        for name, cfg in SERIES_CONFIGS.items()
        if cfg.get("fn") not in DISABLED_FN_FOR_SCRIPT
    }


def calc_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    """Метрики как в ноутбуке 37 (точность / стабильность / качество).

    Строки с нечисловым фактом или прогнозом (NaN/inf) исключаются — иначе ``np.mean(acc)``
    давал бы NaN (пустая ячейка в Excel), а стабильность/качество оставались бы нулями.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.maximum(np.asarray(y_pred, dtype=float), 0)
    y_pred = np.where(y_pred < 1e-3, 0.0, y_pred)

    valid = np.isfinite(y_true) & np.isfinite(y_pred)
    if not np.any(valid):
        return float("nan"), float("nan"), float("nan")

    y_true = y_true[valid]
    y_pred = y_pred[valid]

    acc = np.empty_like(y_true, dtype=float)
    mask_zero = y_true == 0
    acc[mask_zero] = np.where(y_pred[mask_zero] == 0, 100.0, 0.0)
    mask_ok = ~mask_zero
    if np.any(mask_ok):
        acc[mask_ok] = np.clip(
            100.0 - np.abs(y_true[mask_ok] - y_pred[mask_ok]) / np.abs(y_true[mask_ok]) * 100.0,
            0,
            100,
        )
    tochnost = round(float(np.mean(acc)), 2)
    stab = 0.0
    if tochnost > 0:
        cv = np.std(acc, ddof=0) / tochnost
        stab = round(max(0.0, (1 - cv)) * 100, 2)
    kachestvo = 0.0
    if tochnost + stab > 0:
        kachestvo = round(2 * tochnost * stab / (tochnost + stab), 2)
    return tochnost, stab, kachestvo


def normalize_month_period(x) -> pd.Timestamp:
    """Первое число месяца (month start), timezone-naive (как MS)."""
    t = pd.Timestamp(x)
    if t.tzinfo is not None:
        t = t.tz_localize(None)
    return pd.Timestamp(t.to_period("M").to_timestamp())


def prepare_resist_frame(df: pd.DataFrame, resist_id: int) -> pd.DataFrame:
    """Фильтр по ``resist_id``, сортировка, нормализация ``date``, дедупликация."""
    sub = df[df["resist_id"] == resist_id].copy()
    if sub.empty:
        return sub
    sub["date"] = sub["date"].map(normalize_month_period)
    sub = sub.sort_values(["operation_id", "date"])
    if DEDUPE_POLICY == "last":
        sub = sub.drop_duplicates(["operation_id", "date"], keep="last")
    else:
        dup = sub.duplicated(["operation_id", "date"], keep=False)
        if dup.any():
            raise ValueError("дубликаты (operation_id, date) при строгом режиме")
    sub["year"] = sub["date"].dt.year
    sub["month"] = sub["date"].dt.month
    if "fact_predict" not in sub.columns:
        sub["fact_predict"] = np.nan
    sub["fact_value"] = pd.to_numeric(sub["fact_value"], errors="coerce")
    return sub.reset_index(drop=True)


def add_nb37_features(df: pd.DataFrame, mask_train_scope: pd.Series) -> pd.DataFrame:
    """Лаги (lags) как в nb36/nb37: медиана (median) train по ``operation_id`` для lag_1…lag_6."""
    out = df.copy()
    out["op_code"] = out["operation_id"].astype("category").cat.codes
    group = out.groupby("operation_id")
    out["lag_1"] = group["fact_value"].shift(1)
    for _k in range(2, 7):
        out[f"lag_{_k}"] = group["fact_value"].shift(_k)
    out["lag_12"] = group["fact_value"].shift(12)
    out["rolling_mean_3"] = group["fact_value"].transform(
        lambda s: s.shift(1).rolling(window=3, min_periods=1).mean()
    )
    half_year_lag_cols = [f"lag_{i}" for i in range(1, 7)]
    train_med = out.loc[mask_train_scope].groupby("operation_id")["fact_value"].median()
    for _col in half_year_lag_cols:
        out[_col] = out[_col].fillna(out["operation_id"].map(train_med)).fillna(0.0)
    num_cols = out.select_dtypes(include=["number"]).columns
    out[num_cols] = out[num_cols].fillna(0)
    out = out.infer_objects(copy=False)
    if out.isnull().any().any():
        out = out.fillna(0)
    return out


def _one_train_config(
    df: pd.DataFrame,
    mask_train: pd.Series,
    mask_test: pd.Series,
    rid: int,
    config_name: str,
    cfg: dict,
    warning_rows: list,
) -> np.ndarray:
    """Диспетчер как в ``nb36_loop_tail._one_train_config``."""
    if cfg["fn"] == "ets":
        return train_ets_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            trend=cfg["trend"],
            damped_trend=cfg["damped_trend"],
            seasonal=cfg.get("seasonal"),
            seasonal_periods=cfg.get("seasonal_periods"),
            ets_fit_kwargs=cfg.get("ets_fit_kwargs"),
        )
    if cfg["fn"] == "theta":
        return train_theta_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            theta_deseasonalize=cfg.get("theta_deseasonalize", True),
            theta_method=cfg.get("theta_method", "auto"),
            theta_period=cfg.get("theta_period", 12),
        )
    if cfg["fn"] == "sarimax":
        return train_sarimax_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            sarimax_preset=cfg.get("sarimax_preset", "default"),
            sarimax_order=cfg.get("sarimax_order"),
            sarimax_seasonal_order=cfg.get("sarimax_seasonal_order"),
            sarimax_fit_kwargs=cfg.get("sarimax_fit_kwargs"),
        )
    if cfg["fn"] == "auto_arima":
        return train_auto_arima_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            auto_arima_kwargs=cfg.get("auto_arima_kwargs"),
        )
    if cfg["fn"] == "statsforecast":
        return train_statsforecast_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            sf_model_name=cfg["sf_model"],
            season_len=cfg["season_len"],
            sf_window_size=cfg.get("sf_window_size"),
            sf_tsb_kwargs=cfg.get("sf_tsb_kwargs"),
        )
    if cfg["fn"] == "statsforecast_intermittent":
        return train_statsforecast_intermittent_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            sf_model_name=cfg["sf_model"],
            season_len=cfg["season_len"],
            sf_tsb_kwargs=cfg.get("sf_tsb_kwargs"),
        )
    if cfg["fn"] == "prophet":
        return train_prophet_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            prophet_params=cfg.get("prophet_params"),
        )
    if cfg["fn"] == "ucm":
        return train_ucm_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            ucm_level=cfg.get("ucm_level", "local linear trend"),
            ucm_stochastic_level=cfg.get("ucm_stochastic_level"),
            ucm_stochastic_seasonal=cfg.get("ucm_stochastic_seasonal"),
        )
    if cfg["fn"] == "tbats":
        return train_tbats_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            tbats_use_box_cox=cfg.get("tbats_use_box_cox"),
            tbats_use_arma_errors=cfg.get("tbats_use_arma_errors"),
            tbats_seasonal_periods=cfg.get("tbats_seasonal_periods"),
        )
    if cfg["fn"] == "neuralforecast":
        return train_neuralforecast_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            nf_model_name=cfg["nf_model"],
            nf_max_steps=cfg.get("nf_max_steps"),
            nf_learning_rate=cfg.get("nf_learning_rate"),
        )
    if cfg["fn"] == "local_supervised":
        return train_local_supervised_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            sk_model=cfg["sk_model"],
            local_sk_params=cfg.get("local_sk_params"),
        )
    if cfg["fn"] == "glm_count":
        return train_glm_count_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            family_name=cfg["family"],
            glm_fit_kwargs=cfg.get("glm_fit_kwargs"),
            glm_use_regularized=cfg.get("glm_use_regularized", False),
            glm_reg_alpha=cfg.get("glm_reg_alpha", 0.1),
            glm_reg_l1_wt=cfg.get("glm_reg_l1_wt", 0.0),
        )
    if cfg["fn"] == "zip":
        return train_zip_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            zip_fit_kwargs=cfg.get("zip_fit_kwargs"),
            zip_model_kind=cfg.get("zip_model_kind", "zip"),
            zip_exog_infl_mode=cfg.get("zip_exog_infl_mode", "same"),
        )
    if cfg["fn"] == "window_median":
        return train_window_median_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            window_size=int(cfg["window_size"]),
        )
    if cfg["fn"] == "greykite":
        return train_greykite_per_series(
            df,
            mask_train,
            mask_test,
            rid,
            config_name,
            warning_rows,
            greykite_coverage=cfg.get("greykite_coverage", 0.95),
            greykite_model_template=cfg.get("greykite_model_template"),
            greykite_mcp_dict=cfg.get("greykite_mcp_dict"),
            greykite_extra_pred_col=cfg.get("greykite_extra_pred_col", False),
            greykite_forecast_one_by_one=cfg.get("greykite_forecast_one_by_one"),
        )
    raise ValueError(f"неизвестный fn={cfg.get('fn')!r} для {config_name!r}")


def forecast_expand_history_monthly(
    df_src: pd.DataFrame,
    resist_id: int,
    config_name: str,
    *,
    test_year: int,
    test_months: Iterable[int],
    truth_strict: bool = True,
    seed_notebook_warnings: bool = False,
) -> Tuple[pd.Series, List[dict], Dict[str, Any]]:
    """Итеративный прогноз по месяцам теста с полным рефитом и h=1.

    Параметр ``truth_strict``: если для предыдущего месяца нет факта в ``df_src``,
    шаг пропускается (в ``step_log`` записывается причина).

    Возвращает:
    - предсказания по индексам строк теста (Series),
    - warning_rows,
    - служебный dict с ``step_log``, ``df_test_view`` для Excel.
    """
    if config_name not in SERIES_CONFIGS:
        raise KeyError(f"неизвестная конфигурация: {config_name!r}")
    cfg = SERIES_CONFIGS[config_name]

    sub = prepare_resist_frame(df_src, resist_id)
    if sub.empty:
        raise ValueError(f"пустой ряд после фильтра resist_id={resist_id}")

    base = sub.copy()

    mask_test_all = (sub["year"] == test_year) & (sub["month"].isin(list(test_months)))
    mask_train_all = ~mask_test_all
    test_ix = sub.loc[mask_test_all].index.tolist()
    if not test_ix:
        raise ValueError("нет строк теста по test_year/test_months")

    month_ts_sorted = sorted({normalize_month_period(d) for d in sub.loc[mask_test_all, "date"]})

    work = base.copy()
    work.loc[mask_test_all, "fact_value"] = np.nan

    pred_acc = pd.Series(np.nan, index=sub.index, dtype=float)
    warning_rows: list = []
    step_log: List[dict] = []

    for target_ts in month_ts_sorted:
        prev_ts = (target_ts.to_period("M") - 1).to_timestamp()
        test_prev_mask = (work["date"] == prev_ts) & mask_test_all
        if test_prev_mask.any():
            vals = base.loc[test_prev_mask, "fact_value"]
            if truth_strict and vals.isna().any():
                step_log.append(
                    {"target": str(target_ts), "skipped": True, "reason": "нет факта за предыдущий месяц"}
                )
                continue
            work.loc[test_prev_mask, "fact_value"] = vals

        df_fit = work[work["date"] <= target_ts].copy()
        mask_train = df_fit["date"] < target_ts
        mask_test = df_fit["date"] == target_ts
        if not mask_test.any():
            step_log.append({"target": str(target_ts), "skipped": True, "reason": "нет строки теста"})
            continue
        if mask_train.sum() == 0:
            step_log.append({"target": str(target_ts), "skipped": True, "reason": "пустая история train"})
            continue

        scope_train_med = df_fit["date"] < target_ts
        df_feat = add_nb37_features(df_fit, scope_train_med)

        t0 = time.perf_counter()
        y_hat = _one_train_config(
            df_feat,
            mask_train,
            mask_test,
            resist_id,
            config_name,
            cfg,
            warning_rows if seed_notebook_warnings else [],
        )
        elapsed = round(time.perf_counter() - t0, 4)
        test_part_idx = df_feat.loc[mask_test].index
        for i, ix in enumerate(test_part_idx):
            pred_acc.loc[ix] = float(y_hat[i])
        step_log.append({
            "target": str(target_ts),
            "skipped": False,
            "elapsed_sec": elapsed,
            "n_train_rows": int(mask_train.sum()),
            "n_pred": len(y_hat),
        })

    out = pred_acc.loc[test_ix].copy()
    meta = {
        "step_log": step_log,
        "df_test_view": base.loc[mask_test_all].copy(),
        "mask_test_all": mask_test_all,
        "mask_train_all": mask_train_all,
    }
    meta["df_test_view"]["predict_new"] = pred_acc.loc[mask_test_all]
    return out, warning_rows, meta


def combine_iterative_forecasts_nb37(
    df_src: pd.DataFrame,
    resist_id: int,
    *,
    config_names: List[str],
    test_year: int,
    test_months: Iterable[int],
    truth_strict: bool = True,
) -> Tuple[pd.Series, Dict[Any, str], Dict[str, pd.Series], List[dict], pd.DataFrame]:
    """Для каждой конфигурации из ``config_names`` — полный итеративный прогноз (как nb37 по смыслу).

    По каждому ``operation_id`` выбирается конфигурация с максимальным **Качество** на тесте;
    tie-break: лексикографически меньшее имя (как в ноутбуке 37).

    Возвращает склеенный ряд предсказаний ``y_combined`` (индекс — строки теста),
    словарь победителей, все предикты по конфигам, предупреждения и шаблон ``df_test`` без столбца predict_new.
    """
    pred_by_cfg: Dict[str, pd.Series] = {}
    warnings_all: List[dict] = []
    df_test_template: Optional[pd.DataFrame] = None
    cfg_order_global = list(SERIES_CONFIGS.keys())

    for cn in config_names:
        if cn not in SERIES_CONFIGS:
            print(f"[combine] пропуск: неизвестная конфигурация {cn!r}", flush=True)
            continue
        try:
            preds, warns, meta = forecast_expand_history_monthly(
                df_src,
                resist_id,
                cn,
                test_year=test_year,
                test_months=test_months,
                truth_strict=truth_strict,
                seed_notebook_warnings=False,
            )
            pred_by_cfg[cn] = preds
            warnings_all.extend(warns)
            dv = meta["df_test_view"].copy()
            dv = dv.drop(columns=["predict_new"], errors="ignore")
            if df_test_template is None:
                df_test_template = dv
        except Exception as exc:
            print(f"[combine] пропуск {cn!r}: {exc}", flush=True)
            continue

    if not pred_by_cfg or df_test_template is None:
        raise RuntimeError("нет ни одной успешной конфигурации для комбайна (combine)")

    df_test = df_test_template.copy()
    test_idx = df_test.index
    for cn in pred_by_cfg:
        pred_by_cfg[cn] = pred_by_cfg[cn].reindex(test_idx)

    cfg_order = [c for c in cfg_order_global if c in pred_by_cfg]

    winner_by_op: Dict[Any, str] = {}
    y_comb = pd.Series(0.0, index=test_idx, dtype=float)

    for op_id, grp in df_test.groupby("operation_id", sort=False):
        best_q = -1.0
        best_cfg: Optional[str] = None
        for cfg_name in cfg_order:
            if cfg_name not in pred_by_cfg:
                continue
            pred = pred_by_cfg[cfg_name].reindex(grp.index).to_numpy(dtype=float)
            _, _, q = calc_metrics(grp["fact_value"].values, pred)
            if q > best_q or (
                abs(q - best_q) < 1e-9 and (best_cfg is None or cfg_name < best_cfg)
            ):
                best_q = q
                best_cfg = cfg_name
        if best_cfg is None:
            best_cfg = cfg_order[0]
        winner_by_op[op_id] = best_cfg
        y_comb.loc[grp.index] = pred_by_cfg[best_cfg].reindex(grp.index)

    return y_comb, winner_by_op, pred_by_cfg, warnings_all, df_test


def build_nb37_excel_payload(
    *,
    resist_id: int,
    df_test_view: pd.DataFrame,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_baseline: Optional[np.ndarray],
    winner_by_operation: Optional[Dict[Any, str]] = None,
    single_config_label: Optional[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Формирует таблицы как в ячейке ``c37-combine`` ноутбука 37.

    Если ``winner_by_operation`` задан (режим комбайна), колонка «Победившая Конфигурация» заполняется
    по операции (per ``operation_id``), иначе везде используется ``single_config_label``.
    """
    t_m, s_m, q_m = calc_metrics(y_true, y_pred)
    t_fp = s_fp = q_fp = float("nan")
    if y_baseline is not None and np.any(np.isfinite(y_baseline)):
        t_fp, s_fp, q_fp = calc_metrics(y_true, y_baseline)

    combine_rows = [
        {
            "resist_id": resist_id,
            "Конфигурация": COMBINE_NAME,
            "Набор признаков": "—",
            "Тип": "per-series",
            "Точность, %": t_m,
            "Стабильность, %": s_m,
            "Качество, %": q_m,
            "Время, сек": float("nan"),
            "Точн. fact_predict, %": t_fp,
            "Стаб. fact_predict, %": s_fp,
            "Кач. fact_predict, %": q_fp,
        }
    ]
    df_results = pd.DataFrame(combine_rows)
    df_results["Комбинация"] = df_results.apply(
        lambda r: (
            f"{r['Конфигурация']} | {r['Набор признаков']}"
            if r["Набор признаков"] != "—"
            else r["Конфигурация"]
        ),
        axis=1,
    )
    df_results_full = df_results.sort_values(["resist_id", "Качество, %"], ascending=[True, False]).reset_index(
        drop=True
    )

    df_detail = df_test_view[
        ["resist_id", "operation_id", "year", "month", "fact_value", "fact_predict", "predict_new"]
    ].copy()
    df_detail = df_detail.sort_values(["resist_id", "operation_id", "year", "month"]).reset_index(drop=True)
    df_detail = df_detail.rename(
        columns={
            "fact_value": "fact_value (факт)",
            "fact_predict": "fact_predict (текущий)",
            "predict_new": f"{COMBINE_NAME} (новый)",
        }
    )

    rows_op = []
    for (_, op_id), grp in df_test_view.groupby(["resist_id", "operation_id"], sort=False):
        if winner_by_operation is not None:
            win_label = winner_by_operation.get(op_id)
            if win_label is None:
                win_label = single_config_label or "—"
        else:
            win_label = single_config_label or "—"
        fp = grp["fact_predict"].values if "fact_predict" in grp.columns else np.full(len(grp), np.nan)
        if fp is None or not np.any(np.isfinite(fp)):
            t1 = s1 = q1 = float("nan")
        else:
            t1, s1, q1 = calc_metrics(grp["fact_value"].values, fp)
        t2, s2, q2 = calc_metrics(grp["fact_value"].values, grp["predict_new"].values)
        rows_op.append(
            {
                "resist_id": resist_id,
                "operation_id": op_id,
                "Победившая Конфигурация": win_label,
                "Точность (fact_predict)": t1,
                "Стабильность (fact_predict)": s1,
                "Качество (fact_predict)": q1,
                f"Точность ({COMBINE_NAME})": t2,
                f"Стабильность ({COMBINE_NAME})": s2,
                f"Качество ({COMBINE_NAME})": q2,
            }
        )
    df_metrics_op = pd.DataFrame(rows_op)
    return df_results_full, df_detail, df_metrics_op


def write_nb37_style_excel(
    *,
    out_path: Path,
    resist_ids: List[int],
    df_results_full: pd.DataFrame,
    per_rid_best: Dict[int, Dict[str, Any]],
    warning_rows: List[dict],
    record_warnings: bool = False,
) -> None:
    """Экспорт Excel как ячейка ``c37-excel`` ноутбука 37 (openpyxl, remove/replace листов)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sheet_triples: List[Tuple[Any, ...]] = []
    for rid in resist_ids:
        df_itog = df_results_full[df_results_full["resist_id"] == rid]
        if rid not in per_rid_best:
            continue
        b = per_rid_best[rid]
        df_warn = pd.DataFrame([r for r in warning_rows if r.get("resist_id") == rid])
        if df_warn.empty:
            df_warn = pd.DataFrame(columns=WARN_COLS)
        else:
            df_warn = df_warn.reindex(columns=WARN_COLS)
        sheet_triples.append((rid, df_itog, b["df_detail"], b["df_metrics_op"], df_warn))

    names_to_remove: List[str] = []
    for rid, _, _, _, _ in sheet_triples:
        sheets = [f"{rid} Итог", f"{rid} Данные теста", f"{rid} По операциям"]
        if record_warnings:
            sheets.append(f"{rid} Предупреждения")
        names_to_remove.extend(sheets)

    if out_path.exists():
        wb = load_workbook(out_path)
        for sn in names_to_remove:
            if sn in wb.sheetnames:
                wb.remove(wb[sn])
        if len(wb.sheetnames) == 0:
            wb.create_sheet("_tmp")
        wb.save(out_path)
        wb.close()
        writer_mode = "a"
    else:
        writer_mode = "w"

    with pd.ExcelWriter(out_path, engine="openpyxl", mode=writer_mode) as w:
        for rid, df_itog, df_detail, df_metrics_op, df_warn in sheet_triples:
            df_itog.to_excel(w, sheet_name=f"{rid} Итог", index=False)
            df_detail.to_excel(w, sheet_name=f"{rid} Данные теста", index=False)
            df_metrics_op.to_excel(w, sheet_name=f"{rid} По операциям", index=False)
            if record_warnings:
                df_warn.to_excel(w, sheet_name=f"{rid} Предупреждения", index=False)

    wb = load_workbook(out_path)
    if "_tmp" in wb.sheetnames and len(wb.sheetnames) > 1:
        wb.remove(wb["_tmp"])
        wb.save(out_path)
    wb.close()

    print(f"Excel: {out_path.resolve()}")
    for rid, df_itog, _, _, df_warn in sheet_triples:
        msg = (
            f"  «{rid} Итог» ({len(df_itog)} строк), «{rid} Данные теста», «{rid} По операциям»"
        )
        if record_warnings:
            msg += f", «{rid} Предупреждения» ({len(df_warn)} строк)"
        print(msg)


def _run_unit_tests() -> None:
    """Проверки утечки (leakage) и идемпотентности на синтетике."""
    rng = np.random.default_rng(42)
    rows = []
    resist_id = 1
    op = 100
    # train: 2025-01 .. 2025-03
    for m in range(1, 4):
        rows.append(
            {
                "resist_id": resist_id,
                "operation_id": op,
                "date": pd.Timestamp(2025, m, 1),
                "fact_value": float(10 + m),
                "fact_predict": float(rng.uniform(8, 12)),
            }
        )
    # test months 4..6 с известной истиной
    truth_extra = {4: 20.0, 5: 21.0, 6: 22.0}
    for m in range(4, 7):
        rows.append(
            {
                "resist_id": resist_id,
                "operation_id": op,
                "date": pd.Timestamp(2025, m, 1),
                "fact_value": truth_extra[m],
                "fact_predict": 15.0,
            }
        )
    df_syn = pd.DataFrame(rows)

    pred1, _, meta1 = forecast_expand_history_monthly(
        df_syn,
        resist_id,
        "WindowMedian-3",
        test_year=2025,
        test_months=[4, 5, 6],
        truth_strict=True,
    )
    pred2, _, meta2 = forecast_expand_history_monthly(
        df_syn,
        resist_id,
        "WindowMedian-3",
        test_year=2025,
        test_months=[4, 5, 6],
        truth_strict=True,
    )
    assert np.allclose(pred1.values, pred2.values, equal_nan=True), "идемпотентность (idempotency)"

    # Перед прогнозом на месяц m+1 факт за m должен быть в train — проверка через лог шагов
    assert all(not s.get("skipped") for s in meta1["step_log"]), meta1["step_log"]

    # Искусственно вырезаем факт за месяц 4 для строки теста — шаг для месяца 5 не должен использовать истину за апрель
    df_bad = df_syn.copy()
    df_bad.loc[df_bad["date"].dt.month == 4, "fact_value"] = np.nan
    pred_bad, _, meta_bad = forecast_expand_history_monthly(
        df_bad,
        resist_id,
        "WindowMedian-3",
        test_year=2025,
        test_months=[4, 5, 6],
        truth_strict=True,
    )
    assert pred_bad.isna().any() or any(s.get("skipped") for s in meta_bad["step_log"])

    yc, win, _, _, _ = combine_iterative_forecasts_nb37(
        df_syn,
        resist_id,
        config_names=["WindowMedian-3", "WindowMedian-5"],
        test_year=2025,
        test_months=[4, 5, 6],
        truth_strict=True,
    )
    assert len(yc) == 3
    assert win[100] in ("WindowMedian-3", "WindowMedian-5")

    print("unit_tests: OK")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Итеративный прогноз nb37-style (full refit monthly)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "По умолчанию — все конфигурации SERIES_CONFIGS (комбайн nb37 по operation_id). "
            "Флаг --config NAME переключает на одну модель. "
            "Без --csv данные загружаются из RAW_FILES (concat как в ноутбуке 37 → df_model39)."
        ),
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Готовый CSV (date, fact_value, operation_id, resist_id [, fact_predict]). "
        f"Если не задан — сборка из {RAW_DIR} (data-2022 … data-2025), как nb37.",
    )
    rid_grp = parser.add_mutually_exclusive_group()
    rid_grp.add_argument(
        "--resist-id",
        type=int,
        default=None,
        metavar="N",
        help="Один resist_id (только эти строки в прогоне)",
    )
    rid_grp.add_argument(
        "--resist-ids",
        type=str,
        default=None,
        metavar="LIST",
        help="Несколько resist_id через запятую (comma-separated), напр. 124,125,130",
    )
    parser.add_argument("--test-year", type=int, default=2025)
    parser.add_argument(
        "--test-months",
        type=str,
        default="7,8,9,10,11,12",
        help="Месяцы теста (test months), через запятую; метрики только по этим месяцам внутри --test-year "
        "(по умолчанию второе полугодие (second half): июль–декабрь)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        metavar="NAME",
        help="Одна конфигурация из разрешённого подмножества SERIES_CONFIGS "
        "(семейства prophet/tbats/zip/greykite в скрипте отключены — см. DISABLED_FN_FOR_SCRIPT)",
    )
    parser.add_argument("--out-xlsx", type=Path, default=OUT_XLSX_DEFAULT)
    parser.add_argument("--no-excel", action="store_true")
    parser.add_argument("--unit-tests", action="store_true")
    args = parser.parse_args(argv)

    if args.unit_tests:
        _run_unit_tests()
        return

    allowed_cfgs = series_configs_allowed_in_forecast_script()
    if not allowed_cfgs:
        parser.error("пустое подмножество конфигураций после DISABLED_FN_FOR_SCRIPT")

    if args.config is not None:
        if args.config not in SERIES_CONFIGS:
            parser.error(
                f"неизвестная --config {args.config!r}; см. SERIES_CONFIGS в tsa_per_series_nb37_trainers.py"
            )
        fn = SERIES_CONFIGS[args.config].get("fn")
        if fn in DISABLED_FN_FOR_SCRIPT:
            parser.error(
                f"--config {args.config!r}: семейство fn={fn!r} отключено в 37_forecast_test.py "
                f"(DISABLED_FN_FOR_SCRIPT)"
            )
        configs_to_run = [args.config]
    else:
        configs_to_run = list(allowed_cfgs.keys())

    months = [int(x.strip()) for x in args.test_months.split(",") if x.strip()]
    if args.csv is not None:
        df = pd.read_csv(args.csv, dtype=str, low_memory=False)
    else:
        missing_paths = describe_missing_raw_paths(RAW_FILES)
        if missing_paths:
            print(
                "Предупреждение: отсутствуют часть raw-файлов (пропускаются):",
                ", ".join(str(p) for p in missing_paths),
                flush=True,
            )
        df = load_df_model39_from_nb37_raw_files(RAW_FILES)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["fact_value"] = pd.to_numeric(df["fact_value"], errors="coerce")
    df["operation_id"] = pd.to_numeric(df["operation_id"], errors="coerce")
    df["resist_id"] = pd.to_numeric(df["resist_id"], errors="coerce")
    if "fact_predict" in df.columns:
        df["fact_predict"] = pd.to_numeric(df["fact_predict"], errors="coerce")
    df = df.dropna(subset=["date", "fact_value", "operation_id", "resist_id"])

    avail = set(df["resist_id"].dropna().unique().astype(int).tolist())
    if args.resist_ids is not None:
        rid_list = [int(x.strip()) for x in args.resist_ids.split(",") if x.strip()]
        miss = [r for r in rid_list if r not in avail]
        if miss:
            parser.error(f"--resist-ids: нет в данных resist_id={miss}; доступно из файла: {sorted(avail)!r}")
    elif args.resist_id is not None:
        if args.resist_id not in avail:
            parser.error(
                f"--resist-id {args.resist_id} отсутствует в данных; доступно: {sorted(avail)!r}"
            )
        rid_list = [args.resist_id]
    else:
        rid_list = sorted(avail)

    combine_frames: List[pd.DataFrame] = []
    per_rid_best: Dict[int, Dict[str, Any]] = {}
    warn_all: List[dict] = []

    single_mode = len(configs_to_run) == 1
    if not single_mode:
        print(
            f"Режим nb37 (combine): итеративный прогноз для {len(configs_to_run)} конфигураций, затем выбор по operation_id.",
            flush=True,
        )

    n_rid = len(rid_list)
    for irid, rid in enumerate(rid_list, start=1):
        if single_mode:
            cfg0 = configs_to_run[0]
            preds, warns, meta = forecast_expand_history_monthly(
                df,
                int(rid),
                cfg0,
                test_year=args.test_year,
                test_months=months,
                truth_strict=True,
            )
            warn_all.extend(warns)

            dv = meta["df_test_view"].copy()
            y_true = dv["fact_value"].astype(float).values
            y_pred = dv["predict_new"].astype(float).values
            base_fp = dv["fact_predict"].astype(float).values if "fact_predict" in dv.columns else None

            df_res_full, df_detail, df_metrics_op = build_nb37_excel_payload(
                resist_id=int(rid),
                df_test_view=dv,
                y_true=y_true,
                y_pred=y_pred,
                y_baseline=base_fp,
                winner_by_operation=None,
                single_config_label=cfg0,
            )
        else:
            y_comb, winner_by_op, _pred_by_cfg, warns, df_test_base = combine_iterative_forecasts_nb37(
                df,
                int(rid),
                config_names=configs_to_run,
                test_year=args.test_year,
                test_months=months,
                truth_strict=True,
            )
            warn_all.extend(warns)
            dv = df_test_base.copy()
            dv["predict_new"] = y_comb.reindex(dv.index)
            y_true = dv["fact_value"].astype(float).values
            y_pred = dv["predict_new"].astype(float).values
            base_fp = dv["fact_predict"].astype(float).values if "fact_predict" in dv.columns else None

            df_res_full, df_detail, df_metrics_op = build_nb37_excel_payload(
                resist_id=int(rid),
                df_test_view=dv,
                y_true=y_true,
                y_pred=y_pred,
                y_baseline=base_fp,
                winner_by_operation=winner_by_op,
                single_config_label=None,
            )

        _q = df_res_full.iloc[0]["Качество, %"] if len(df_res_full) else float("nan")
        _q_show = "nan" if pd.isna(_q) else f"{float(_q):.2f}"
        print(f"[{irid}/{n_rid}] resist_id={rid} → Качество, % = {_q_show}", flush=True)

        combine_frames.append(df_res_full)
        per_rid_best[int(rid)] = {
            "best_combo": COMBINE_NAME,
            "df_metrics_op": df_metrics_op,
            "df_detail": df_detail,
        }

    df_results_full = pd.concat(combine_frames, ignore_index=True) if combine_frames else pd.DataFrame()

    if not args.no_excel:
        write_nb37_style_excel(
            out_path=args.out_xlsx,
            resist_ids=[int(r) for r in rid_list],
            df_results_full=df_results_full,
            per_rid_best=per_rid_best,
            warning_rows=warn_all,
            record_warnings=RECORD_MODEL_WARNINGS,
        )


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    main()
