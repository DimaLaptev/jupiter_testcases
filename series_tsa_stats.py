"""
Описательная и рядовая статистика (descriptive and time-series statistics) по месячным
`fact_value` на уровне серий `(resist_id, operation_id)` — для выбора семейств моделей (model
families) и весов (sample_weight / `calculate_minute`).

Препроцессинг (preprocessing) до `df_model39` — тот же, что в
`notebooks/34_comparison_per_series_screenshot_top_configs.ipynb` (ячейки c3, c5), через
`load_data_model39()` = `load_model39_like_notebook28` в этом репозитории.

См. ТЗ: `memory/series_tsa_stats_script_prompt.md`.

Агрегация (aggregation) дубликатов (duplicate rows) в одном календарном месяце (month):
`fact_value` — сумма (sum), `calculate_minute` и `calc_resist_10` — среднее (mean) по дублям
(требование docstring: одна запись на `(resist_id, operation_id, year, month)` перед метриками).

Запуск (из корня репозитория):
  python scripts/series_tsa_stats.py --resist-ids 124 -o data/processed/series_tsa_stats.xlsx
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from export_resist_fte_period import load_model39_like_notebook28
from export_resist_operation_facts import default_raw_files

# Аналог `load_data_model39` из ТЗ: совпадает с nb34 c5.
load_data_model39 = load_model39_like_notebook28

DEFAULT_RESIST_IDS = [124]
TEST_YEAR = 2025
TEST_MONTHS = (7, 8, 9, 10, 11, 12)
CALC_RESIST_COL = "calc_resist_10"
EPS = 1e-9
MIN_MONTHS_SEASONAL_CORR = 25  # для пары (y, y-12) нужно n >= 25 наблюдений (indices)


def _parse_int_list_from_cli(values: list[str] | None) -> list[int] | None:
    """Собрать целочисленные id из повторяющихся аргументов и/или '124,125'."""
    if not values:
        return None
    out: list[int] = []
    for v in values:
        for part in re.split(r"[,\s;]+", str(v).strip()):
            if not part:
                continue
            out.append(int(part))
    return out


def _resist_ids_from_env() -> list[int] | None:
    raw = os.environ.get("RESIST_IDS", "").strip()
    if not raw:
        return None
    return [int(p.strip()) for p in re.split(r"[,\s;]+", raw) if p.strip()]


def validate_resist_ids(df: pd.DataFrame, resist_ids: list[int]) -> list[int]:
    resist_ids = list(dict.fromkeys(resist_ids))
    avail = {int(x) for x in df["resist_id"].dropna().unique()}
    missing = [r for r in resist_ids if r not in avail]
    if missing:
        sample = sorted(avail)[:15]
        raise ValueError(
            f"Нет данных для resist_id={missing}. Примеры доступных id: {sample}..."
        )
    return resist_ids


def apply_test_split_mask(df: pd.DataFrame) -> pd.Series:
    m = (df["year"] == TEST_YEAR) & (df["month"].isin(TEST_MONTHS))
    return ~m


def aggregate_months(df: pd.DataFrame) -> pd.DataFrame:
    """Одна строка на (resist_id, operation_id, year, month)."""
    gcols = ["resist_id", "operation_id", "year", "month"]
    agg: dict[str, str] = {"fact_value": "sum"}
    if "calculate_minute" in df.columns:
        agg["calculate_minute"] = "mean"
    if CALC_RESIST_COL in df.columns:
        agg[CALC_RESIST_COL] = "mean"
    out = df.groupby(gcols, sort=True, as_index=False).agg(agg)
    out = out.sort_values(
        ["resist_id", "operation_id", "year", "month"],
        kind="mergesort",
    ).reset_index(drop=True)
    out["date"] = pd.to_datetime(
        dict(year=out["year"], month=out["month"], day=1), errors="coerce"
    )
    return out


def _span_months_inclusive(ymin: int, mmin: int, ymax: int, mmax: int) -> int:
    return (ymax - ymin) * 12 + (mmax - mmin) + 1


def _ols_slope(y: np.ndarray) -> float:
    """Наклон OLS: y = a + b*x, x = 0..n-1."""
    n = len(y)
    if n < 2:
        return float("nan")
    x = np.arange(n, dtype=float)
    x_m = (n - 1) / 2.0
    y_m = float(np.mean(y))
    sxx = float(np.sum((x - x_m) ** 2)) or 1.0
    sxy = float(np.sum((x - x_m) * (y - y_m)))
    return sxy / sxx


def _acf_lag(y: np.ndarray, lag: int) -> float:
    """ACF (autocorrelation) на лаге (lag) через corrcoef (как в pandas)."""
    n = len(y)
    if n <= lag or lag < 1:
        return float("nan")
    a, b = y[lag:], y[:-lag]
    if a.size < 2:
        return float("nan")
    c = np.corrcoef(a, b)[0, 1]
    return float(c) if not np.isnan(c) else float("nan")


def _seasonal_lag12_corr(y: np.ndarray) -> float:
    """Корреляция Пирсона (Pearson) между y_t и y_{t-12} (при n >= MIN_MONTHS_SEASONAL_CORR)."""
    n = len(y)
    if n < MIN_MONTHS_SEASONAL_CORR:
        return float("nan")
    a, b = y[12:], y[:-12]
    if a.size < 2:
        return float("nan")
    c = np.corrcoef(a, b)[0, 1]
    return float(c) if not np.isnan(c) else float("nan")


def per_series_table(df_m: pd.DataFrame) -> pd.DataFrame:
    """df_m: после aggregate_months, отсортирован по времени (time) внутри групп."""
    rows: list[dict[str, Any]] = []
    have_cm = "calculate_minute" in df_m.columns
    have_cr = CALC_RESIST_COL in df_m.columns
    gcols = ["resist_id", "operation_id"]
    for (rid, opid), grp in df_m.groupby(gcols, sort=True):
        grp = grp.sort_values(["year", "month"], kind="mergesort")
        y = grp["fact_value"].astype(float).values
        n = len(y)
        zero_count = int(np.sum(y == 0.0)) if n else 0
        y_nonzero = y[y != 0.0]
        ym = float(np.mean(y)) if n else float("nan")
        ys = float(np.std(y, ddof=0)) if n else float("nan")
        if ym > EPS:
            cv = ys / ym
        else:
            cv = float("nan")
        q1, q3 = float(np.nanpercentile(y, 25)), float(np.nanpercentile(y, 75))
        iqr = q3 - q1
        nz_std = float(np.std(y_nonzero, ddof=0)) if y_nonzero.size else float("nan")
        t_first = pd.Timestamp(
            year=int(grp["year"].iloc[0]), month=int(grp["month"].iloc[0]), day=1
        )
        t_last = pd.Timestamp(
            year=int(grp["year"].iloc[-1]), month=int(grp["month"].iloc[-1]), day=1
        )
        span = _span_months_inclusive(
            int(grp["year"].iloc[0]),
            int(grp["month"].iloc[0]),
            int(grp["year"].iloc[-1]),
            int(grp["month"].iloc[-1]),
        )
        r = {
            "resist_id": int(rid),
            "operation_id": str(opid),
            "n_obs": n,
            "date_min": t_first,
            "date_max": t_last,
            "span_months": int(span),
            "zero_count": zero_count,
            "zero_fraction": (zero_count / n) if n else float("nan"),
            "mean": ym,
            "std": ys,
            "median": float(np.median(y)) if n else float("nan"),
            "min": float(np.min(y)) if n else float("nan"),
            "max": float(np.max(y)) if n else float("nan"),
            "cv": float(cv) if not np.isnan(cv) else float("nan"),
            "iqr": iqr,
            "nonzero_std": nz_std,
            "trend_proxy": _ols_slope(y),
            "seasonal_strength_proxy": _seasonal_lag12_corr(y),
            "acf_lag1": _acf_lag(y, 1) if n >= 2 else float("nan"),
            "acf_lag12": _acf_lag(y, 12) if n > 12 else float("nan"),
        }
        if have_cm:
            cm = pd.to_numeric(grp["calculate_minute"], errors="coerce")
            r["calculate_minute_median"] = float(cm.median()) if cm.notna().any() else float(
                "nan"
            )
        else:
            r["calculate_minute_median"] = float("nan")
        if have_cr:
            cr = pd.to_numeric(grp[CALC_RESIST_COL], errors="coerce")
            r["calc_resist_10_median"] = float(cr.median()) if cr.notna().any() else float(
                "nan"
            )
        else:
            r["calc_resist_10_median"] = float("nan")
        rows.append(r)
    out = pd.DataFrame(rows)
    return out.sort_values(["resist_id", "operation_id"], kind="mergesort").reset_index(
        drop=True
    )


def per_resist_table(df_per: pd.DataFrame) -> pd.DataFrame:
    """Агрегат по `resist_id` (one row per resist_id)."""
    if df_per.empty:
        return pd.DataFrame()
    g = df_per.groupby("resist_id", sort=True)
    rows = []
    for rid, sub in g:
        zf = sub["zero_fraction"]
        rows.append(
            {
                "resist_id": int(rid),
                "n_series": int(sub["operation_id"].nunique()),
                "sum_n_obs": int(sub["n_obs"].sum()),
                "mean_n_obs": float(sub["n_obs"].mean()),
                "mean_zero_fraction": float(sub["zero_fraction"].mean()),
                "mean_std": float(sub["std"].mean()),
                "mean_of_series_means": float(sub["mean"].mean()),
                "zero_fraction_q25": float(zf.quantile(0.25)),
                "zero_fraction_q50": float(zf.quantile(0.50)),
                "zero_fraction_q75": float(zf.quantile(0.75)),
            }
        )
    return pd.DataFrame(rows).sort_values("resist_id", kind="mergesort").reset_index(drop=True)


def build_gaps_table(df_m: pd.DataFrame) -> pd.DataFrame:
    """Long-таблица: отсутствующие (missing) календарные месяцы в [date_min, date_max] по серии."""
    gap_rows: list[dict[str, Any]] = []
    gcols = ["resist_id", "operation_id"]
    for (rid, opid), grp in df_m.groupby(gcols, sort=True):
        grp = grp.sort_values(["year", "month"], kind="mergesort")
        y0, m0 = int(grp["year"].iloc[0]), int(grp["month"].iloc[0])
        y1, m1 = int(grp["year"].iloc[-1]), int(grp["month"].iloc[-1])
        cur = pd.Period(year=y0, month=m0, freq="M")
        endp = pd.Period(year=y1, month=m1, freq="M")
        have = {(int(r["year"]), int(r["month"])) for _, r in grp.iterrows()}
        while cur <= endp:
            y, m = int(cur.year), int(cur.month)
            if (y, m) not in have:
                gap_rows.append(
                    {
                        "resist_id": int(rid),
                        "operation_id": str(opid),
                        "year": y,
                        "month": m,
                    }
                )
            cur = cur + 1
    return (
        pd.DataFrame(gap_rows)
        if gap_rows
        else pd.DataFrame(
            columns=["resist_id", "operation_id", "year", "month"]
        )
    ).sort_values(
        ["resist_id", "operation_id", "year", "month"],
        kind="mergesort",
    ).reset_index(
        drop=True
    )


def _git_head() -> str:
    try:
        root = Path(__file__).resolve().parent.parent
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if p.returncode == 0 and p.stdout:
            return p.stdout.strip()[:12]
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def build_metadata(
    resist_ids: list[int],
    raw_files: list[Path],
    *,
    use_test_split: bool,
    use_gaps: bool,
    write_parquet: bool,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = [
        {"key": "RESIST_IDS", "value": ",".join(str(x) for x in resist_ids)},
        {"key": "raw_files", "value": ";".join(str(p) for p in raw_files)},
        {"key": "use_test_split", "value": str(use_test_split)},
        {"key": "TEST_YEAR (test split)", "value": str(TEST_YEAR) if use_test_split else "n/a"},
        {"key": "TEST_MONTHS (test split)", "value": str(list(TEST_MONTHS)) if use_test_split else "n/a"},
        {"key": "gaps sheet", "value": str(use_gaps)},
        {"key": "parquet export", "value": str(write_parquet)},
        {"key": "python", "value": sys.version.split()[0]},
        {"key": "pandas", "value": pd.__version__},
        {"key": "numpy", "value": np.__version__},
        {"key": "git_commit (short)", "value": _git_head() or "n/a"},
    ]
    return pd.DataFrame(rows)


def _ensure_openpyxl() -> None:
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("Для записи Excel (Excel) установите: pip install openpyxl", file=sys.stderr)
        sys.exit(1)


def write_excel_sheets(
    out_path: Path,
    per_series: pd.DataFrame,
    per_resist: pd.DataFrame,
    metadata: pd.DataFrame,
    gaps: pd.DataFrame | None = None,
) -> None:
    _ensure_openpyxl()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as w:
        per_series.to_excel(w, sheet_name="per_series", index=False)
        per_resist.to_excel(w, sheet_name="per_resist", index=False)
        metadata.to_excel(w, sheet_name="metadata", index=False)
        if gaps is not None:
            gaps.to_excel(w, sheet_name="gaps", index=False)


def write_parquet_optional(
    out_xlsx: Path, per_series: pd.DataFrame, per_resist: pd.DataFrame
) -> None:
    d, stem = out_xlsx.parent, out_xlsx.stem
    d.mkdir(parents=True, exist_ok=True)
    per_series.to_parquet(d / f"{stem}_per_series.parquet", index=False)
    per_resist.to_parquet(d / f"{stem}_per_resist.parquet", index=False)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Статистика рядов (time series stats) по resist_id/operation_id (nb34-совместимый load)."
    )
    p.add_argument(
        "--resist-ids",
        nargs="*",
        default=None,
        help="Список resist_id: можно повторить флаг, через пробел, или '124,125'. "
        "Если пусто — $RESIST_IDS или константа DEFAULT_RESIST_IDS.",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Путь к .xlsx (по умолчанию data/processed/series_tsa_stats.xlsx от корня).",
    )
    p.add_argument(
        "--use-test-split",
        action="store_true",
        help="Исключить тест: год (year) 2025 и месяцы 7..12 (как в nb34).",
    )
    p.add_argument(
        "--gaps",
        action="store_true",
        help="Добавить лист (sheet) gaps с пропущенными (missing) месяцами.",
    )
    p.add_argument(
        "--parquet",
        action="store_true",
        help="Дополнительно записать per_series/per_resist в Parquet (Parquet) рядом с xlsx.",
    )
    p.add_argument(
        "--include-excluded-resists",
        action="store_true",
        help="Не фильтровать EXCLUDED_RESIST_IDS при загрузке (как в load_model39).",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    root = Path(__file__).resolve().parent.parent
    out_path = args.output
    if out_path is None:
        out_path = root / "data" / "processed" / "series_tsa_stats.xlsx"

    if args.resist_ids is None or len(args.resist_ids) == 0:
        resist_ids = _resist_ids_from_env() or list(DEFAULT_RESIST_IDS)
    else:
        parsed = _parse_int_list_from_cli([str(x) for x in args.resist_ids])
        resist_ids = parsed if parsed else list(DEFAULT_RESIST_IDS)

    raw_files = default_raw_files()
    try:
        df = load_data_model39(raw_files, include_excluded=bool(args.include_excluded_resists))
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    if df.empty:
        print("df_model39 пуст — проверьте data/raw (raw).", file=sys.stderr)
        sys.exit(1)

    resist_ids = validate_resist_ids(df, resist_ids)
    df = df[df["resist_id"].isin(resist_ids)].copy()

    if args.use_test_split:
        df = df.loc[apply_test_split_mask(df)].copy()
        if df.empty:
            print("После test-split (test split) нет строк.", file=sys.stderr)
            sys.exit(1)

    df_m = aggregate_months(df)
    if df_m.empty:
        print("После агрегации по месяцам (month) нет данных.", file=sys.stderr)
        sys.exit(1)

    per_s = per_series_table(df_m)
    per_r = per_resist_table(per_s)
    meta = build_metadata(
        resist_ids,
        [p for p in raw_files if p.exists()],
        use_test_split=bool(args.use_test_split),
        use_gaps=bool(args.gaps),
        write_parquet=bool(args.parquet),
    )
    gaps_df: pd.DataFrame | None = None
    if args.gaps:
        gaps_df = build_gaps_table(df_m)

    write_excel_sheets(out_path, per_s, per_r, meta, gaps_df)
    if args.parquet:
        try:
            write_parquet_optional(out_path, per_s, per_r)
        except (ImportError, ValueError) as e:
            print("Parquet: нужен pyarrow (pyarrow) или fastparquet:", e, file=sys.stderr)
            sys.exit(1)

    print(f"OK: {out_path}")


if __name__ == "__main__":
    main()