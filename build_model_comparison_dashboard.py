"""
Дашборд по model_comparison_multi.xlsx (или model_comparison.xlsx).

Читает листы «{rid} Итог» и «{rid} Данные теста», собирает объединённый
DataFrame и генерирует Excel-дашборд с тремя листами:
  1. Данные          — помесячные строки с fact_predict и лучшим новым прогнозом
  2. Оценка прогноза — KPI, топ-10 лучших/худших, полная таблица по resist_id
  3. Тепловая карта  — качество (fact_predict) и качество (лучшая модель) по месяцам

Использование:
    python scripts/build_model_comparison_dashboard.py
    python scripts/build_model_comparison_dashboard.py --input path/to/file.xlsx
    python scripts/build_model_comparison_dashboard.py --input path/to/file.xlsx --output out.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
sys.path.insert(0, str(_project_root))

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

# ---------------------------------------------------------------------------
#  Константы
# ---------------------------------------------------------------------------

ITOG_SUFFIX = " Итог"
DATA_SUFFIX = " Данные теста"

MONTH_NAMES = [
    "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
]


def _default_input() -> Path:
    return _project_root / "data" / "processed" / "model_comparison_multi.xlsx"


# ---------------------------------------------------------------------------
#  Чтение исходного Excel
# ---------------------------------------------------------------------------


def _find_new_col(columns: list[str]) -> str | None:
    for c in columns:
        if c.endswith(" (новый)"):
            return c
    return None


def load_source(xlsx_path: Path) -> tuple[pd.DataFrame, dict[int | str, str]]:
    """
    Возвращает:
      df        — объединённый DataFrame (fact_value, fact_predict, predict_new, …)
      best_map  — {resist_id: название лучшей модели (Комбинация)}
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
    for name in itog_sheets:
        df_it = pd.read_excel(xlsx_path, sheet_name=name, engine="openpyxl")
        if "Комбинация" in df_it.columns and len(df_it) > 0:
            rid_raw = name.removesuffix(ITOG_SUFFIX).strip()
            try:
                rid = int(rid_raw)
            except ValueError:
                rid = rid_raw
            best_map[rid] = str(df_it.iloc[0]["Комбинация"])

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

    df["abs_error"] = (df["fact_value"] - df["fact_predict"]).abs()
    df["accuracy_pct"] = _accuracy_col(df["fact_value"], df["fact_predict"])

    df["abs_error_new"] = (df["fact_value"] - df["predict_new"]).abs()
    df["accuracy_pct_new"] = _accuracy_col(df["fact_value"], df["predict_new"])

    if "resist_id" in df.columns:
        df["resist_id"] = pd.to_numeric(df["resist_id"], errors="coerce")
        df["resist_id"] = df["resist_id"].apply(
            lambda x: int(x) if pd.notna(x) and float(x) == int(x) else x
        )
    if "month" in df.columns:
        df["month"] = pd.to_numeric(df["month"], errors="coerce").fillna(0).astype(int)
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)

    df["best_model_name"] = df["resist_id"].map(best_map).fillna("")

    if "division_title" not in df.columns:
        df["division_title"] = ""

    return df, best_map


def _accuracy_col(fact: pd.Series, pred: pd.Series) -> pd.Series:
    acc = np.where(
        fact == 0,
        np.where(pred == 0, 100.0, 0.0),
        np.clip(100.0 - (fact - pred).abs() / fact * 100.0, 0, 100),
    )
    return np.round(acc, 2)


# ---------------------------------------------------------------------------
#  Агрегация по resist_id (fact_predict + predict_new)
# ---------------------------------------------------------------------------


def _division_stats_dual(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for rid, grp in df.groupby("resist_id", dropna=True):
        m_acc = calc_mean_accuracy(grp)
        stab = calc_stability(grp)
        qi = calc_quality_index(m_acc, stab)

        grp_new = grp.copy()
        grp_new["accuracy_pct"] = grp_new["accuracy_pct_new"]
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

    for key in ("accuracy_pct", "accuracy_pct_new"):
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


def _write_div_table_ext(
    ws,
    start_row: int,
    data: pd.DataFrame,
    is_worst: bool,
) -> int:
    headers = [
        "resist_id", "Подразделение",
        "Факт, шт.", "Прогноз, шт.", "Ошибка, шт.",
        "Точность, %", "Стабильность, %", "Качество, %",
        "Точность (новый), %", "Стабильность (новый), %", "Качество (новый), %",
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


def build_dashboard_sheet(wb: Workbook, df: pd.DataFrame, div_stats: pd.DataFrame) -> None:
    ws = wb.create_sheet("Оценка прогноза")

    m_acc = calc_mean_accuracy(df)
    stab = calc_stability(df)
    qi = calc_quality_index(m_acc, stab)

    ws.merge_cells("A1:L1")
    ws.cell(row=1, column=1, value="Оценка качества прогноза (сравнение моделей)")
    ws.cell(row=1, column=1).font = Font(bold=True, size=16)
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center")

    kpi_row = 3
    write_kpi_card(ws, kpi_row, 1, "Точность\n(fact_predict)", f"{m_acc:.1f}%", _fill_for(m_acc))
    write_kpi_card(ws, kpi_row, 3, "Стабильность\n(fact_predict)", f"{stab:.1f}%", _fill_for(stab))
    write_kpi_card(ws, kpi_row, 5, "Качество\n(fact_predict)", f"{qi:.1f}%", _fill_for(qi))
    write_kpi_card(ws, kpi_row, 7, "Факт\nвсего", f"{int(df['fact_value'].sum()):,}", GOOD_FILL)
    write_kpi_card(ws, kpi_row, 9, "Прогноз (fp)\nвсего", f"{int(df['fact_predict'].sum()):,}", GOOD_FILL)
    write_kpi_card(ws, kpi_row, 11, "Кол-во\nстрок", len(df), GOOD_FILL)

    ws.row_dimensions[kpi_row].height = 50
    ws.row_dimensions[kpi_row + 1].height = 55

    # ---- Топ-10 ХУДШИХ по fact_predict ----
    sec = 7
    ws.cell(row=sec, column=1,
            value="Топ-10 моделей (resist_id) с ХУДШИМ качеством (fact_predict)")
    ws.cell(row=sec, column=1).font = Font(bold=True, size=12, color="C00000")
    ws.merge_cells(start_row=sec, start_column=1, end_row=sec, end_column=12)

    worst = div_stats.nsmallest(10, "quality_index")
    next_row = _write_div_table_ext(ws, sec + 1, worst, is_worst=True)

    # ---- Топ-10 ЛУЧШИХ по fact_predict ----
    sec2 = next_row + 1
    ws.cell(row=sec2, column=1,
            value="Топ-10 моделей (resist_id) с ЛУЧШИМ качеством (fact_predict)")
    ws.cell(row=sec2, column=1).font = Font(bold=True, size=12, color="007030")
    ws.merge_cells(start_row=sec2, start_column=1, end_row=sec2, end_column=12)

    best = div_stats.nlargest(10, "quality_index")
    next_row = _write_div_table_ext(ws, sec2 + 1, best, is_worst=False)

    # ---- Полная таблица по resist_id ----
    sec3 = next_row + 1
    ws.cell(row=sec3, column=1,
            value="Точность, стабильность и качество по моделям (resist_id)")
    ws.cell(row=sec3, column=1).font = Font(bold=True, size=12)
    ws.merge_cells(start_row=sec3, start_column=1, end_row=sec3, end_column=12)

    full_headers = [
        "resist_id", "Подразделение",
        "Точность, %", "Стабильность, %", "Качество, %", "Факт, шт.",
        "Точность (новый), %", "Стабильность (новый), %", "Качество (новый), %",
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


def build_heatmap_sheet(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Тепловая карта")

    months_present = sorted(df["month"].unique())
    resist_ids = sorted(
        [x for x in df["resist_id"].unique() if pd.notna(x)],
        key=lambda x: (0, x) if isinstance(x, (int, float)) else (1, str(x)),
    )

    next_row = _write_heatmap_block(
        ws, 1,
        "Тепловая карта: Качество (%) по fact_predict",
        df, "accuracy_pct", months_present, resist_ids,
    )
    _write_heatmap_block(
        ws, next_row + 1,
        "Тепловая карта: Качество (%) по лучшей модели",
        df, "accuracy_pct_new", months_present, resist_ids,
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


def build_dashboard(input_path: Path, output_path: Path | None = None) -> Path:
    df, best_map = load_source(input_path)
    div_stats = _division_stats_dual(df)

    wb = Workbook()
    wb.remove(wb.active)

    build_data_sheet(wb, df)
    build_dashboard_sheet(wb, df, div_stats)
    build_heatmap_sheet(wb, df)

    if output_path is None:
        output_path = input_path.parent / "model_comparison_dashboard.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))

    print(f"Дашборд сохранён: {output_path.resolve()}")
    print(f"  resist_id: {len(best_map)}, строк данных: {len(df)}")
    return output_path


def main() -> None:
    p = argparse.ArgumentParser(
        description="Дашборд по model_comparison_multi.xlsx (сравнение fact_predict и лучшей модели)"
    )
    p.add_argument("--input", "-i", type=Path, default=None,
                   help="Путь к model_comparison_multi.xlsx")
    p.add_argument("--output", "-o", type=Path, default=None,
                   help="Путь к выходному xlsx (default: model_comparison_dashboard.xlsx)")
    args = p.parse_args()

    inp = args.input if args.input else _default_input()
    if not inp.is_file():
        print(f"Файл не найден: {inp}", file=sys.stderr)
        sys.exit(1)

    build_dashboard(inp, args.output)


if __name__ == "__main__":
    main()
