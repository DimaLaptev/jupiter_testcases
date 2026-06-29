# -*- coding: utf-8 -*-
"""Аудит (audit) всех SERIES_CONFIGS: поиск аномальных прогнозов на горизонте production.

Использует тот же пайплайн (pipeline), что ProductionForecaster._series_forecast:
вся история — train, 4 будущих месяца — test.

Пример:
  python scripts/audit_forecast_configs_outliers.py 145 --operations 11111
  python scripts/audit_forecast_configs_outliers.py 145 --csv-out audit_145.csv
"""

from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from scripts.production_comp_predict_operation_count_v2 import (  # noqa: E402
    FORECAST_HORIZON,
    ConfigDispatcher,
    OperationHistoryCleaner,
    _add_nb37_features,
    allowed_configs,
)
from scripts.production_comparison_tsa_per_series_nb37_trainers import (  # noqa: E402
    FORECAST_REL_CAP,
    SERIES_CONFIGS,
    _forecast_cap_from_hist,
    cleanup_memory,
    holdout_forecast_is_valid,
)

try:
    from scripts.nb37_raw_model39_load import load_df_model39_from_nb37_raw_files
except ImportError:
    load_df_model39_from_nb37_raw_files = None  # type: ignore[misc, assignment]

try:
    from scripts.test_predict_operation_count_v2 import CsvHistoryRepository, HISTORY_START_DATE
except ImportError:
    CsvHistoryRepository = None  # type: ignore[misc, assignment]
    HISTORY_START_DATE = datetime(2022, 12, 31)

RAW_DIR = _ROOT / "data" / "raw"
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]


def _coerce_operation_id(value: object) -> object:
    try:
        x = float(value)
        return int(x) if x == int(x) else x
    except (TypeError, ValueError):
        return value


def _monotonic_explosion(fc: np.ndarray, factor: float = 3.0) -> bool:
    if fc.size < 2:
        return False
    prev = max(float(fc[0]), 1e-9)
    for v in fc[1:]:
        cur = float(v)
        if cur > prev * factor:
            return True
        prev = max(cur, 1e-9)
    return False


def _build_forecast_frame(
    history: dict,
    operation_id: object,
    resist_id: int,
    horizon: int,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    cl = OperationHistoryCleaner()
    df_sorted = cl.to_dataframe(history, operation_id, resist_id).sort_values("date").reset_index(drop=True)
    if df_sorted.empty:
        raise ValueError("empty history")

    last_date = pd.Timestamp(df_sorted["date"].iloc[-1]).to_period("M").to_timestamp()
    future_rows = []
    for k in range(1, horizon + 1):
        ts = last_date + pd.DateOffset(months=k)
        future_rows.append({
            "resist_id": int(resist_id),
            "operation_id": operation_id,
            "date": pd.Timestamp(ts),
            "fact_value": np.nan,
            "year": int(ts.year),
            "month": int(ts.month),
        })
    df_full = pd.concat([df_sorted, pd.DataFrame(future_rows)], ignore_index=True)
    df_full = df_full.sort_values(["operation_id", "date"]).reset_index(drop=True)
    mask_train = df_full["fact_value"].notna()
    mask_test = ~mask_train
    df_feat = _add_nb37_features(df_full, mask_train)
    return df_feat, mask_train, mask_test


def audit_operation(
    history: dict,
    operation_id: object,
    resist_id: int,
    *,
    horizon: int = FORECAST_HORIZON,
    rel_cap: float = FORECAST_REL_CAP,
) -> pd.DataFrame:
    dispatcher = ConfigDispatcher()
    configs = allowed_configs()
    df_feat, mask_train, mask_test = _build_forecast_frame(
        history, operation_id, resist_id, horizon,
    )
    y_hist = df_feat.loc[mask_train, "fact_value"].astype(float).values
    train_max = float(np.max(y_hist)) if len(y_hist) else 0.0
    cap = _forecast_cap_from_hist(y_hist, rel_cap=rel_cap)

    rows: list[dict] = []
    for cfg_name in configs:
        cfg = configs[cfg_name]
        fn = cfg.get("fn", "")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                y_hat = dispatcher.dispatch(
                    df_feat,
                    mask_train,
                    mask_test,
                    int(resist_id),
                    cfg_name,
                    cfg,
                    warning_rows=[],
                )
            y_arr = np.asarray(y_hat, dtype=float).ravel()
            if y_arr.size != horizon:
                y_arr = np.resize(y_arr, horizon)
            err_msg = ""
        except Exception as exc:
            y_arr = np.zeros(horizon, dtype=float)
            err_msg = str(exc)

        max_pred = float(np.max(y_arr)) if y_arr.size else 0.0
        ratio = max_pred / train_max if train_max > 0 else (max_pred if max_pred > 0 else 0.0)
        rows.append({
            "resist_id": resist_id,
            "operation_id": operation_id,
            "config_name": cfg_name,
            "fn": fn,
            "sk_model": cfg.get("sk_model", ""),
            "family": cfg.get("family", ""),
            "train_max": train_max,
            "cap": cap,
            "max_pred": max_pred,
            "pred_ratio": ratio,
            "any_non_finite": not np.all(np.isfinite(y_arr)),
            "holdout_valid": holdout_forecast_is_valid(y_arr, y_hist, rel_cap=rel_cap),
            "monotonic_explosion": _monotonic_explosion(y_arr),
            "forecast": list(np.round(y_arr, 4)),
            "error": err_msg,
        })
        cleanup_memory()

    out = pd.DataFrame(rows)
    return out.sort_values("max_pred", ascending=False).reset_index(drop=True)


def _history_from_csv(df: pd.DataFrame, resist_id: int, operation_id: object) -> dict:
    sub = df.loc[
        (df["resist_id"] == resist_id) & (df["operation_id"] == operation_id)
    ].copy()
    if sub.empty:
        return {}
    now_period = (datetime.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    sub["_ts"] = pd.to_datetime(sub["date"], errors="coerce")
    sub = sub.dropna(subset=["_ts"])
    start_bound = pd.Timestamp(HISTORY_START_DATE)
    end_bound = pd.Timestamp(now_period)
    sub = sub.loc[(sub["_ts"] > start_bound) & (sub["_ts"] < end_bound)]
    history: dict = {}
    for _, row in sub.iterrows():
        ts = pd.Timestamp(row["_ts"]).to_period("M").to_timestamp()
        history[ts] = float(row.get("fact_value", 0) or 0)
    return history


def main() -> None:
    parser = argparse.ArgumentParser(description="Аудит прогнозов по всем SERIES_CONFIGS.")
    parser.add_argument("resist_id", type=int)
    parser.add_argument(
        "--operations",
        default="11111",
        help="operation_id через запятую",
    )
    parser.add_argument("--horizon", type=int, default=FORECAST_HORIZON)
    parser.add_argument("--rel-cap", type=float, default=FORECAST_REL_CAP)
    parser.add_argument("--csv-out", default=None, help="Путь к CSV с полным отчётом")
    parser.add_argument(
        "--only-invalid",
        action="store_true",
        help="Печатать только конфиги с holdout_valid=False",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Синтетическая история (без CSV nb37) для smoke-теста аудита",
    )
    args = parser.parse_args()

    ops = [_coerce_operation_id(p.strip()) for p in args.operations.split(",") if p.strip()]

    all_frames: list[pd.DataFrame] = []
    for op in ops:
        if args.synthetic:
            months = pd.date_range("2023-01", periods=39, freq="MS")
            vals = [50 + int(5 * np.sin(i / 3)) for i in range(36)]
            vals.extend([67, 56, 78])
            hist = {m: float(v) for m, v in zip(months, vals)}
        else:
            if load_df_model39_from_nb37_raw_files is None:
                print("nb37 loader недоступен", file=sys.stderr)
                sys.exit(1)
            for p in RAW_FILES:
                if not p.exists():
                    print(f"Нет файла {p}; используйте --synthetic", file=sys.stderr)
                    sys.exit(1)
            df = load_df_model39_from_nb37_raw_files(RAW_FILES)
            hist = _history_from_csv(df, args.resist_id, op)
        if not hist:
            print(f"Нет истории: resist={args.resist_id} op={op}", file=sys.stderr)
            continue
        report = audit_operation(
            hist,
            op,
            args.resist_id,
            horizon=args.horizon,
            rel_cap=args.rel_cap,
        )
        all_frames.append(report)
        view = report
        if args.only_invalid:
            view = report.loc[~report["holdout_valid"]]
        print(f"\n=== resist={args.resist_id} operation={op} configs={len(SERIES_CONFIGS)} ===")
        if view.empty:
            print("(нет строк по фильтру)")
        else:
            cols = [
                "config_name", "fn", "max_pred", "pred_ratio",
                "holdout_valid", "monotonic_explosion", "forecast",
            ]
            print(view[cols].head(25).to_string(index=False))

    if not all_frames:
        sys.exit(2)

    combined = pd.concat(all_frames, ignore_index=True)
    if args.csv_out:
        out_path = Path(args.csv_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
