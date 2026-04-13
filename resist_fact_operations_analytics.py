"""
Анализ факта (fact_value) по операциям (operation_id) для выбранных resist_id.

Предобработка (preprocessing) совпадает с notebooks/27_comparison_per_series_trimmed_extras.ipynb
(ячейка загрузки до проверки RESIST_IDS).

Запуск из корня репозитория:
  python scripts/resist_fact_operations_analytics.py --resist-id 124 --out-xlsx data/processed/fact_ops_124.xlsx
  python scripts/resist_fact_operations_analytics.py --resist-ids 124,200 --raw data/raw/data-2022.csv ...

Если не передавать --resist-id и --resist-ids, берётся список RESIST_IDS из начала этого файла (см. ниже).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows

_ROOT = Path(__file__).resolve().parent.parent
_RAW_DIR = _ROOT / "data" / "raw"
_DEFAULT_RAW_FILES = [
    _RAW_DIR / "data-2022.csv",
    _RAW_DIR / "data-2023.csv",
    _RAW_DIR / "data-2024.csv",
    _RAW_DIR / "data-2025.csv",
]
_DEFAULT_OUT = _ROOT / "data" / "processed" / "resist_fact_operations_analytics.xlsx"

# Список resist_id для анализа по умолчанию (используется, если в командной строке нет --resist-id / --resist-ids).
# Задайте здесь id и запускайте: python scripts/resist_fact_operations_analytics.py
# При передаче любого из этих аргументов список из CLI полностью подменяет значение ниже.
RESIST_IDS: list[int] = []

EXCLUDED_RESIST_IDS = [
    25, 26, 27, 29, 54, 57, 61, 63, 66, 68, 80, 81, 82, 83, 100, 101, 102, 103,
    104, 105, 106, 109, 112, 113, 115, 116, 119, 120, 121, 122, 123, 125, 126,
    129, 131, 132, 134, 135, 136, 137, 138, 140, 141, 143, 144, 146, 147, 148,
    149, 150, 151, 152, 153, 154, 156, 157, 158, 162, 165, 169, 170, 171, 172,
    173, 174, 175, 176, 177, 178, 179, 181, 196, 139,
]
PREDICT_COMMENT = "first_predict_value_record"


def to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "t", "1"])


def to_bool_value(value):
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return None
    return str(value).strip().lower() in ["true", "t", "1"]


def parse_calculate_param(calc_json: str):
    if pd.isna(calc_json):
        return {}
    try:
        return json.loads(calc_json)
    except Exception:
        return {}


def flatten_calc_to_dict(calc_obj: dict, prefix: str = "calc_") -> dict:
    out = {}
    for k, v in (calc_obj or {}).items():
        col = f"{prefix}{k}"
        if isinstance(v, dict):
            if "value" in v:
                out[col] = v.get("value")
            else:
                out[col] = json.dumps(v, ensure_ascii=False) if v else ""
        else:
            out[col] = v
    return out


def coerce_numeric_series(series: pd.Series) -> pd.Series:
    """pd.to_numeric (to_numeric) + повтор для строк с десятичной запятой (decimal comma), напр. \"8,5\"."""
    out = pd.to_numeric(series, errors="coerce")
    mask = out.isna() & series.notna()
    if mask.any():
        fixed = (
            series[mask]
            .astype(str)
            .str.strip()
            .str.replace(",", ".", regex=False)
        )
        out.loc[mask] = pd.to_numeric(fixed, errors="coerce")
    return out


def load_df_model39_notebook27(raw_files: list[Path]) -> pd.DataFrame:
    """Та же логика, что notebooks/27_comparison_per_series_trimmed_extras.ipynb (до проверки RESIST_IDS)."""
    dfs = []
    for p in raw_files:
        if p.exists():
            dfs.append(pd.read_csv(p, dtype=str))
    if not dfs:
        raise FileNotFoundError(f"Файлы данных не найдены в {raw_files}")

    df_all = pd.concat(dfs, ignore_index=True)
    df_all["period"] = pd.to_datetime(df_all["period"], errors="coerce")
    df_all["resist_id"] = pd.to_numeric(df_all["resist_id"], errors="coerce").astype("Int64")

    bool_cols = ["send", "validate_one", "validate_two", "cancel_approve", "forecast"]
    for col in bool_cols:
        if col in df_all.columns:
            df_all[col] = to_bool(df_all[col])
    df_all["validate_count"] = pd.to_numeric(df_all["validate_count"], errors="coerce").fillna(0).astype(int)
    if "comment" in df_all.columns:
        df_all["comment"] = df_all["comment"].fillna("")
        mask_predict_record = df_all["comment"] == PREDICT_COMMENT
    else:
        mask_predict_record = pd.Series(False, index=df_all.index)

    mask_ok = (
        ~df_all["cancel_approve"]
        & ~mask_predict_record
        & ~df_all["resist_id"].isin(EXCLUDED_RESIST_IDS)
    )
    df_ok = df_all[mask_ok].copy()

    records = []
    for _, row in df_ok.iterrows():
        calc_obj = parse_calculate_param(row.get("calculate_parameter"))
        calc_flat = flatten_calc_to_dict(calc_obj)
        op_raw = row.get("operation_parameter")
        if pd.isna(op_raw):
            continue
        try:
            op_data = json.loads(op_raw)
        except Exception:
            continue
        period = row.get("period")
        if pd.isna(period):
            continue
        for op_id, payload in op_data.items():
            if not isinstance(payload, dict):
                continue
            if to_bool_value(payload.get("operation_active", payload.get("active"))) is False:
                continue
            base_record = {
                "resist_id": row.get("resist_id"),
                "month": int(period.month),
                "year": int(period.year),
                "operation_id": op_id,
                "fact_value": payload.get("fact_value"),
                "fact_predict": payload.get("fact_predict"),
                "workDayMonth_2": calc_flat.get("calc_workDayMonth_2"),
                "calculate_minute": payload.get("calculate_minute"),
            }
            records.append({**base_record, **calc_flat})

    if not records:
        return pd.DataFrame()

    df_model39 = pd.DataFrame(records)
    df_model39["fact_value"] = coerce_numeric_series(df_model39["fact_value"])
    df_model39["fact_predict"] = coerce_numeric_series(df_model39["fact_predict"])
    df_model39["workDayMonth_2"] = coerce_numeric_series(df_model39["workDayMonth_2"])
    df_model39["calculate_minute"] = coerce_numeric_series(df_model39["calculate_minute"])

    calc_cols = [c for c in df_model39.columns if c.startswith("calc_")]
    for col in calc_cols:
        df_model39[col] = coerce_numeric_series(df_model39[col])

    df_model39["date"] = pd.to_datetime(
        dict(year=df_model39["year"], month=df_model39["month"], day=1), errors="coerce"
    ).dt.date
    df_model39 = df_model39.dropna(subset=["fact_value"])
    df_model39 = df_model39.sort_values(["operation_id", "year", "month"]).reset_index(drop=True)
    return df_model39


def train_test_mask(df: pd.DataFrame, test_year: int, test_months: tuple[int, ...]) -> tuple[pd.Series, pd.Series]:
    mask_test = (df["year"] == test_year) & (df["month"].isin(test_months))
    mask_train = ~mask_test
    return mask_train, mask_test


def _months_span_inclusive(d0: date, d1: date) -> int:
    """Число месяцев на сетке month-start от d0 до d1 включительно."""
    if d0 > d1:
        d0, d1 = d1, d0
    return (d1.year - d0.year) * 12 + (d1.month - d0.month) + 1


def _months_between_consecutive(d_prev: date, d_next: date) -> int:
    """Разница в месяцах между соседними датами (первое число месяца)."""
    return (d_next.year - d_prev.year) * 12 + (d_next.month - d_prev.month)


def compute_operation_metrics(
    grp_train: pd.DataFrame,
    grp_test: pd.DataFrame,
) -> dict:
    """Метрики по одной операции: train — регулярность и выбросы (outliers), train/test — длины."""
    n_train = len(grp_train)
    n_test = len(grp_test)

    out: dict = {
        "n_months_train": n_train,
        "n_months_test": n_test,
        "train_date_min": pd.NA,
        "train_date_max": pd.NA,
        "expected_months_in_span": pd.NA,
        "n_unique_train_months": pd.NA,
        "coverage_train": pd.NA,
        "n_duplicate_train_periods": pd.NA,
        "max_gap_months_train": pd.NA,
        "iqr_train": pd.NA,
        "iqr_outlier_count_train": pd.NA,
        "iqr_outlier_pct_train": pd.NA,
        "iqr_is_zero": pd.NA,
    }

    if n_train == 0:
        return out

    t = grp_train.sort_values(["year", "month"])
    dates = pd.to_datetime(dict(year=t["year"], month=t["month"], day=1)).dt.date
    d_min = dates.min()
    d_max = dates.max()
    out["train_date_min"] = str(d_min)
    out["train_date_max"] = str(d_max)

    expected = _months_span_inclusive(d_min, d_max)
    out["expected_months_in_span"] = int(expected)

    uniq = t.drop_duplicates(subset=["year", "month"], keep="first")
    n_u = len(uniq)
    out["n_unique_train_months"] = int(n_u)
    out["n_duplicate_train_periods"] = int(n_train - n_u)
    out["coverage_train"] = round(float(n_u) / float(expected), 6) if expected > 0 else np.nan

    uniq_sorted = uniq.sort_values(["year", "month"])
    u_dates = pd.to_datetime(
        dict(year=uniq_sorted["year"], month=uniq_sorted["month"], day=1)
    ).dt.date.values
    if len(u_dates) <= 1:
        out["max_gap_months_train"] = 0
    else:
        gaps = []
        for i in range(1, len(u_dates)):
            delta = _months_between_consecutive(u_dates[i - 1], u_dates[i])
            gaps.append(max(0, delta - 1))
        out["max_gap_months_train"] = int(max(gaps))

    vals = t["fact_value"].astype(float).values
    q1 = float(np.percentile(vals, 25))
    q3 = float(np.percentile(vals, 75))
    iqr = q3 - q1
    out["iqr_train"] = round(iqr, 8)

    if iqr <= 0:
        out["iqr_is_zero"] = True
        out["iqr_outlier_count_train"] = 0
        out["iqr_outlier_pct_train"] = 0.0
    else:
        out["iqr_is_zero"] = False
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        mask_out = (vals < low) | (vals > high)
        n_out = int(mask_out.sum())
        out["iqr_outlier_count_train"] = n_out
        out["iqr_outlier_pct_train"] = round(100.0 * n_out / len(vals), 4) if len(vals) else 0.0

    return out


def build_metrics_table(
    df: pd.DataFrame,
    resist_id: int,
    test_year: int,
    test_months: tuple[int, ...],
) -> pd.DataFrame:
    sub = df[df["resist_id"] == resist_id].copy()
    if sub.empty:
        return pd.DataFrame()

    mask_train, mask_test = train_test_mask(sub, test_year, test_months)
    rows = []

    for op_id, grp in sub.groupby("operation_id", sort=True):
        tr = grp.loc[mask_train.loc[grp.index]]
        te = grp.loc[mask_test.loc[grp.index]]
        m = compute_operation_metrics(tr, te)
        rows.append(
            {
                "resist_id": resist_id,
                "operation_id": op_id,
                **m,
            }
        )

    return pd.DataFrame(rows)


def safe_sheet_name(rid: int) -> str:
    s = str(rid)
    return s[:31] if len(s) <= 31 else s[:31]


def write_excel(
    out_path: Path,
    resist_ids: list[int],
    df_full: pd.DataFrame,
    test_year: int,
    test_months: tuple[int, ...],
    generated_at: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    wb.remove(wb.active)

    for rid in resist_ids:
        sn = safe_sheet_name(rid)
        ws = wb.create_sheet(title=sn)
        ws.append(["Параметр", "Значение"])
        ws.append(["resist_id", str(rid)])
        ws.append(["test_year", str(test_year)])
        ws.append(["test_months", ",".join(str(m) for m in test_months)])
        ws.append(["generated_at", generated_at])
        ws.append(
            [
                "preprocessing",
                "27_comparison_per_series_trimmed_extras (ячейка загрузки 1–147)",
            ]
        )
        ws.append([])

        tbl = build_metrics_table(df_full, rid, test_year, test_months)
        if tbl.empty:
            ws.append(["message", f"Нет строк df_model39 для resist_id={rid} после фильтрации."])
        else:
            for row in dataframe_to_rows(tbl, index=False, header=True):
                ws.append(row)

    wb.save(out_path)


def parse_resist_ids(s: str) -> list[int]:
    parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
    return [int(p) for p in parts]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Аналитика факта по operation_id для выбранных resist_id (предобработка как в ноутбуке 27)."
    )
    parser.add_argument(
        "--resist-id",
        type=int,
        action="append",
        dest="resist_ids",
        help="resist_id (можно указать несколько раз); если не задано — см. RESIST_IDS в начале скрипта",
    )
    parser.add_argument(
        "--resist-ids",
        type=str,
        default=None,
        dest="resist_ids_csv",
        help="Список resist_id через запятую; если не задано — см. RESIST_IDS в начале скрипта",
    )
    parser.add_argument(
        "--raw",
        type=Path,
        nargs="*",
        default=None,
        help="Пути к CSV (по умолчанию data/raw/data-2022..2025 от корня репозитория)",
    )
    parser.add_argument(
        "--out-xlsx",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Выходной Excel (по умолчанию {_DEFAULT_OUT})",
    )
    parser.add_argument("--test-year", type=int, default=2025)
    parser.add_argument(
        "--test-months",
        type=str,
        default="7,8,9,10,11,12",
        help="Месяцы теста через запятую (по умолчанию 7-12)",
    )
    args = parser.parse_args()

    raw_files = list(args.raw) if args.raw else list(_DEFAULT_RAW_FILES)

    used_cli = False
    ids: list[int] = []
    if args.resist_ids:
        ids.extend(args.resist_ids)
        used_cli = True
    if args.resist_ids_csv is not None:
        used_cli = True
        if str(args.resist_ids_csv).strip():
            ids.extend(parse_resist_ids(args.resist_ids_csv))
    ids = list(dict.fromkeys(ids))
    if not used_cli:
        ids = list(dict.fromkeys(RESIST_IDS))
    if not ids:
        parser.error(
            "Нет resist_id: задайте RESIST_IDS в начале скрипта или передайте --resist-id / --resist-ids …"
        )

    test_months = tuple(parse_resist_ids(args.test_months.replace(" ", "")))

    generated_at = pd.Timestamp.now(tz=None).strftime("%Y-%m-%d %H:%M:%S")

    df_model39 = load_df_model39_notebook27(raw_files)
    if df_model39.empty:
        parser.error("После загрузки CSV нет строк (records пуст). Проверьте сырые файлы и фильтры.")

    avail = set(int(x) for x in df_model39["resist_id"].dropna().unique())
    missing = [r for r in ids if r not in avail]
    if missing:
        sample = sorted(avail)[:15]
        print(
            f"Предупреждение: нет данных для resist_id={missing}. "
            f"Примеры доступных id: {sample}…",
            file=sys.stderr,
        )

    df_f = df_model39[df_model39["resist_id"].isin(ids)].copy()
    write_excel(
        args.out_xlsx,
        ids,
        df_f,
        args.test_year,
        test_months,
        generated_at,
    )
    print(f"Сохранено: {args.out_xlsx.resolve()}")


if __name__ == "__main__":
    main()
