# -*- coding: utf-8 -*-
"""Бэктест (backtest) production-пайплайна ``optim_2_predict_operation_count_v2`` в формате Excel как ``37_forecast_test_fix.py``.

История (history) для обучения/турнира обрезается строго до первого месяца теста
(``--test-year`` / ``--test-months``): в репозиторий (repository) попадают только строки
с ``date < первый тестовый месяц``. Затем вызывается ``PredictOparationCountV2.predict``;
прогнозные месяцы — как в production: ``FORECAST_HORIZON`` (= 4) вперёд от последней даты
истории. Строки теста за пределами этих 4 месяцев получают ``predict_new = NaN``.

Выход: листы «{{rid}} Итог», «{{id}} Данные теста», «{{rid}} По операциям» — совместимы с
``build_model_comparison_dashboard.py`` (фаза 1).
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

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
    EXCLUDED_RESIST_IDS,
    describe_missing_raw_paths,
    load_df_model39_from_nb37_raw_files,
)
from scripts.optim_2_predict_operation_count_v2 import (  # noqa: E402
    DATE_FMT,
    HISTORY_START_DATE,
    MODEL_KEY,
    PredictOparationCountV2,
)


def _operation_key_for_param(operation_id: Any) -> str:
    """Согласование с ``format_data`` / ключами ``operation_parameter`` (как в CsvHistoryRepository)."""
    if pd.isna(operation_id):
        return str(operation_id)
    try:
        x = float(operation_id)
        if x == int(x):
            return str(int(x))
    except (TypeError, ValueError):
        pass
    return str(operation_id)

RAW_DIR = _ROOT / "data" / "raw"
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]

OUT_XLSX_DEFAULT = _ROOT / "data" / "processed" / "37_optim_2_test.xlsx"
DEDUPE_POLICY = "last"

# Подпись «модели» в листах (как ``Комбайн 37`` в nb37); колонка ``… (новый)`` для дашборда.
OPTIM2_COMBINE_NAME = "Optim2 production"

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

RECORD_MODEL_WARNINGS = False


def calc_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    """Метрики как в ``37_forecast_test_fix.py`` / дашборде (построчная accuracy_pct)."""
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
    df = df.apply(np.nan_to_num, nan=0.0, posinf=0.0, neginf=0.0)

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


def normalize_month_period(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    if t.tzinfo is not None:
        t = t.tz_localize(None)
    return pd.Timestamp(t.to_period("M").to_timestamp())


def prepare_resist_frame(df: pd.DataFrame, resist_id: int) -> pd.DataFrame:
    sub = df[df["resist_id"] == resist_id].copy()
    if sub.empty:
        return sub
    sub["date"] = sub["date"].map(normalize_month_period)
    sub = sub.sort_values(["operation_id", "date"])
    if DEDUPE_POLICY == "last":
        sub = sub.drop_duplicates(["operation_id", "date"], keep="last")
    sub["year"] = sub["date"].dt.year
    sub["month"] = sub["date"].dt.month
    if "fact_predict" not in sub.columns:
        sub["fact_predict"] = np.nan
    sub["fact_value"] = pd.to_numeric(sub["fact_value"], errors="coerce")
    return sub.reset_index(drop=True)


def build_optim2_excel_payload(
    *,
    resist_id: int,
    df_test_view: pd.DataFrame,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_baseline: Optional[np.ndarray],
    winner_by_operation: Dict[Any, str],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Те же таблицы, что ``build_nb37_excel_payload`` в ``37_forecast_test_fix.py``."""
    t_m, s_m, q_m = calc_metrics(y_true, y_pred)
    t_fp = s_fp = q_fp = float("nan")
    if y_baseline is not None and np.any(np.isfinite(y_baseline)):
        t_fp, s_fp, q_fp = calc_metrics(y_true, y_baseline)

    combine_rows = [
        {
            "resist_id": resist_id,
            "Конфигурация": OPTIM2_COMBINE_NAME,
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
            "predict_new": f"{OPTIM2_COMBINE_NAME} (новый)",
        }
    )

    rows_op = []
    for (_, op_id), grp in df_test_view.groupby(["resist_id", "operation_id"], sort=False):
        win_label = winner_by_operation.get(op_id, "—")
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
                f"Точность ({OPTIM2_COMBINE_NAME})": t2,
                f"Стабильность ({OPTIM2_COMBINE_NAME})": s2,
                f"Качество ({OPTIM2_COMBINE_NAME})": q2,
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


class BacktestCsvHistoryRepository:
    """Как ``CsvHistoryRepository``, но верхняя граница истории — ``end_exclusive`` (начало теста)."""

    def __init__(self, df_model39: pd.DataFrame, *, end_exclusive: pd.Timestamp) -> None:
        self._df = df_model39
        self._end_exclusive = pd.Timestamp(end_exclusive)

    def fetch(self, resist: str) -> Iterable[Mapping[str, Any]]:
        rid = int(resist)
        need = {"resist_id", "date", "fact_value"}
        miss = need - set(self._df.columns)
        if miss:
            raise ValueError(f"df_model39 не хватает колонок: {sorted(miss)}")
        sub = self._df.loc[self._df["resist_id"] == rid].copy()
        if sub.empty:
            return []
        sub["_ts"] = pd.to_datetime(sub["date"], errors="coerce")
        sub = sub.dropna(subset=["_ts"])
        start_bound = pd.Timestamp(HISTORY_START_DATE)
        end_bound = self._end_exclusive
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


def _coerce_operation_id(value: object) -> object:
    try:
        x = float(value)
        return int(x) if x == int(x) else x
    except (TypeError, ValueError):
        return value


def operations_for_resist(df: pd.DataFrame, resist_id: int) -> list:
    """Все ``operation_id`` по ``resist_id`` (как список для ``predict``)."""
    sub = df.loc[df["resist_id"] == resist_id, "operation_id"].dropna()
    out = sorted({_coerce_operation_id(x) for x in sub.unique()}, key=lambda z: (str(type(z)), str(z)))
    return list(out)


def run_optim2_backtest_for_resist(
    df: pd.DataFrame,
    resist_id: int,
    *,
    test_year: int,
    test_months: List[int],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    months_sorted = sorted(test_months)
    first_test = pd.Timestamp(test_year, months_sorted[0], 1)

    operations = operations_for_resist(df, resist_id)
    if not operations:
        raise ValueError(f"нет operation_id для resist_id={resist_id}")

    sub_full = prepare_resist_frame(df, resist_id)
    mask_test = (sub_full["year"] == test_year) & (sub_full["month"].isin(months_sorted))
    df_test = sub_full.loc[mask_test].copy()
    if df_test.empty:
        raise ValueError(f"нет строк теста: year={test_year}, months={months_sorted}, rid={resist_id}")

    repo = BacktestCsvHistoryRepository(df, end_exclusive=first_test)
    predictor = PredictOparationCountV2(repository=repo)
    raw = predictor.predict(operations, str(resist_id))

    def _raw_block(op_val: Any):
        if op_val in raw:
            return raw[op_val]
        try:
            if pd.notna(op_val) and float(op_val) == int(float(op_val)):
                k = int(float(op_val))
                if k in raw:
                    return raw[k]
        except (TypeError, ValueError):
            pass
        return {}

    preds: List[float] = []
    for _, row in df_test.iterrows():
        op = row["operation_id"]
        block = _raw_block(op)
        dk = normalize_month_period(row["date"]).strftime(DATE_FMT)
        v = block.get(dk) if isinstance(block, dict) else None
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            preds.append(float("nan"))
        else:
            preds.append(float(v))

    df_test = df_test.copy()
    df_test["predict_new"] = preds

    winner_by_operation: Dict[Any, str] = {}
    for op in df_test["operation_id"].unique():
        ob = _raw_block(op)
        if isinstance(ob, dict) and MODEL_KEY in ob:
            winner_by_operation[op] = str(ob[MODEL_KEY])

    y_true = df_test["fact_value"].astype(float).values
    y_pred = df_test["predict_new"].astype(float).values
    y_base = df_test["fact_predict"].astype(float).values if "fact_predict" in df_test.columns else None

    return build_optim2_excel_payload(
        resist_id=resist_id,
        df_test_view=df_test,
        y_true=y_true,
        y_pred=y_pred,
        y_baseline=y_base,
        winner_by_operation=winner_by_operation,
    )


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Бэктест optim_2 production + Excel как 37_forecast_test_fix (дашборд phase1).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Прогноз на тесте — один production-рефит от истории до начала теста; длина горизонта "
            "задаётся FORECAST_HORIZON в optim_2 (сейчас 4 месяца). Лишние тестовые месяцы без "
            "точки в прогнозе получат NaN в столбце «новый»."
        ),
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="CSV (date, fact_value, operation_id, resist_id [, fact_predict]). Иначе — RAW_FILES.",
    )
    rid_grp = parser.add_mutually_exclusive_group()
    rid_grp.add_argument("--resist-id", type=int, default=None, metavar="N")
    rid_grp.add_argument(
        "--resist-ids",
        type=str,
        default=None,
        metavar="LIST",
        help="Несколько resist_id через запятую, напр. 124,125,130",
    )
    parser.add_argument("--test-year", type=int, default=2025)
    parser.add_argument(
        "--test-months",
        type=str,
        default="7,8,9,10,11,12",
        help="Месяцы теста через запятую (по умолчанию июль–декабрь).",
    )
    parser.add_argument("--out-xlsx", type=Path, default=OUT_XLSX_DEFAULT)
    parser.add_argument("--no-excel", action="store_true")
    args = parser.parse_args(argv)

    months = [int(x.strip()) for x in args.test_months.split(",") if x.strip()]

    if args.csv is not None:
        df = pd.read_csv(args.csv, dtype=str, low_memory=False)
    else:
        missing_paths = describe_missing_raw_paths(RAW_FILES)
        if missing_paths:
            print(
                "Предупреждение: отсутствуют raw-файлы:",
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

    avail = set(int(x) for x in df["resist_id"].dropna().unique().tolist())
    if args.resist_ids is not None:
        rid_list = [int(x.strip()) for x in args.resist_ids.split(",") if x.strip()]
        miss = [r for r in rid_list if r not in avail]
        if miss:
            parser.error(f"--resist-ids: нет resist_id={miss}; в данных: {sorted(avail)!r}")
    elif args.resist_id is not None:
        if args.resist_id not in avail:
            parser.error(f"--resist-id отсутствует; доступно: {sorted(avail)!r}")
        rid_list = [args.resist_id]
    else:
        rid_list = sorted(avail)

    per_rid_best: Dict[int, Dict[str, Any]] = {}
    warn_all: List[dict] = []

    n_rid = len(rid_list)
    for i, rid in enumerate(rid_list, start=1):
        if rid in EXCLUDED_RESIST_IDS:
            print(f"Предупреждение: resist_id={rid} в EXCLUDED_RESIST_IDS loader.", flush=True)
        try:
            df_res_full, df_detail, df_metrics_op = run_optim2_backtest_for_resist(
                df,
                int(rid),
                test_year=args.test_year,
                test_months=months,
            )
        except Exception as exc:
            print(f"[{i}/{n_rid}] resist_id={rid} ОШИБКА: {exc}", flush=True)
            continue

        _q = df_res_full.iloc[0]["Качество, %"] if len(df_res_full) else float("nan")
        _q_show = "nan" if pd.isna(_q) else f"{float(_q):.2f}"
        print(f"[{i}/{n_rid}] resist_id={rid} → Качество, % = {_q_show}", flush=True)

        combine_frames.append(df_res_full)
        per_rid_best[int(rid)] = {
            "best_combo": OPTIM2_COMBINE_NAME,
            "df_metrics_op": df_metrics_op,
            "df_detail": df_detail,
        }

    df_results_full = pd.concat(combine_frames, ignore_index=True) if combine_frames else pd.DataFrame()

    if not args.no_excel and combine_frames:
        write_nb37_style_excel(
            out_path=args.out_xlsx,
            resist_ids=[int(r) for r in rid_list if int(r) in per_rid_best],
            df_results_full=df_results_full,
            per_rid_best=per_rid_best,
            warning_rows=warn_all,
            record_warnings=RECORD_MODEL_WARNINGS,
        )
    elif not combine_frames:
        print("Нет успешных resist: Excel не записан.", flush=True)


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    main()
