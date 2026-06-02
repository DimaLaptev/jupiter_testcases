"""
Дашборд по Excel сравнения моделей с фильтрацией по сырому массиву nb37.

Копия ``build_model_comparison_dashboard.py`` с дополнительной сверкой каждой строки
дашборда с raw CSV (``37_forecast_test_fix.RAW_FILES`` через ``nb37_raw_model39_load``):

1. Исключаются ``EXCLUDED_RESIST_IDS`` из nb37.
2. Исключаются операции с ``active=False`` / ``operation_active=False`` (уже в loader).
3. Отрезаются ведущие месяцы, где ``fact_predict`` не > 0 (на raw-ключах и на строках дашборда).

Метрики и листы строятся только по очищенному массиву.

Использование:
    python scripts/build_model_comparison_dashboard_raw_filter.py -i path/to/file.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal, Sequence

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
#  Импорт вычислительных / стилевых хелперов из build_metrics_dashboard_simple
# ---------------------------------------------------------------------------

_project_root = Path(__file__).resolve().parent.parent
_scripts_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_scripts_dir))

from build_metrics_dashboard_simple import (  # noqa: E402
    GOOD_FILL,
    BAD_FILL,
    NEUTRAL_FILL,
    HEADER_FILL,
    HEADER_FONT,
    KPI_FONT,
    KPI_LABEL_FONT,
    THIN_BORDER,
    calc_mean_accuracy,
    calc_stability,
    calc_quality_index,
    style_header_row,
    auto_column_width,
    write_kpi_card,
)

from nb37_raw_model39_load import (  # noqa: E402
    EXCLUDED_RESIST_IDS,
    describe_missing_raw_paths,
    load_df_model39_from_nb37_raw_files,
)

# ---------------------------------------------------------------------------
#  Константы
# ---------------------------------------------------------------------------

ITOG_SUFFIX = " Итог"
DATA_SUFFIX = " Данные теста"
PHASE2_COMMITTED_SHEET = "Фаза2_committed"

RAW_DIR = _project_root / "data" / "raw"
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]

_MERGE_KEYS = ("resist_id", "operation_id", "year", "month")

DataSource = Literal["phase1", "phase2"]

MONTH_NAMES = [
    "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
]


def _default_input() -> Path:
    return _project_root / "data" / "processed" / "model_comparison_multi.xlsx"


def drop_leading_zero_fact_predict(df: pd.DataFrame) -> pd.DataFrame:
    """Убирает ведущие строки per (resist_id, operation_id), где fact_predict не > 0."""
    if df.empty or "fact_predict" not in df.columns:
        return df
    for col in _MERGE_KEYS:
        if col not in df.columns:
            return df

    kept: list[pd.DataFrame] = []
    for _, grp in df.groupby(["resist_id", "operation_id"], sort=False):
        sorted_grp = grp.sort_values(["year", "month"], kind="stable")
        i_valid: int | None = None
        for i, value in enumerate(sorted_grp["fact_predict"].tolist()):
            try:
                if value is not None and float(value) > 0:
                    i_valid = i
                    break
            except (TypeError, ValueError):
                continue
        if i_valid is not None:
            kept.append(sorted_grp.iloc[i_valid:])
    if not kept:
        return df.iloc[0:0].copy()
    return pd.concat(kept, ignore_index=True)


def _normalize_key_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "resist_id" in out.columns:
        out["resist_id"] = pd.to_numeric(out["resist_id"], errors="coerce")
        out["resist_id"] = out["resist_id"].apply(
            lambda x: int(x) if pd.notna(x) and float(x) == int(x) else x
        )
    if "operation_id" in out.columns:
        out["operation_id"] = pd.to_numeric(out["operation_id"], errors="coerce")
        out["operation_id"] = out["operation_id"].apply(
            lambda x: int(x) if pd.notna(x) and float(x) == int(x) else x
        )
    if "month" in out.columns:
        out["month"] = pd.to_numeric(out["month"], errors="coerce").fillna(0).astype(int)
    if "year" in out.columns:
        out["year"] = pd.to_numeric(out["year"], errors="coerce").fillna(0).astype(int)
    return out


def build_raw_allowed_keys(raw_files: Sequence[Path]) -> pd.DataFrame:
    """Ключи строк raw после EXCLUDED_RESIST_IDS, active=False и drop leading fact_predict.

    ``load_df_model39_from_nb37_raw_files`` уже исключает resist из ``EXCLUDED_RESIST_IDS``
    и операции с ``active=False`` / ``operation_active=False``.
    """
    missing = describe_missing_raw_paths(raw_files)
    if missing:
        print(
            "Предупреждение: отсутствуют raw CSV: "
            + ", ".join(str(p) for p in missing),
            file=sys.stderr,
        )
    raw = load_df_model39_from_nb37_raw_files(raw_files)
    if raw.empty:
        raise SystemExit(
            "Сырой массив nb37 пуст после загрузки — проверьте RAW_FILES / data/raw/*.csv."
        )
    raw = _normalize_key_cols(raw)
    raw["fact_predict"] = pd.to_numeric(raw["fact_predict"], errors="coerce").fillna(0.0)
    raw = drop_leading_zero_fact_predict(raw)
    return raw[list(_MERGE_KEYS)].drop_duplicates()


def filter_dashboard_by_raw_reference(
    df: pd.DataFrame,
    allowed_keys: pd.DataFrame,
    *,
    label: str = "",
) -> pd.DataFrame:
    """Сверка строк дашборда с raw: resist exclude, inner join, drop leading fact_predict."""
    n0 = len(df)
    out = _normalize_key_cols(df)
    out = out[~out["resist_id"].isin(EXCLUDED_RESIST_IDS)]
    n1 = len(out)
    out = out.merge(allowed_keys, on=list(_MERGE_KEYS), how="inner")
    n2 = len(out)
    out = drop_leading_zero_fact_predict(out)
    n3 = len(out)
    tag = f" ({label})" if label else ""
    if n0 != n3:
        print(
            f"filter_dashboard_by_raw_reference{tag}: {n0} → {n1} (exclude resist) → "
            f"{n2} (raw join) → {n3} (drop leading fact_predict)",
            file=sys.stderr,
        )
    return out


def _accuracy_col(fact: pd.Series, pred: pd.Series) -> pd.Series:
    acc = np.where(
        fact == 0,
        np.where(pred == 0, 100.0, 0.0),
        np.clip(100.0 - (fact - pred).abs() / fact * 100.0, 0, 100),
    )
    return np.round(acc, 2)


def _compute_metric_columns(
    df: pd.DataFrame,
    *,
    use_fp_map: dict[int | str, bool] | None = None,
) -> pd.DataFrame:
    out = df.copy()
    out["abs_error"] = (out["fact_value"] - out["fact_predict"]).abs()
    out["accuracy_pct"] = _accuracy_col(out["fact_value"], out["fact_predict"])
    out["abs_error_new"] = (out["fact_value"] - out["predict_new"]).abs()
    out["accuracy_pct_new"] = _accuracy_col(out["fact_value"], out["predict_new"])
    if use_fp_map is not None:
        out["predict_chosen"] = np.where(
            out["resist_id"].map(use_fp_map).fillna(False),
            out["fact_predict"],
            out["predict_new"],
        )
    elif "predict_chosen" not in out.columns:
        out["predict_chosen"] = out["predict_new"]
    out["abs_error_chosen"] = (out["fact_value"] - out["predict_chosen"]).abs()
    out["accuracy_pct_chosen"] = _accuracy_col(out["fact_value"], out["predict_chosen"])
    return out


# ---------------------------------------------------------------------------
#  Чтение исходного Excel
# ---------------------------------------------------------------------------


def _find_new_col(columns: list[str]) -> str | None:
    for c in columns:
        if c.endswith(" (новый)"):
            return c
    return None


def _pick_best_from_itog(df_it: pd.DataFrame) -> tuple[str, bool]:
    """
    Сравнивает «Качество, %» лучшей строки (после сортировки) с «Кач. fact_predict, %».
    Если у fact_predict (baseline) качество выше — выбираем текущий прогноз.

    Возвращает (название для колонки «Название модели прогноза», use_fact_predict).
    """
    if df_it.empty or "Комбинация" not in df_it.columns:
        return "", False

    d = df_it.copy()
    if "Качество, %" in d.columns:
        d["Качество, %"] = pd.to_numeric(d["Качество, %"], errors="coerce")
        d = d.sort_values("Качество, %", ascending=False, na_position="last").reset_index(drop=True)

    row0 = d.iloc[0]
    q_new = pd.to_numeric(row0.get("Качество, %"), errors="coerce")
    q_fp = pd.to_numeric(row0.get("Кач. fact_predict, %"), errors="coerce")

    if pd.notna(q_fp) and pd.notna(q_new) and float(q_fp) > float(q_new):
        return "Текущий", True
    return str(row0["Комбинация"]), False


def load_source_phase1(
    xlsx_path: Path,
    *,
    raw_files: Sequence[Path] = RAW_FILES,
) -> tuple[pd.DataFrame, dict[int | str, str]]:
    """
    Фаза 1: листы «… Итог» + «… Данные теста».

    Возвращает:
      df        — объединённый DataFrame (fact_value, fact_predict, predict_new,
                  predict_chosen, accuracy_pct_chosen, …)
      best_map  — {resist_id: название выбранного прогноза («Текущий» или Комбинация)}
    """
    xl = pd.ExcelFile(xlsx_path, engine="openpyxl")
    itog_sheets = sorted(n for n in xl.sheet_names if n.endswith(ITOG_SUFFIX))
    data_sheets = sorted(n for n in xl.sheet_names if n.endswith(DATA_SUFFIX))

    if not itog_sheets or not data_sheets:
        all_names = ", ".join(repr(n) for n in xl.sheet_names)
        raise SystemExit(
            f"Не найдены листы «… Итог» / «… Данные теста» в {xlsx_path}\n"
            f"Листы: [{all_names}]"
        )

    best_map: dict[int | str, str] = {}
    use_fp_map: dict[int | str, bool] = {}
    for name in itog_sheets:
        df_it = pd.read_excel(xlsx_path, sheet_name=name, engine="openpyxl")
        rid_raw = name.removesuffix(ITOG_SUFFIX).strip()
        try:
            rid = int(rid_raw)
        except ValueError:
            rid = rid_raw
        name_best, use_fp = _pick_best_from_itog(df_it)
        if name_best:
            best_map[rid] = name_best
        use_fp_map[rid] = use_fp

    frames: list[pd.DataFrame] = []
    for name in data_sheets:
        df_d = pd.read_excel(xlsx_path, sheet_name=name, engine="openpyxl")
        new_col = _find_new_col(list(df_d.columns))

        rename = {}
        for c in df_d.columns:
            if c == "fact_value (факт)":
                rename[c] = "fact_value"
            elif c == "fact_predict (текущий)":
                rename[c] = "fact_predict"
        if new_col:
            rename[new_col] = "predict_new"

        df_d = df_d.rename(columns=rename)

        for col in ("fact_value", "fact_predict"):
            if col in df_d.columns:
                df_d[col] = pd.to_numeric(df_d[col], errors="coerce").fillna(0)
        if "predict_new" in df_d.columns:
            df_d["predict_new"] = pd.to_numeric(df_d["predict_new"], errors="coerce").fillna(0)
        else:
            df_d["predict_new"] = 0.0

        frames.append(df_d)

    df = pd.concat(frames, ignore_index=True)

    allowed_keys = build_raw_allowed_keys(raw_files)
    df = filter_dashboard_by_raw_reference(df, allowed_keys, label="phase1")
    df = _compute_metric_columns(df, use_fp_map=use_fp_map)

    df["best_model_name"] = df["resist_id"].map(best_map).fillna("")

    if "division_title" not in df.columns:
        df["division_title"] = ""

    return df, best_map


def _read_baseline_from_data_sheets(xlsx_path: Path) -> pd.DataFrame:
    """Только fact_predict из листов «{rid} Данные теста» для merge с фазой 2."""
    xl = pd.ExcelFile(xlsx_path, engine="openpyxl")
    data_sheets = sorted(n for n in xl.sheet_names if n.endswith(DATA_SUFFIX))
    frames: list[pd.DataFrame] = []
    for name in data_sheets:
        df_d = pd.read_excel(xlsx_path, sheet_name=name, engine="openpyxl")
        rename: dict[str, str] = {}
        if "fact_value (факт)" in df_d.columns:
            rename["fact_value (факт)"] = "fact_value"
        if "fact_predict (текущий)" in df_d.columns:
            rename["fact_predict (текущий)"] = "fact_predict"
        df_d = df_d.rename(columns=rename)
        need = ["resist_id", "operation_id", "year", "month", "fact_predict"]
        if not all(c in df_d.columns for c in need):
            continue
        frames.append(df_d[need].copy())
    if not frames:
        return pd.DataFrame(columns=["resist_id", "operation_id", "year", "month", "fact_predict"])
    out = pd.concat(frames, ignore_index=True)
    out["fact_predict"] = pd.to_numeric(out["fact_predict"], errors="coerce").fillna(0.0)
    out["resist_id"] = pd.to_numeric(out["resist_id"], errors="coerce")
    out["year"] = pd.to_numeric(out["year"], errors="coerce").fillna(0).astype(int)
    out["month"] = pd.to_numeric(out["month"], errors="coerce").fillna(0).astype(int)
    out = out.drop_duplicates(subset=["resist_id", "operation_id", "year", "month"], keep="first")
    return out


def load_source_phase2(
    xlsx_path: Path,
    phase2_sheet: str,
    *,
    raw_files: Sequence[Path] = RAW_FILES,
) -> tuple[pd.DataFrame, dict[int | str, str]]:
    """
    Фаза 2: лист с committed-прогнозом (rolling expanding). Без листов «Итог».
    """
    xl = pd.ExcelFile(xlsx_path, engine="openpyxl")
    if phase2_sheet not in xl.sheet_names:
        all_names = ", ".join(repr(n) for n in xl.sheet_names)
        raise SystemExit(
            f"Лист {phase2_sheet!r} не найден в {xlsx_path}\nДоступные листы: [{all_names}]"
        )

    df = pd.read_excel(xlsx_path, sheet_name=phase2_sheet, engine="openpyxl")
    if "predict_committed" not in df.columns:
        raise SystemExit(
            f"На листе {phase2_sheet!r} нет колонки «predict_committed». Колонки: {list(df.columns)}"
        )

    if "target_year" in df.columns:
        df = df.rename(columns={"target_year": "year"})
    if "target_month" in df.columns:
        df = df.rename(columns={"target_month": "month"})
    if "year" not in df.columns or "month" not in df.columns:
        raise SystemExit(
            "Для фазы 2 нужны target_year/target_month или year/month на листе committed."
        )

    df["fact_value"] = pd.to_numeric(df["fact_value"], errors="coerce").fillna(0.0)
    df["predict_committed"] = pd.to_numeric(df["predict_committed"], errors="coerce").fillna(0.0)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)
    df["month"] = pd.to_numeric(df["month"], errors="coerce").fillna(0).astype(int)

    base = _read_baseline_from_data_sheets(xlsx_path)
    if base.empty:
        print(
            "Предупреждение: листы «… Данные теста» не найдены или без нужных колонок — "
            "KPI «Текущий» (fact_predict) будет с нулевым прогнозом.",
            file=sys.stderr,
        )
        df["fact_predict"] = 0.0
    else:
        df["resist_id"] = pd.to_numeric(df["resist_id"], errors="coerce")
        df = df.merge(
            base,
            on=["resist_id", "operation_id", "year", "month"],
            how="left",
        )
        df["fact_predict"] = pd.to_numeric(df["fact_predict"], errors="coerce").fillna(0.0)

    df["predict_new"] = df["predict_committed"]
    df["predict_chosen"] = df["predict_committed"]

    allowed_keys = build_raw_allowed_keys(raw_files)
    df = filter_dashboard_by_raw_reference(df, allowed_keys, label="phase2")
    df = _compute_metric_columns(df)

    if "best_combo" in df.columns:
        df["best_model_name"] = df["best_combo"].apply(lambda x: str(x) if pd.notna(x) else "")
        best_map: dict[int | str, str] = {}
        for rid, grp in df.groupby("resist_id", dropna=True):
            s = grp["best_combo"].dropna()
            if s.empty:
                continue
            modes = s.mode()
            best_map[rid] = str(modes.iloc[0]) if len(modes) else str(s.iloc[0])
    else:
        df["best_model_name"] = ""
        best_map = {}

    if "division_title" not in df.columns:
        df["division_title"] = ""

    return df, best_map


def load_source(
    xlsx_path: Path,
    data_source: DataSource = "phase1",
    *,
    phase2_sheet: str = PHASE2_COMMITTED_SHEET,
    raw_files: Sequence[Path] = RAW_FILES,
) -> tuple[pd.DataFrame, dict[int | str, str]]:
    if data_source == "phase1":
        return load_source_phase1(xlsx_path, raw_files=raw_files)
    return load_source_phase2(xlsx_path, phase2_sheet, raw_files=raw_files)


# ---------------------------------------------------------------------------
#  Агрегация по resist_id (fact_predict + predict_new)
# ---------------------------------------------------------------------------


def _division_stats_dual(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for rid, grp in df.groupby("resist_id", dropna=True):
        m_acc = calc_mean_accuracy(grp)
        stab = calc_stability(grp)
        qi = calc_quality_index(m_acc, stab)

        # «Новый» блок — метрики по выбранному прогнозу (модель или Текущий по сравнению на Итог)
        grp_new = grp.copy()
        grp_new["accuracy_pct"] = grp_new["accuracy_pct_chosen"]
        m_acc_new = calc_mean_accuracy(grp_new)
        stab_new = calc_stability(grp_new)
        qi_new = calc_quality_index(m_acc_new, stab_new)

        div_titles = grp["division_title"].dropna() if "division_title" in grp.columns else pd.Series(dtype=object)
        div_title = div_titles.iloc[0] if len(div_titles) > 0 else ""
        div_title = div_title if pd.notna(div_title) and str(div_title).strip() else "(не указано)"

        model_name = grp["best_model_name"].dropna()
        model_name = model_name.iloc[0] if len(model_name) > 0 else ""

        rows.append({
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
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
#  Лист «Данные»
# ---------------------------------------------------------------------------

DATA_COLS = [
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
    "best_model_name",
]

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


def build_data_sheet(wb: Workbook, df: pd.DataFrame) -> dict:
    ws = wb.create_sheet("Данные")
    cols = [c for c in DATA_COLS if c in df.columns]
    headers = [DATA_HEADERS_RU.get(c, c) for c in cols]

    for ci, h in enumerate(headers, 1):
        ws.cell(row=1, column=ci, value=h)
    style_header_row(ws, 1, len(headers))

    for ri, (_, row) in enumerate(df.iterrows(), 2):
        for ci, col in enumerate(cols, 1):
            val = row[col]
            if isinstance(val, (np.integer,)):
                val = int(val)
            elif isinstance(val, (np.floating,)):
                val = float(val)
            ws.cell(row=ri, column=ci, value=val)

    last_row = ws.max_row
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last_row}"

    col_idx = {c: cols.index(c) + 1 for c in cols}

    for key in ("accuracy_pct", "accuracy_pct_new", "accuracy_pct_chosen"):
        idx = col_idx.get(key)
        if idx:
            letter = get_column_letter(idx)
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                ColorScaleRule(
                    start_type="num", start_value=80, start_color="F8696B",
                    mid_type="num", mid_value=90, mid_color="FFEB84",
                    end_type="num", end_value=100, end_color="63BE7B",
                ),
            )

    summary_row = last_row + 2
    ws.cell(row=summary_row, column=1, value="Итого:").font = Font(bold=True)

    acc_ci = col_idx.get("accuracy_pct")
    if acc_ci:
        m_acc = calc_mean_accuracy(df)
        stab = calc_stability(df)
        qi = calc_quality_index(m_acc, stab)
        ws.cell(row=summary_row, column=acc_ci, value=m_acc).font = Font(bold=True)
        ws.cell(row=summary_row + 1, column=1, value="Точность (ср.), %:").font = Font(bold=True, color="4472C4")
        ws.cell(row=summary_row + 1, column=acc_ci, value=m_acc).font = Font(bold=True, color="4472C4", size=14)
        ws.cell(row=summary_row + 2, column=1, value="Стабильность, %:").font = Font(bold=True, color="4472C4")
        ws.cell(row=summary_row + 2, column=acc_ci, value=stab).font = Font(bold=True, color="4472C4", size=14)
        ws.cell(row=summary_row + 3, column=1, value="Качество, %:").font = Font(bold=True, color="4472C4")
        ws.cell(row=summary_row + 3, column=acc_ci, value=qi).font = Font(bold=True, color="4472C4", size=14)

    auto_column_width(ws)
    return {"last_row": last_row, "col_indices": col_idx}


# ---------------------------------------------------------------------------
#  Лист «Оценка прогноза»
# ---------------------------------------------------------------------------


def _fill_for(val: float) -> PatternFill:
    if val >= 90:
        return GOOD_FILL
    if val >= 80:
        return NEUTRAL_FILL
    return BAD_FILL


def _global_metrics_from_acc(df: pd.DataFrame, acc_col: str) -> tuple[float, float, float]:
    """Точность / стабильность / качество по всему массиву, колонка построчной точности — acc_col."""
    t = df.copy()
    t["accuracy_pct"] = pd.to_numeric(t[acc_col], errors="coerce").fillna(0)
    ma = calc_mean_accuracy(t)
    st = calc_stability(t)
    qi = calc_quality_index(ma, st)
    return ma, st, qi


def _write_div_table_ext(
    ws,
    start_row: int,
    data: pd.DataFrame,
    is_worst: bool,
    *,
    second_block_label: str = "новый",
) -> int:
    headers = [
        "resist_id", "Подразделение",
        "Факт, шт.", "Прогноз, шт.", "Ошибка, шт.",
        "Точность, %", "Стабильность, %", "Качество, %",
        f"Точность ({second_block_label}), %",
        f"Стабильность ({second_block_label}), %",
        f"Качество ({second_block_label}), %",
        "Название модели прогноза",
    ]
    for ci, h in enumerate(headers, 1):
        ws.cell(row=start_row, column=ci, value=h)
    style_header_row(ws, start_row, len(headers))

    fill = BAD_FILL if is_worst else GOOD_FILL
    ri = start_row + 1
    for _, row in data.iterrows():
        ws.cell(row=ri, column=1, value=row["resist_id"])
        ws.cell(row=ri, column=2, value=row["division_title"])
        ws.cell(row=ri, column=3, value=int(row["fact_sum"]))
        ws.cell(row=ri, column=4, value=int(row["pred_sum"]))
        ws.cell(row=ri, column=5, value=int(row["error_sum"]))
        ws.cell(row=ri, column=6, value=row["mean_accuracy"])
        ws.cell(row=ri, column=7, value=row["stability"])
        ws.cell(row=ri, column=8, value=row["quality_index"])
        ws.cell(row=ri, column=9, value=row["mean_accuracy_new"])
        ws.cell(row=ri, column=10, value=row["stability_new"])
        ws.cell(row=ri, column=11, value=row["quality_index_new"])
        ws.cell(row=ri, column=12, value=row["best_model_name"])
        for ci in range(1, len(headers) + 1):
            ws.cell(row=ri, column=ci).border = THIN_BORDER
        ws.cell(row=ri, column=6).fill = fill
        for ci in (6, 7, 8, 9, 10, 11):
            ws.cell(row=ri, column=ci).number_format = "0.00"
        ri += 1
    return ri


def build_dashboard_sheet(
    wb: Workbook,
    df: pd.DataFrame,
    div_stats: pd.DataFrame,
    *,
    main_title: str = "Оценка качества прогноза (сравнение моделей)",
    second_forecast_label: str = "Новый",
    second_block_table_label: str = "новый",
) -> None:
    ws = wb.create_sheet("Оценка прогноза")

    m_acc, stab, qi = _global_metrics_from_acc(df, "accuracy_pct")
    m_acc_n, stab_n, qi_n = _global_metrics_from_acc(df, "accuracy_pct_chosen")
    sum_pred_chosen = int(pd.to_numeric(df["predict_chosen"], errors="coerce").fillna(0).sum())

    ws.merge_cells("A1:L1")
    ws.cell(row=1, column=1, value=main_title)
    ws.cell(row=1, column=1).font = Font(bold=True, size=16)
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center")

    kpi_row = 3
    write_kpi_card(ws, kpi_row, 1, "Точность\n(Текущий)", f"{m_acc:.1f}%", _fill_for(m_acc))
    write_kpi_card(ws, kpi_row, 3, "Стабильность\n(Текущий)", f"{stab:.1f}%", _fill_for(stab))
    write_kpi_card(ws, kpi_row, 5, "Качество\n(Текущий)", f"{qi:.1f}%", _fill_for(qi))
    write_kpi_card(ws, kpi_row, 7, "Факт\nвсего", f"{int(df['fact_value'].sum()):,}", GOOD_FILL)
    write_kpi_card(ws, kpi_row, 9, "Прогноз\n(Текущий) всего", f"{int(df['fact_predict'].sum()):,}", GOOD_FILL)
    write_kpi_card(ws, kpi_row, 11, "Кол-во\nстрок", len(df), GOOD_FILL)

    ws.row_dimensions[kpi_row].height = 50
    ws.row_dimensions[kpi_row + 1].height = 55

    kpi_row2 = 5
    write_kpi_card(
        ws, kpi_row2, 1, f"Точность\n({second_forecast_label})", f"{m_acc_n:.1f}%", _fill_for(m_acc_n)
    )
    write_kpi_card(
        ws, kpi_row2, 3, f"Стабильность\n({second_forecast_label})", f"{stab_n:.1f}%", _fill_for(stab_n)
    )
    write_kpi_card(
        ws, kpi_row2, 5, f"Качество\n({second_forecast_label})", f"{qi_n:.1f}%", _fill_for(qi_n)
    )
    write_kpi_card(ws, kpi_row2, 7, "Факт\nвсего", f"{int(df['fact_value'].sum()):,}", GOOD_FILL)
    write_kpi_card(
        ws, kpi_row2, 9, f"Прогноз\n({second_forecast_label}) всего", f"{sum_pred_chosen:,}", GOOD_FILL
    )
    write_kpi_card(ws, kpi_row2, 11, "Кол-во\nстрок", len(df), GOOD_FILL)

    ws.row_dimensions[kpi_row2].height = 50
    ws.row_dimensions[kpi_row2 + 1].height = 55

    # ---- Топ-10 ХУДШИХ по fact_predict ----
    sec = 8
    ws.cell(row=sec, column=1,
            value="Топ-10 моделей (resist_id) с ХУДШИМ качеством (fact_predict)")
    ws.cell(row=sec, column=1).font = Font(bold=True, size=12, color="C00000")
    ws.merge_cells(start_row=sec, start_column=1, end_row=sec, end_column=12)

    worst = div_stats.nsmallest(10, "quality_index")
    next_row = _write_div_table_ext(
        ws, sec + 1, worst, is_worst=True, second_block_label=second_block_table_label
    )

    # ---- Топ-10 ЛУЧШИХ по fact_predict ----
    sec2 = next_row + 1
    ws.cell(row=sec2, column=1,
            value="Топ-10 моделей (resist_id) с ЛУЧШИМ качеством (fact_predict)")
    ws.cell(row=sec2, column=1).font = Font(bold=True, size=12, color="007030")
    ws.merge_cells(start_row=sec2, start_column=1, end_row=sec2, end_column=12)

    best = div_stats.nlargest(10, "quality_index")
    next_row = _write_div_table_ext(
        ws, sec2 + 1, best, is_worst=False, second_block_label=second_block_table_label
    )

    # ---- Полная таблица по resist_id ----
    sec3 = next_row + 1
    ws.cell(row=sec3, column=1,
            value="Точность, стабильность и качество по моделям (resist_id)")
    ws.cell(row=sec3, column=1).font = Font(bold=True, size=12)
    ws.merge_cells(start_row=sec3, start_column=1, end_row=sec3, end_column=12)

    full_headers = [
        "resist_id", "Подразделение",
        "Точность, %", "Стабильность, %", "Качество, %", "Факт, шт.",
        f"Точность ({second_block_table_label}), %",
        f"Стабильность ({second_block_table_label}), %",
        f"Качество ({second_block_table_label}), %",
        "Название модели прогноза",
    ]
    hdr_row = sec3 + 1
    for ci, h in enumerate(full_headers, 1):
        ws.cell(row=hdr_row, column=ci, value=h)
    style_header_row(ws, hdr_row, len(full_headers))

    for ri, (_, row) in enumerate(div_stats.iterrows(), hdr_row + 1):
        ws.cell(row=ri, column=1, value=row["resist_id"])
        ws.cell(row=ri, column=2, value=row["division_title"])
        ws.cell(row=ri, column=3, value=row["mean_accuracy"])
        ws.cell(row=ri, column=4, value=row["stability"])
        ws.cell(row=ri, column=5, value=row["quality_index"])
        ws.cell(row=ri, column=6, value=int(row["fact_sum"]))
        ws.cell(row=ri, column=7, value=row["mean_accuracy_new"])
        ws.cell(row=ri, column=8, value=row["stability_new"])
        ws.cell(row=ri, column=9, value=row["quality_index_new"])
        ws.cell(row=ri, column=10, value=row["best_model_name"])
        for ci in range(1, len(full_headers) + 1):
            ws.cell(row=ri, column=ci).border = THIN_BORDER
        for ci in (3, 4, 5, 7, 8, 9):
            ws.cell(row=ri, column=ci).number_format = "0.00"

    for col in range(1, 13):
        ws.column_dimensions[get_column_letter(col)].width = 18


# ---------------------------------------------------------------------------
#  Лист «Тепловая карта»
# ---------------------------------------------------------------------------


def _write_heatmap_block(
    ws,
    start_row: int,
    title: str,
    df: pd.DataFrame,
    acc_col: str,
    months_present: list,
    resist_ids: list,
) -> int:
    last_month_col = len(months_present) + 2
    ws.cell(row=start_row, column=1, value=title)
    ws.cell(row=start_row, column=1).font = Font(bold=True, size=14)
    ws.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=last_month_col)

    hdr = start_row + 2
    ws.cell(row=hdr, column=1, value="resist_id")
    ws.cell(row=hdr, column=2, value="Подразделение")
    for mi, m in enumerate(months_present, 3):
        ws.cell(row=hdr, column=mi, value=MONTH_NAMES[int(m) - 1] if 1 <= m <= 12 else str(m))
    style_header_row(ws, hdr, last_month_col)

    for di, rid in enumerate(resist_ids, hdr + 1):
        slice_any = df[df["resist_id"] == rid]
        div_titles = slice_any["division_title"].dropna()
        div_title = div_titles.iloc[0] if len(div_titles) > 0 else "(не указано)"
        div_title = div_title if pd.notna(div_title) and str(div_title).strip() else "(не указано)"

        ws.cell(row=di, column=1, value=rid).border = THIN_BORDER
        ws.cell(row=di, column=2, value=div_title).border = THIN_BORDER

        for mi, m in enumerate(months_present, 3):
            sl = df[(df["resist_id"] == rid) & (df["month"] == m)].copy()
            if sl.empty or sl["fact_value"].sum() == 0:
                ws.cell(row=di, column=mi, value="—")
                ws.cell(row=di, column=mi).alignment = Alignment(horizontal="center")
            else:
                sl["accuracy_pct"] = sl[acc_col]
                m_a = calc_mean_accuracy(sl)
                s = calc_stability(sl)
                q = calc_quality_index(m_a, s)
                ws.cell(row=di, column=mi, value=q)
                ws.cell(row=di, column=mi).number_format = "0.0"
            ws.cell(row=di, column=mi).border = THIN_BORDER

    last_data_row = hdr + len(resist_ids)
    for mi in range(3, last_month_col + 1):
        cl = get_column_letter(mi)
        ws.conditional_formatting.add(
            f"{cl}{hdr + 1}:{cl}{last_data_row}",
            ColorScaleRule(
                start_type="num", start_value=80, start_color="F8696B",
                mid_type="num", mid_value=90, mid_color="FFEB84",
                end_type="num", end_value=100, end_color="63BE7B",
            ),
        )

    total_row = last_data_row + 1
    ws.cell(row=total_row, column=1, value="ИТОГО").font = Font(bold=True, size=12)
    ws.cell(row=total_row, column=1).border = THIN_BORDER
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=2)

    for mi, m in enumerate(months_present, 3):
        sl = df[df["month"] == m].copy()
        if sl.empty or sl["fact_value"].sum() == 0:
            ws.cell(row=total_row, column=mi, value="—")
        else:
            sl["accuracy_pct"] = sl[acc_col]
            m_a = calc_mean_accuracy(sl)
            s = calc_stability(sl)
            q = calc_quality_index(m_a, s)
            ws.cell(row=total_row, column=mi, value=q)
            ws.cell(row=total_row, column=mi).number_format = "0.0"
        ws.cell(row=total_row, column=mi).border = THIN_BORDER
        ws.cell(row=total_row, column=mi).font = Font(bold=True)

    return total_row + 2


def build_heatmap_sheet(
    wb: Workbook,
    df: pd.DataFrame,
    *,
    title_baseline: str = "Тепловая карта: Качество (%) по fact_predict",
    title_chosen: str = "Тепловая карта: Качество (%) по выбранному лучшему прогнозу",
) -> None:
    ws = wb.create_sheet("Тепловая карта")

    months_present = sorted(df["month"].unique())
    resist_ids = sorted(
        [x for x in df["resist_id"].unique() if pd.notna(x)],
        key=lambda x: (0, x) if isinstance(x, (int, float)) else (1, str(x)),
    )

    next_row = _write_heatmap_block(
        ws, 1,
        title_baseline,
        df, "accuracy_pct", months_present, resist_ids,
    )
    _write_heatmap_block(
        ws, next_row + 1,
        title_chosen,
        df, "accuracy_pct_chosen", months_present, resist_ids,
    )

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 35
    last_month_col = len(months_present) + 2
    for ci in range(3, last_month_col + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 10

    legend_row = ws.max_row + 2
    ws.cell(row=legend_row, column=1, value="Легенда:").font = Font(bold=True)
    ws.cell(row=legend_row + 1, column=1, value="Красный — качество < 80%").font = Font(color="C00000")
    ws.cell(row=legend_row + 2, column=1, value="Жёлтый — качество 80-90%").font = Font(color="BF8F00")
    ws.cell(row=legend_row + 3, column=1, value="Зелёный — качество > 90%").font = Font(color="007030")


# ---------------------------------------------------------------------------
#  Главная функция
# ---------------------------------------------------------------------------


def build_dashboard(
    input_path: Path,
    output_path: Path | None = None,
    *,
    data_source: DataSource = "phase1",
    phase2_sheet: str = PHASE2_COMMITTED_SHEET,
    second_forecast_label: str = "Новый",
    second_block_table_label: str = "новый",
    raw_files: Sequence[Path] = RAW_FILES,
) -> Path:
    df, best_map = load_source(
        input_path,
        data_source=data_source,
        phase2_sheet=phase2_sheet,
        raw_files=raw_files,
    )
    div_stats = _division_stats_dual(df)

    wb = Workbook()
    wb.remove(wb.active)

    build_data_sheet(wb, df)

    if data_source == "phase2":
        build_dashboard_sheet(
            wb,
            df,
            div_stats,
            main_title="Оценка качества прогноза (фаза 2, committed)",
            second_forecast_label="Фаза 2",
            second_block_table_label="фаза 2",
        )
        build_heatmap_sheet(
            wb,
            df,
            title_baseline="Тепловая карта: Качество (%) по fact_predict (текущий, из листов «Данные теста»)",
            title_chosen="Тепловая карта: Качество (%) по прогнозу фазы 2 (committed)",
        )
    else:
        build_dashboard_sheet(
            wb,
            df,
            div_stats,
            second_forecast_label=second_forecast_label,
            second_block_table_label=second_block_table_label,
        )
        build_heatmap_sheet(
            wb,
            df,
            title_chosen=f"Тепловая карта: Качество (%) по выбранному прогнозу ({second_block_table_label})",
        )

    if output_path is None:
        if data_source == "phase2":
            output_path = input_path.parent / f"{input_path.stem}_dashboard_phase2_raw_filter.xlsx"
        else:
            output_path = input_path.parent / "model_comparison_dashboard_raw_filter.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))

    print(f"Дашборд сохранён: {output_path.resolve()} (источник данных: {data_source})")
    print(f"  resist_id: {len(best_map)}, строк данных: {len(df)}")
    return output_path


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Дашборд сравнения моделей с фильтрацией по raw nb37 "
            "(EXCLUDED_RESIST_IDS, active=False, drop leading fact_predict)."
        )
    )
    p.add_argument("--input", "-i", type=Path, default=None,
                   help="Путь к входному xlsx (ноутбук 21 / model_comparison_multi и т.д.)")
    p.add_argument("--output", "-o", type=Path, default=None,
                   help="Выходной xlsx (по умолчанию: model_comparison_dashboard_raw_filter.xlsx)")
    p.add_argument(
        "--data-source",
        choices=("phase1", "phase2"),
        default="phase1",
        help="phase1: листы «… Итог» + «… Данные теста»; phase2: лист committed + merge fact_predict из «Данные теста»",
    )
    p.add_argument(
        "--phase2-sheet",
        type=str,
        default=PHASE2_COMMITTED_SHEET,
        help=f"Имя листа для фазы 2 (default: {PHASE2_COMMITTED_SHEET!r})",
    )
    p.add_argument(
        "--second-forecast-label",
        type=str,
        default="Новый",
        help="Подпись второго прогноза на листе «Оценка прогноза» (фаза 1; default: Новый), например «Комбайн»",
    )
    p.add_argument(
        "--second-block-table-label",
        type=str,
        default="новый",
        help="Суффикс в заголовках таблиц/столбцов для второго прогноза (фаза 1; default: новый), например «Комбайн»",
    )
    args = p.parse_args()

    inp = args.input if args.input else _default_input()
    if not inp.is_file():
        print(f"Файл не найден: {inp}", file=sys.stderr)
        sys.exit(1)

    if args.data_source == "phase2" and (
        args.second_forecast_label != "Новый" or args.second_block_table_label != "новый"
    ):
        print(
            "Предупреждение: --second-* заданы при phase2; для фазы 2 подписи «Фаза 2» фиксированы в коде.",
            file=sys.stderr,
        )

    build_dashboard(
        inp,
        args.output,
        data_source=args.data_source,
        phase2_sheet=args.phase2_sheet,
        second_forecast_label=args.second_forecast_label,
        second_block_table_label=args.second_block_table_label,
    )


if __name__ == "__main__":
    main()
