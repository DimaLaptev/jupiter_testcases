# -*- coding: utf-8 -*-
"""Бенчмарк (benchmark): ``predict_operation_count_v2`` vs ``optimized_predict_operation_count_v2``.

Синтетическая история в long-формате (как ``df_model39``): ``resist_id``, ``date``,
``operation_id``, ``fact_value``. Репозиторий (repository) имитирует вывод ORM
``fetch`` (те же поля ``period``, ``operation_parameter``), как в
``CsvHistoryRepository`` из ``test_predict_operation_count_v2.py``.

Важно: если установлен пакет ``neuralforecast``, в базовом модуле остаются конфиги
NF-* и время будет выше, чем у optimized (без NF). Скрипт печатает число конфигов
в каждом варианте для интерпретации.
"""

from __future__ import annotations

import argparse
import gc
import logging
import statistics
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from scripts import optimized_predict_operation_count_v2 as opt_mod
from scripts import predict_operation_count_v2 as base_mod


def _operation_key_for_param(operation_id: Any) -> str:
    if pd.isna(operation_id):
        return str(operation_id)
    try:
        x = float(operation_id)
        if x == int(x):
            return str(int(x))
    except (TypeError, ValueError):
        pass
    return str(operation_id)


class SyntheticDfHistoryRepository:
    """История из ``DataFrame``; ``fetch`` совместим с ``HistoryRepository`` production."""

    def __init__(self, df_model39: pd.DataFrame, history_start_date: datetime) -> None:
        self._df = df_model39
        self._history_start = history_start_date

    def fetch(self, resist: str) -> Iterable[Mapping[str, Any]]:
        now_period = (datetime.today().replace(day=1) - timedelta(days=1)).replace(day=1)
        rid = int(resist)
        need = {"resist_id", "date", "fact_value"}
        miss = need - set(self._df.columns)
        if miss:
            raise ValueError(f"не хватает колонок (columns): {sorted(miss)}")
        sub = self._df.loc[self._df["resist_id"] == rid].copy()
        if sub.empty:
            return []
        sub["_ts"] = pd.to_datetime(sub["date"], errors="coerce")
        sub = sub.dropna(subset=["_ts"])
        start_bound = pd.Timestamp(self._history_start)
        end_bound = pd.Timestamp(now_period)
        sub = sub.loc[(sub["_ts"] > start_bound) & (sub["_ts"] < end_bound)]
        if sub.empty:
            return []
        sub["_period"] = sub["_ts"].dt.to_period("M").dt.to_timestamp()
        sub = sub.sort_values(["_period", "operation_id"])
        sub = sub.drop_duplicates(["_period", "operation_id"], keep="last")
        rows_out: List[Dict[str, Any]] = []
        for period_ts, grp in sub.groupby("_period", sort=True):
            op_param: Dict[str, dict] = {}
            for _, row in grp.iterrows():
                key = _operation_key_for_param(row["operation_id"])
                op_param[key] = {"fact_value": row["fact_value"]}
            rows_out.append({
                "period": pd.Timestamp(period_ts),
                "operation_parameter": op_param,
            })
        rows_out.sort(key=lambda r: r["period"])
        return rows_out


def build_synthetic_history_df(
    *,
    n_operations: int,
    n_months: int,
    resist_id: int,
    seed: int,
    history_start_date: datetime,
) -> pd.DataFrame:
    """Строит положительный месячный ряд (seasonality + drift + шум) по операциям."""
    rng = np.random.default_rng(seed)
    now_period = (datetime.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    end = pd.Timestamp(now_period) - pd.DateOffset(months=2)
    dates = pd.date_range(end=end, periods=int(n_months), freq="MS")
    if dates[0] <= pd.Timestamp(history_start_date):
        raise ValueError(
            "n_months слишком велик для окна дат; уменьшите n_months или проверьте HISTORY_START_DATE"
        )
    rows: List[dict] = []
    for oid in range(1, int(n_operations) + 1):
        base = 5.0 + oid * 1.5
        for i, d in enumerate(dates):
            seasonal = 1.0 + 0.12 * np.sin(2 * np.pi * i / 12.0)
            noise = float(rng.normal(0.0, 0.4))
            fv = max(0.5, base * seasonal + noise + i * 0.03)
            rows.append({
                "resist_id": resist_id,
                "operation_id": oid,
                "date": d,
                "fact_value": round(fv, 4),
            })
    return pd.DataFrame(rows)


def _bench_one(label: str, predict_fn, repeat: int) -> List[float]:
    times: List[float] = []
    for _ in range(repeat):
        gc.collect()
        t0 = time.perf_counter()
        predict_fn()
        times.append(time.perf_counter() - t0)
    return times


def main() -> None:
    warnings.filterwarnings("ignore")
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logging.disable(logging.CRITICAL)
    p = argparse.ArgumentParser(description="Сравнение времени predict base vs optimized")
    p.add_argument("--n-ops", type=int, default=4, help="число синтетических operation_id")
    p.add_argument("--n-months", type=int, default=28, help="длина истории в месяцах (monthly)")
    p.add_argument("--resist", type=int, default=1, help="resist_id в синтетике")
    p.add_argument("--repeat", type=int, default=1, help="повторов замера на вариант")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    hs = base_mod.HISTORY_START_DATE
    df = build_synthetic_history_df(
        n_operations=args.n_ops,
        n_months=args.n_months,
        resist_id=args.resist,
        seed=args.seed,
        history_start_date=hs,
    )
    repo_base = SyntheticDfHistoryRepository(df, hs)
    repo_opt = SyntheticDfHistoryRepository(df, hs)
    operations = list(range(1, args.n_ops + 1))
    resist_str = str(args.resist)

    n_cfg_base = len(base_mod.allowed_configs())
    n_cfg_opt = len(opt_mod.allowed_configs())

    facade_base = base_mod.PredictOparationCountV2(repository=repo_base)
    facade_opt = opt_mod.PredictOparationCountV2(repository=repo_opt)

    def run_base():
        facade_base.predict(operations, resist_str)

    def run_opt():
        facade_opt.predict(operations, resist_str)

    # Прогрев (warmup): по одному проходу каждого варианта (кэш import/компиляция)
    gc.collect()
    run_base()
    gc.collect()
    run_opt()

    t_base = _bench_one("base", run_base, args.repeat)
    t_opt = _bench_one("opt", run_opt, args.repeat)

    mean_base = statistics.mean(t_base)
    mean_opt = statistics.mean(t_opt)
    speedup = mean_base / mean_opt if mean_opt > 0 else float("inf")

    print("=== Synthetic benchmark (benchmark) predict v2 ===")
    print(f"operations={operations}, n_months={args.n_months}, resist={args.resist}, repeat={args.repeat}")
    print(f"rows in df={len(df)}")
    print(f"SERIES_CONFIGS count: baseline={n_cfg_base}, optimized={n_cfg_opt}")
    if n_cfg_base != n_cfg_opt:
        print(
            "(разное число конфигов: в baseline возможны NF-* при установленном neuralforecast)"
        )
    print(f"time baseline (s): mean={mean_base:.4f}  all={['%.4f' % x for x in t_base]}")
    print(f"time optimized (s): mean={mean_opt:.4f}  all={['%.4f' % x for x in t_opt]}")
    print(f"speedup (ускорение) baseline_time / optimized_time = {speedup:.3f}x")
    if mean_opt < mean_base:
        print(f"optimized быстрее на {(1 - mean_opt / mean_base) * 100:.1f}%")
    else:
        print("optimized не быстрее при данных параметрах (см. число конфигов и шум замера)")


if __name__ == "__main__":
    main()
