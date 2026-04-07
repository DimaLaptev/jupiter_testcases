"""
Чтение листа «Данные» из выходных *dashboard*.xlsx и метрики Точность / Стабильность / Качество.
Без Streamlit — для import (import) из тестов и streamlit_app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build_metrics_dashboard_simple import (  # noqa: E402
    calc_mean_accuracy,
    calc_stability,
    calc_quality_index,
)

# Синхронизировать с DATA_HEADERS_RU в scripts/build_model_comparison_dashboard.py
DATA_HEADERS_RU = {
    "resist_id": "Модель (resist_id)",
    "operation_id": "ID операции",
    "year": "Год",
    "month": "Месяц",
    "fact_value": "Факт, шт.",
    "fact_predict": "Прогноз fact_predict, шт.",
    "abs_error": "Ошибка (fact_predict)",
    "accuracy_pct": "Точность прогноза, % (fact_predict)",
    "predict_new": "Прогноз (новый), шт.",
    "abs_error_new": "Ошибка (новый)",
    "accuracy_pct_new": "Точность прогноза, % (новый)",
    "predict_chosen": "Прогноз (выбранный лучший), шт.",
    "abs_error_chosen": "Ошибка (выбранный)",
    "accuracy_pct_chosen": "Точность прогноза, % (выбранный лучший)",
    "best_model_name": "Название модели прогноза",
}

RU_TO_EN: dict[str, str] = {ru: en for en, ru in DATA_HEADERS_RU.items()}

SHEET_DANNye = "Данные"


def discover_dashboard_files(processed_dir: Path) -> list[Path]:
    if not processed_dir.is_dir():
        return []
    out: list[Path] = []
    for p in processed_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() != ".xlsx":
            continue
        if "dashboard" not in p.name.lower():
            continue
        out.append(p)
    return sorted(out, key=lambda x: x.name.lower())


def rename_dannye_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [RU_TO_EN.get(str(c).strip(), str(c).strip()) for c in df.columns]
    return df


def filter_footer_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Убрать строки «Итого:» и KPI под таблицей на листе «Данные»."""
    if df.empty or "resist_id" not in df.columns or "month" not in df.columns:
        return df.iloc[0:0].copy()
    rid = pd.to_numeric(df["resist_id"], errors="coerce")
    mo = pd.to_numeric(df["month"], errors="coerce")
    mask = rid.notna() & mo.notna() & mo.between(1, 12)
    return df.loc[mask].copy()


def load_dannye_from_file(path: Path, dashboard_file: str) -> pd.DataFrame:
    xl = pd.ExcelFile(path, engine="openpyxl")
    if SHEET_DANNye not in xl.sheet_names:
        raise ValueError(f"Нет листа «{SHEET_DANNye}»: {path.name}")
    df = pd.read_excel(path, sheet_name=SHEET_DANNye, engine="openpyxl")
    df = rename_dannye_columns(df)
    df = filter_footer_rows(df)
    df["dashboard_file"] = dashboard_file
    for col in (
        "resist_id",
        "operation_id",
        "year",
        "month",
        "fact_value",
        "fact_predict",
        "abs_error",
        "accuracy_pct",
        "predict_new",
        "abs_error_new",
        "accuracy_pct_new",
        "predict_chosen",
        "abs_error_chosen",
        "accuracy_pct_chosen",
    ):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "best_model_name" in df.columns:
        df["best_model_name"] = df["best_model_name"].astype(str).replace("nan", "")
    return df


def global_metrics_from_acc(df: pd.DataFrame, acc_col: str) -> tuple[float, float, float]:
    t = df.copy()
    t["accuracy_pct"] = pd.to_numeric(t[acc_col], errors="coerce").fillna(0)
    ma = calc_mean_accuracy(t)
    st_ = calc_stability(t)
    qi = calc_quality_index(ma, st_)
    return ma, st_, qi


def division_stats_dual(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    gkeys: list[str] = (
        ["dashboard_file", "resist_id"] if "dashboard_file" in df.columns else ["resist_id"]
    )
    rows: list[dict] = []
    for key, grp in df.groupby(gkeys, dropna=True):
        if isinstance(key, tuple):
            dfile, rid = key[0], key[1]
        else:
            dfile, rid = "", key

        m_acc = calc_mean_accuracy(grp)
        stab = calc_stability(grp)
        qi = calc_quality_index(m_acc, stab)

        grp_new = grp.copy()
        grp_new["accuracy_pct"] = pd.to_numeric(
            grp_new["accuracy_pct_chosen"], errors="coerce"
        ).fillna(0)
        m_acc_new = calc_mean_accuracy(grp_new)
        stab_new = calc_stability(grp_new)
        qi_new = calc_quality_index(m_acc_new, stab_new)

        if "division_title" in grp.columns:
            div_titles = grp["division_title"].dropna()
            div_title = div_titles.iloc[0] if len(div_titles) > 0 else ""
        else:
            div_title = ""
        div_title = div_title if pd.notna(div_title) and str(div_title).strip() else "(не указано)"

        model_name = (
            grp["best_model_name"].dropna()
            if "best_model_name" in grp.columns
            else pd.Series(dtype=object)
        )
        model_name = str(model_name.iloc[0]) if len(model_name) > 0 else ""

        row = {
            "resist_id": rid,
            "division_title": div_title,
            "fact_sum": grp["fact_value"].sum(),
            "pred_sum": grp["fact_predict"].sum(),
            "error_sum": grp["abs_error"].sum(),
            "mean_accuracy": m_acc,
            "stability": stab,
            "quality_index": qi,
            "mean_accuracy_new": m_acc_new,
            "stability_new": stab_new,
            "quality_index_new": qi_new,
            "best_model_name": model_name,
        }
        if "dashboard_file" in df.columns:
            row["dashboard_file"] = dfile
        rows.append(row)
    return pd.DataFrame(rows)


def heatmap_quality_matrix(
    df: pd.DataFrame,
    acc_col: str,
    row_label_col: str,
) -> pd.DataFrame:
    if df.empty or "month" not in df.columns:
        return pd.DataFrame()
    months = sorted(df["month"].dropna().unique())
    rows_idx = sorted(df[row_label_col].unique(), key=lambda x: (str(type(x)), str(x)))
    mat = []
    for r in rows_idx:
        row_vals = []
        sl_r = df[df[row_label_col] == r]
        for m in months:
            sl = sl_r[sl_r["month"] == m].copy()
            if sl.empty or sl["fact_value"].sum() == 0:
                row_vals.append(np.nan)
            else:
                sl = sl.copy()
                sl["accuracy_pct"] = pd.to_numeric(sl[acc_col], errors="coerce").fillna(0)
                m_a = calc_mean_accuracy(sl)
                s = calc_stability(sl)
                q = calc_quality_index(m_a, s)
                row_vals.append(q)
        mat.append(row_vals)
    out = pd.DataFrame(mat, index=rows_idx, columns=[int(m) for m in months])
    out.index.name = row_label_col
    return out
