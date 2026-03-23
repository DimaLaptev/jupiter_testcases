"""
Аналитика по resist_id с низким «Качеством» (новый прогноз).

Читает Excel отчёт сравнения моделей (листы «{id} Итог»), отбирает resist_id,
у которых лучшая по метрике «Качество, %» комбинация ниже порога, затем по сырым
CSV строит три таблицы:

1. Средняя длина истории (train) в месяцах по операциям — среднее по resist_id.
2. Доля операций (в %), у которых на тесте хотя бы в одном месяце отсутствует
   факт «год назад» (аналог lag_12 внутри operation_id).
3. «Стабильность» по fact_value на train: (1 - CV) * 100 по месячному ряду факта
   на операцию, затем среднее по операциям внутри resist_id (структурно как stab
   в calc_metrics, но по сырому ряду вместо помесячной точности).

Запуск из корня репозитория:
  python scripts/weak_resist_quality_analytics.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# --- пути по умолчанию (как в notebooks/7_model_comparison_multi_calc_lag12_per_series_only.ipynb)
_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_IN_XLSX = _ROOT / "data" / "processed" / "model_comparison_multi_calc_lag12_per_series_only.xlsx"
_DEFAULT_OUT_XLSX = _ROOT / "data" / "processed" / "weak_resist_id_analytics.xlsx"
_RAW_DIR = _ROOT / "data" / "raw"
_DEFAULT_RAW_FILES = [
    _RAW_DIR / "data-2022.csv",
    _RAW_DIR / "data-2023.csv",
    _RAW_DIR / "data-2024.csv",
    _RAW_DIR / "data-2025.csv",
]

SHEET_SUFFIX = " Итог"
QUALITY_COL = "Качество, %"
QUALITY_THRESHOLD = 80.0

TEST_YEAR = 2025
TEST_MONTHS = (7, 8, 9, 10, 11, 12)

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


def to_bool_value(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return None
    return str(value).strip().lower() in ["true", "t", "1"]


def parse_calculate_param(calc_json: str) -> dict:
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


def load_df_model39(raw_files: list[Path]) -> pd.DataFrame:
    """Тот же пайплайн, что в ноутбуке 7_model_comparison_multi_calc_lag12_per_series_only (ячейка загрузки)."""
    dfs = []
    for p in raw_files:
        if p.exists():
            dfs.append(pd.read_csv(p, dtype=str))
    if not dfs:
        raise FileNotFoundError(f"Файлы данных не найдены: {raw_files}")

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

    df_model39 = pd.DataFrame(records)
    df_model39["fact_value"] = pd.to_numeric(df_model39["fact_value"], errors="coerce")
    df_model39["fact_predict"] = pd.to_numeric(df_model39["fact_predict"], errors="coerce")
    df_model39["workDayMonth_2"] = pd.to_numeric(df_model39["workDayMonth_2"], errors="coerce")
    df_model39["calculate_minute"] = pd.to_numeric(df_model39["calculate_minute"], errors="coerce")

    calc_cols = [c for c in df_model39.columns if c.startswith("calc_")]
    for col in calc_cols:
        df_model39[col] = pd.to_numeric(df_model39[col], errors="coerce")

    df_model39["date"] = pd.to_datetime(
        dict(year=df_model39["year"], month=df_model39["month"], day=1), errors="coerce"
    )
    df_model39 = df_model39.dropna(subset=["fact_value"])
    df_model39 = df_model39.sort_values(["operation_id", "year", "month"]).reset_index(drop=True)
    return df_model39


def parse_weak_resist_ids_from_excel(
    xlsx_path: Path,
    quality_threshold: float = QUALITY_THRESHOLD,
) -> tuple[list[int], pd.DataFrame]:
    """
    Листы «{rid} Итог»: лучшая комбинация — строка с максимальным «Качество, %»
    (сортировка внутри скрипта для устойчивости).
    """
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Файл не найден: {xlsx_path}")

    xl = pd.ExcelFile(xlsx_path, engine="openpyxl")
    itog_names = sorted(n for n in xl.sheet_names if n.endswith(SHEET_SUFFIX))
    if not itog_names:
        raise SystemExit(f"Нет листов с суффиксом «{SHEET_SUFFIX}» в {xlsx_path}")

    rows: list[dict] = []
    weak: list[int] = []

    for name in itog_names:
        rid_str = name[: -len(SHEET_SUFFIX)].strip()
        try:
            rid = int(rid_str)
        except ValueError:
            continue

        df = pd.read_excel(xlsx_path, sheet_name=name, engine="openpyxl")
        if QUALITY_COL not in df.columns:
            raise SystemExit(f"Лист «{name}»: нет колонки «{QUALITY_COL}»")

        df = df.copy()
        df[QUALITY_COL] = pd.to_numeric(df[QUALITY_COL], errors="coerce")
        df = df.sort_values(QUALITY_COL, ascending=False, na_position="last")
        if df.empty:
            rows.append({"resist_id": rid, "sheet": name, QUALITY_COL: np.nan, "weak": False})
            continue

        best_q = float(df.iloc[0][QUALITY_COL])
        is_weak = not np.isnan(best_q) and best_q < quality_threshold
        rows.append({"resist_id": rid, "sheet": name, QUALITY_COL: best_q, "weak": is_weak})
        if is_weak:
            weak.append(rid)

    summary = pd.DataFrame(rows)
    return weak, summary


def _masks(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    mask_test = (df["year"] == TEST_YEAR) & (df["month"].isin(TEST_MONTHS))
    mask_train = ~mask_test
    return mask_train, mask_test


def stability_fact_train(fact: np.ndarray) -> float:
    """(1 - std/mean)*100 по ряду fact_value на train, как в плане."""
    fact = np.asarray(fact, dtype=float)
    if fact.size == 0:
        return 0.0
    mu = float(np.mean(fact))
    if mu <= 0:
        return 0.0
    cv = float(np.std(fact, ddof=0) / mu)
    return round(max(0.0, (1.0 - cv)) * 100.0, 2)


def build_tables_metrics(
    df: pd.DataFrame,
    resist_ids: list[int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Три таблицы только по указанным resist_id."""
    subset = df[df["resist_id"].isin(resist_ids)].copy()
    if subset.empty:
        empty = pd.DataFrame()
        return empty, empty, empty

    mask_train, mask_test = _masks(subset)

    # --- 1) средняя длина истории (train) по операциям, затем среднее по resist_id
    train_part = subset.loc[mask_train]
    hist_len = (
        train_part.groupby(["resist_id", "operation_id"], as_index=False)
        .size()
        .rename(columns={"size": "history_len_months"})
    )
    table1 = (
        hist_len.groupby("resist_id", as_index=False)["history_len_months"]
        .mean()
        .round(4)
        .rename(columns={"history_len_months": "avg_history_len_train_months"})
    )
    n_ops = hist_len.groupby("resist_id")["operation_id"].nunique().rename("n_operations")
    table1 = table1.merge(n_ops.reset_index(), on="resist_id", how="left")

    # lag_12 внутри (resist_id, operation_id)
    subset = subset.sort_values(["resist_id", "operation_id", "year", "month"])
    subset["lag_12"] = subset.groupby(["resist_id", "operation_id"])["fact_value"].shift(12)

    test_part = subset.loc[mask_test].copy()
    # операция «проблемная», если на тесте есть хотя бы один месяц с NaN lag_12
    bad_any = (
        test_part.assign(missing_lag=test_part["lag_12"].isna())
        .groupby(["resist_id", "operation_id"], as_index=False)["missing_lag"]
        .any()
    )
    # только операции с хотя бы одной тестовой строкой
    ops_with_test = test_part.groupby(["resist_id", "operation_id"]).size().reset_index(name="n_test_rows")
    merged = ops_with_test.merge(bad_any, on=["resist_id", "operation_id"], how="left")
    merged["missing_lag"] = merged["missing_lag"].fillna(False)

    table2 = (
        merged.groupby("resist_id", as_index=False)
        .agg(
            n_operations_with_test=("operation_id", "count"),
            n_ops_missing_lag12=("missing_lag", lambda s: int(s.sum())),
        )
    )
    table2["pct_operations_missing_lag12"] = (
        100.0 * table2["n_ops_missing_lag12"] / table2["n_operations_with_test"].replace(0, np.nan)
    ).round(4)

    # --- 3) стабильность по fact на train
    stab_rows: list[dict] = []
    for (rid, op_id), grp in train_part.groupby(["resist_id", "operation_id"]):
        vals = grp["fact_value"].values.astype(float)
        stab_rows.append(
            {"resist_id": rid, "operation_id": op_id, "stability_fact_train": stability_fact_train(vals)}
        )
    stab_df = pd.DataFrame(stab_rows)
    table3 = (
        stab_df.groupby("resist_id", as_index=False)
        .agg(
            mean_stability_fact_train=("stability_fact_train", "mean"),
            n_operations=("operation_id", "count"),
        )
    )
    table3["mean_stability_fact_train"] = table3["mean_stability_fact_train"].round(4)

    return table1, table2, table3


def main() -> None:
    parser = argparse.ArgumentParser(description="Аналитика resist_id с низким качеством нового прогноза.")
    parser.add_argument(
        "--in-xlsx",
        type=Path,
        default=_DEFAULT_IN_XLSX,
        help="Входной Excel отчёта сравнения моделей",
    )
    parser.add_argument(
        "--out-xlsx",
        type=Path,
        default=_DEFAULT_OUT_XLSX,
        help="Выходной Excel с таблицами аналитики",
    )
    parser.add_argument(
        "--quality-threshold",
        type=float,
        default=QUALITY_THRESHOLD,
        help="Порог «Качество, %%» лучшей комбинации (строго ниже — в выборку)",
    )
    parser.add_argument(
        "--raw",
        type=Path,
        nargs="*",
        default=None,
        help="Список CSV (по умолчанию data-2022..2025 в data/raw)",
    )
    args = parser.parse_args()

    in_xlsx: Path = args.in_xlsx
    out_xlsx: Path = args.out_xlsx
    raw_files = list(args.raw) if args.raw else _DEFAULT_RAW_FILES

    weak_ids, summary = parse_weak_resist_ids_from_excel(in_xlsx, quality_threshold=args.quality_threshold)

    print(f"Входной отчёт: {in_xlsx.resolve()}")
    print(f"Порог «{QUALITY_COL}» < {args.quality_threshold}%: найдено resist_id: {len(weak_ids)} — {weak_ids}")

    df_model39 = load_df_model39(raw_files)
    t1, t2, t3 = build_tables_metrics(df_model39, weak_ids)

    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_xlsx, engine="openpyxl", mode="w") as w:
        summary.to_excel(w, sheet_name="Отбор по Excel", index=False)
        if not weak_ids:
            pd.DataFrame(
                {"message": [f"Нет resist_id с «{QUALITY_COL}» < {args.quality_threshold}%"]}
            ).to_excel(w, sheet_name="Нет данных", index=False)
        elif t1.empty:
            pd.DataFrame(
                {"message": ["Нет строк в df_model39 для выбранных resist_id (проверьте сырые CSV)"]}
            ).to_excel(w, sheet_name="Нет данных", index=False)
        else:
            t1.to_excel(w, sheet_name="Средняя длина истории", index=False)
            t2.to_excel(w, sheet_name="Доля без lag_12", index=False)
            t3.to_excel(w, sheet_name="Стабильность факта train", index=False)

    print(f"Сохранено: {out_xlsx.resolve()}")


if __name__ == "__main__":
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    main()
