# -*- coding: utf-8 -*-
"""Аудит (audit) всех SERIES_CONFIGS: поиск аномальных прогнозов на горизонте production.

Использует тот же пайплайн (pipeline), что ProductionForecaster._series_forecast:
вся история — train, 4 будущих месяца — test.

Пример:
  python scripts/audit_forecast_configs_outliers.py 145 --operations 11111
  python scripts/audit_forecast_configs_outliers.py 127 --operations 8847 --skip-fn statsforecast
  python scripts/audit_forecast_configs_outliers.py 127 --operations 8847 --skip-fn statsforecast,statsforecast_intermittent
  python scripts/audit_forecast_configs_outliers.py 145 --csv-out audit_145.csv --no-isolate
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pickle
import subprocess
import sys
import tempfile
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Set

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
    from scripts.test_predict_operation_count_v2 import HISTORY_START_DATE
except ImportError:
    HISTORY_START_DATE = datetime(2022, 12, 31)

RAW_DIR = _ROOT / "data" / "raw"
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]

DEFAULT_CONFIG_TIMEOUT_SEC = 180
_WIN_ACCESS_VIOLATION = 3221225477


def _coerce_operation_id(value: object) -> object:
    try:
        x = float(value)
        return int(x) if x == int(x) else x
    except (TypeError, ValueError):
        return value


def _parse_fn_list(values: Optional[Sequence[str]]) -> Set[str]:
    out: Set[str] = set()
    if not values:
        return out
    for item in values:
        for part in str(item).split(","):
            token = part.strip()
            if token:
                out.add(token)
    return out


def _filter_configs(
    configs: Mapping[str, dict],
    *,
    skip_fn: Set[str],
    include_fn: Set[str],
) -> dict[str, dict]:
    filtered: dict[str, dict] = {}
    for name, cfg in configs.items():
        fn = str(cfg.get("fn", ""))
        if skip_fn and fn in skip_fn:
            continue
        if include_fn and fn not in include_fn:
            continue
        filtered[name] = cfg
    return filtered


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "LOKY_MAX_CPU_COUNT",
    ):
        env.setdefault(key, "1")
    return env


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


def _dispatch_in_process(
    df_feat: pd.DataFrame,
    mask_train: pd.Series,
    mask_test: pd.Series,
    resist_id: int,
    cfg_name: str,
    cfg: dict,
    horizon: int,
) -> tuple[np.ndarray, str]:
    dispatcher = ConfigDispatcher()
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
        return y_arr, ""
    except Exception as exc:
        return np.zeros(horizon, dtype=float), str(exc)
    finally:
        cleanup_memory()


def _worker_entry(payload_path: str, cfg_name: str, result_path: str) -> int:
    """Точка входа (entry point) дочернего процесса: один конфиг → pickle-результат."""
    for key in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "LOKY_MAX_CPU_COUNT",
    ):
        os.environ.setdefault(key, "1")

    with open(payload_path, "rb") as fh:
        payload = pickle.load(fh)

    configs = allowed_configs()
    cfg = configs.get(cfg_name)
    if cfg is None:
        result = {"status": "error", "message": f"unknown config {cfg_name!r}"}
    else:
        y_arr, err = _dispatch_in_process(
            payload["df_feat"],
            payload["mask_train"],
            payload["mask_test"],
            int(payload["resist_id"]),
            cfg_name,
            cfg,
            int(payload["horizon"]),
        )
        if err:
            result = {"status": "error", "message": err, "y_arr": y_arr.tolist()}
        else:
            result = {"status": "ok", "y_arr": y_arr.tolist()}

    with open(result_path, "wb") as fh:
        pickle.dump(result, fh)
    return 0


def _crash_message(exit_code: int) -> str:
    if exit_code == _WIN_ACCESS_VIOLATION:
        return "segmentation fault / access violation (native crash)"
    if exit_code < 0:
        return f"process killed by signal {-exit_code} (possible native crash)"
    if exit_code != 0:
        return f"subprocess exit code {exit_code} (possible native crash)"
    return ""


def _dispatch_isolated(
    payload_path: str,
    cfg_name: str,
    horizon: int,
    timeout_sec: int,
) -> tuple[np.ndarray, str]:
    result_path = f"{payload_path}.{hashlib.md5(cfg_name.encode('utf-8')).hexdigest()}.result.pkl"
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", payload_path, cfg_name, result_path],
            env=_subprocess_env(),
            timeout=timeout_sec,
            capture_output=True,
        )
    except subprocess.TimeoutExpired:
        return np.zeros(horizon, dtype=float), f"timeout after {timeout_sec}s"
    except OSError as exc:
        return np.zeros(horizon, dtype=float), f"subprocess failed: {exc}"

    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        msg = _crash_message(proc.returncode)
        if stderr:
            msg = f"{msg}; stderr: {stderr[:500]}" if msg else stderr[:500]
        return np.zeros(horizon, dtype=float), msg or "subprocess failed"

    if not Path(result_path).exists():
        return np.zeros(horizon, dtype=float), "worker finished without result file"

    try:
        with open(result_path, "rb") as fh:
            result = pickle.load(fh)
    except Exception as exc:
        return np.zeros(horizon, dtype=float), f"cannot read worker result: {exc}"
    finally:
        try:
            Path(result_path).unlink(missing_ok=True)
        except OSError:
            pass

    y_arr = np.asarray(result.get("y_arr", []), dtype=float).ravel()
    if y_arr.size != horizon:
        y_arr = np.resize(y_arr, horizon)
    if result.get("status") != "ok":
        return y_arr, str(result.get("message", "worker error"))
    return y_arr, ""


def _write_payload(
    df_feat: pd.DataFrame,
    mask_train: pd.Series,
    mask_test: pd.Series,
    resist_id: int,
    horizon: int,
) -> str:
    fd, path = tempfile.mkstemp(prefix="audit_fc_payload_", suffix=".pkl")
    os.close(fd)
    payload = {
        "df_feat": df_feat,
        "mask_train": mask_train,
        "mask_test": mask_test,
        "resist_id": int(resist_id),
        "horizon": int(horizon),
    }
    with open(path, "wb") as fh:
        pickle.dump(payload, fh)
    return path


def audit_operation(
    history: dict,
    operation_id: object,
    resist_id: int,
    *,
    horizon: int = FORECAST_HORIZON,
    rel_cap: float = FORECAST_REL_CAP,
    skip_fn: Optional[Set[str]] = None,
    include_fn: Optional[Set[str]] = None,
    isolate: bool = True,
    config_timeout_sec: int = DEFAULT_CONFIG_TIMEOUT_SEC,
) -> pd.DataFrame:
    configs = _filter_configs(
        allowed_configs(),
        skip_fn=skip_fn or set(),
        include_fn=include_fn or set(),
    )
    df_feat, mask_train, mask_test = _build_forecast_frame(
        history, operation_id, resist_id, horizon,
    )
    y_hist = df_feat.loc[mask_train, "fact_value"].astype(float).values
    train_max = float(np.max(y_hist)) if len(y_hist) else 0.0
    cap = _forecast_cap_from_hist(y_hist, rel_cap=rel_cap)

    payload_path: Optional[str] = None
    if isolate:
        payload_path = _write_payload(df_feat, mask_train, mask_test, resist_id, horizon)

    rows: list[dict] = []
    try:
        for cfg_name, cfg in configs.items():
            fn = cfg.get("fn", "")
            if isolate and payload_path is not None:
                y_arr, err_msg = _dispatch_isolated(
                    payload_path, cfg_name, horizon, config_timeout_sec,
                )
            else:
                y_arr, err_msg = _dispatch_in_process(
                    df_feat, mask_train, mask_test, resist_id, cfg_name, cfg, horizon,
                )

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
                "isolated": isolate,
            })
    finally:
        if payload_path:
            try:
                Path(payload_path).unlink(missing_ok=True)
            except OSError:
                pass
            prefix = Path(payload_path).name
            for p in Path(tempfile.gettempdir()).glob(f"{prefix}.*.result.pkl"):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    out = pd.DataFrame(rows)
    if out.empty:
        return out
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
    parser.add_argument("resist_id", type=int, nargs="?", help="resist_id (не нужен в режиме --worker)")
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
    parser.add_argument(
        "--skip-fn",
        action="append",
        default=[],
        metavar="FN",
        help=(
            "Пропустить семейство fn (можно повторять и через запятую): "
            "statsforecast, statsforecast_intermittent, local_supervised, ..."
        ),
    )
    parser.add_argument(
        "--include-fn",
        action="append",
        default=[],
        metavar="FN",
        help="Аудит только указанных fn (пересекается с --skip-fn)",
    )
    parser.add_argument(
        "--no-isolate",
        action="store_true",
        help="Без subprocess: быстрее, но segfault убьёт весь прогон",
    )
    parser.add_argument(
        "--config-timeout",
        type=int,
        default=DEFAULT_CONFIG_TIMEOUT_SEC,
        help=f"Таймаут (timeout) на один конфиг в subprocess, сек (default {DEFAULT_CONFIG_TIMEOUT_SEC})",
    )
    parser.add_argument("--worker", nargs=3, metavar=("PAYLOAD", "CONFIG", "RESULT"), help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        payload_path, cfg_name, result_path = args.worker
        raise SystemExit(_worker_entry(payload_path, cfg_name, result_path))

    if args.resist_id is None:
        parser.error("resist_id обязателен вне режима --worker")

    skip_fn = _parse_fn_list(args.skip_fn)
    include_fn = _parse_fn_list(args.include_fn)
    isolate = not args.no_isolate

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
            skip_fn=skip_fn,
            include_fn=include_fn,
            isolate=isolate,
            config_timeout_sec=args.config_timeout,
        )
        all_frames.append(report)
        view = report
        if args.only_invalid:
            view = report.loc[~report["holdout_valid"]]
        skipped_note = f", skip_fn={sorted(skip_fn)}" if skip_fn else ""
        mode_note = "subprocess" if isolate else "in-process"
        print(
            f"\n=== resist={args.resist_id} operation={op} "
            f"configs={len(report)}/{len(SERIES_CONFIGS)} mode={mode_note}{skipped_note} ==="
        )
        if view.empty:
            print("(нет строк по фильтру)")
        else:
            cols = [
                "config_name", "fn", "max_pred", "pred_ratio",
                "holdout_valid", "monotonic_explosion", "error", "forecast",
            ]
            show_cols = [c for c in cols if c in view.columns]
            print(view[show_cols].head(25).to_string(index=False))

        crash_n = int(report["error"].astype(str).str.contains("crash|segmentation|violation", case=False, regex=True).sum()) if not report.empty and "error" in report.columns else 0
        if crash_n:
            print(f"native crash: {crash_n} конфиг(ов) — см. колонку error", file=sys.stderr)

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
