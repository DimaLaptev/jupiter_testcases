"""
Сборка Excel-дашборда «Оценка качества прогноза (по средней точности)».

Отличие от build_metrics_dashboard.py:
  Вместо «Взвешенной точности» (1 − WMAPE, с учётом веса операций)
  используется «Точность» — простое среднее по колонке accuracy_pct
  (обратный MAPE, 1 − MAPE), т.е. каждая строка имеет одинаковый вес.

Метрики:
  - Точность прогноза  — построчная: MAX(0; 100% − |Факт−Прогноз|/Факт)
  - Точность           — среднее арифметическое «Точность прогноза» по видимым строкам
  - Стабильность       — (1 − CV) * 100%, где CV = σ/μ по «Точность прогноза»
  - Качество           — гармоническое среднее Точности и Стабильности

Использование:
    python build_metrics_dashboard_simple.py
    python build_metrics_dashboard_simple.py --input path/to/file.xlsx
    python build_metrics_dashboard_simple.py --input path/to/file.xlsx --output result.xlsx
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
#  Константы
# ---------------------------------------------------------------------------

THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
KPI_FONT = Font(bold=True, size=22)
KPI_LABEL_FONT = Font(bold=True, size=11, color="555555")
GOOD_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
BAD_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
NEUTRAL_FILL = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")

DATA_COLS = [
    "resist_id",
    "division_title",
    "operation_id",
    "date",
    "month",
    "year",
    "fact_value",
    "fact_predict",
    "abs_error",
    "accuracy_pct",
    "fact_fts",
]

DATA_HEADERS_RU = {
    "resist_id": "Модель (resist_id)",
    "division_title": "Подразделение (division)",
    "operation_id": "ID операции (operation_id)",
    "date": "Дата (date)",
    "month": "Месяц (month)",
    "year": "Год (year)",
    "fact_value": "Факт, шт. (fact_value)",
    "fact_predict": "Прогноз, шт. (fact_predict)",
    "abs_error": "Ошибка, шт. (abs_error)",
    "accuracy_pct": "Точность прогноза, % (Forecast Accuracy)",
    "fact_fts": "Факт, ПШЕ (fact_fts)",
}

KPI_CELLS = {
    "mean_accuracy": (3, 1),
    "stability": (3, 3),
    "quality_index": (3, 5),
    "total_fact": (3, 7),
    "total_pred": (3, 9),
    "visible_rows": (3, 11),
}


# ---------------------------------------------------------------------------
#  Вспомогательные функции
# ---------------------------------------------------------------------------


def load_dataframe(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if p.suffix in (".xlsx", ".xls", ".xlsm"):
        return pd.read_excel(p)
    if p.suffix == ".csv":
        return pd.read_csv(p)
    raise ValueError(f"Неподдерживаемый формат: {p.suffix}")


def prepare_dataframe(df: pd.DataFrame, forecast_col: str = "fact_predict") -> pd.DataFrame:
    df = df.copy()

    if forecast_col not in df.columns:
        raise ValueError(f"Колонка прогноза не найдена: {forecast_col}")

    for col in ("fact_value", forecast_col):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["abs_error"] = (df["fact_value"] - df[forecast_col]).abs()

    acc = np.where(
        df["fact_value"] == 0,
        np.where(df[forecast_col] == 0, 100.0, 0.0),
        np.clip(100.0 - df["abs_error"] / df["fact_value"] * 100.0, 0, 100),
    )
    df["accuracy_pct"] = np.round(acc, 2)

    if forecast_col != "fact_predict":
        df["fact_predict"] = df[forecast_col].copy()

    col_map = {"Факт, ПШЕ": "fact_fts"}
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)

    if "fact_fts" in df.columns:
        df["fact_fts"] = pd.to_numeric(df["fact_fts"], errors="coerce").fillna(0)
    else:
        df["fact_fts"] = 0.0

    if "month" not in df.columns and "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["month"] = df["date"].dt.month
        df["year"] = df["date"].dt.year
    else:
        df["month"] = pd.to_numeric(df["month"], errors="coerce").fillna(0).astype(int)
        df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)

    if "resist_id" not in df.columns:
        df["resist_id"] = ""
    if "division_title" not in df.columns:
        df["division_title"] = ""

    present = [c for c in DATA_COLS if c in df.columns]
    extra = [c for c in df.columns if c not in DATA_COLS]
    return df[present + extra]


def calc_mean_accuracy(df: pd.DataFrame) -> float:
    """Точность — простое среднее по accuracy_pct (обратный MAPE)."""
    if df.empty:
        return 0.0
    return round(df["accuracy_pct"].mean(), 2)


def calc_stability(df: pd.DataFrame) -> float:
    mean_acc = df["accuracy_pct"].mean()
    if mean_acc == 0 or pd.isna(mean_acc):
        return 0.0
    cv = df["accuracy_pct"].std(ddof=0) / mean_acc
    return round(max(0.0, (1 - cv)) * 100, 2)


def calc_quality_index(accuracy: float, stability: float) -> float:
    if accuracy + stability == 0:
        return 0.0
    return round(2 * accuracy * stability / (accuracy + stability), 2)


# ---------------------------------------------------------------------------
#  Стилизация
# ---------------------------------------------------------------------------


def style_header_row(ws, row: int, max_col: int) -> None:
    for col in range(1, max_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER


def auto_column_width(ws, min_width: int = 10, max_width: int = 35) -> None:
    for col_cells in ws.columns:
        col_letter = get_column_letter(col_cells[0].column)
        max_len = max(
            (len(str(c.value)) if c.value is not None else 0 for c in col_cells),
            default=0,
        )
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, min_width), max_width)


def write_kpi_card(ws, row: int, col: int, label: str, value, fill: PatternFill) -> None:
    cell_val = ws.cell(row=row, column=col, value=value)
    cell_val.font = KPI_FONT
    cell_val.fill = fill
    cell_val.alignment = Alignment(horizontal="center", vertical="center")
    cell_val.border = THIN_BORDER

    cell_lbl = ws.cell(row=row + 1, column=col, value=label)
    cell_lbl.font = KPI_LABEL_FONT
    cell_lbl.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell_lbl.border = THIN_BORDER


# ---------------------------------------------------------------------------
#  VBA-макрос
# ---------------------------------------------------------------------------


def _build_vba_code(last_data_row: int, col_indices: dict[str, int]) -> str:
    acc_col = col_indices["accuracy_pct"]
    fact_col = col_indices["fact_value"]
    pred_col = col_indices["fact_predict"]
    err_col = col_indices["abs_error"]
    fact_fts_col = col_indices.get("fact_fts", 0)

    kpi_ma = KPI_CELLS["mean_accuracy"]
    kpi_st = KPI_CELLS["stability"]
    kpi_qi = KPI_CELLS["quality_index"]
    kpi_tf = KPI_CELLS["total_fact"]
    kpi_tp = KPI_CELLS["total_pred"]
    kpi_vr = KPI_CELLS["visible_rows"]

    return f'''
' === RecalcMetrics: пересчёт метрик по видимым строкам листа «Данные» ===
' Версия «по средней точности» (без взвешивания по объёму).

Public Sub RecalcMetrics()
    On Error GoTo ErrHandler

    Dim wsData As Worksheet
    Dim wsDash As Worksheet
    Set wsData = ThisWorkbook.Sheets(1)
    Set wsDash = ThisWorkbook.Sheets(2)

    Dim lastRow As Long
    lastRow = {last_data_row}

    Dim accCol As Long:     accCol = {acc_col}
    Dim factCol As Long:    factCol = {fact_col}
    Dim predCol As Long:    predCol = {pred_col}
    Dim errCol As Long:     errCol = {err_col}
    Dim factFtsCol As Long: factFtsCol = {fact_fts_col}

    Dim sumAcc As Double:     sumAcc = 0
    Dim sumAcc2 As Double:    sumAcc2 = 0
    Dim sumFact As Double:    sumFact = 0
    Dim sumPred As Double:    sumPred = 0
    Dim sumErr As Double:     sumErr = 0
    Dim sumFactFts As Double: sumFactFts = 0
    Dim nVisible As Long:     nVisible = 0
    Dim r As Long
    Dim accVal As Double
    Dim meanAcc As Double
    Dim stdAcc As Double
    Dim cv As Double
    Dim stab As Double
    Dim qi As Double
    Dim summaryRow As Long
    Dim maRow As Long
    Dim stRow As Long
    Dim qiRow As Long

    Application.ScreenUpdating = False

    For r = 2 To lastRow
        If wsData.Rows(r).Hidden = False Then
            nVisible = nVisible + 1
            accVal = CDbl(wsData.Cells(r, accCol).Value)
            sumAcc = sumAcc + accVal
            sumAcc2 = sumAcc2 + accVal * accVal
            sumFact = sumFact + CDbl(wsData.Cells(r, factCol).Value)
            sumPred = sumPred + CDbl(wsData.Cells(r, predCol).Value)
            sumErr = sumErr + CDbl(wsData.Cells(r, errCol).Value)
            If factFtsCol > 0 Then
                sumFactFts = sumFactFts + CDbl(wsData.Cells(r, factFtsCol).Value)
            End If
        End If
    Next r

    ' --- Точность (среднее accuracy_pct) ---
    If nVisible = 0 Then
        meanAcc = 0
    Else
        meanAcc = sumAcc / nVisible
    End If

    ' --- Стабильность = 1 - CV ---
    If nVisible = 0 Or meanAcc = 0 Then
        stab = 0
    Else
        stdAcc = Sqr(sumAcc2 / nVisible - meanAcc * meanAcc)
        cv = stdAcc / meanAcc
        stab = (1 - cv) * 100
        If stab < 0 Then stab = 0
    End If

    ' --- Качество = гармоническое среднее ---
    If (meanAcc + stab) = 0 Then
        qi = 0
    Else
        qi = 2 * meanAcc * stab / (meanAcc + stab)
    End If

    ' --- Запись на лист «Оценка прогноза» ---
    wsDash.Cells({kpi_ma[0]}, {kpi_ma[1]}).Value = Format(Round(meanAcc, 1), "0.0") & "%"
    wsDash.Cells({kpi_st[0]}, {kpi_st[1]}).Value = Format(Round(stab, 1), "0.0") & "%"
    wsDash.Cells({kpi_qi[0]}, {kpi_qi[1]}).Value = Format(Round(qi, 1), "0.0") & "%"
    wsDash.Cells({kpi_tf[0]}, {kpi_tf[1]}).Value = Format(CLng(sumFact), "#,##0")
    wsDash.Cells({kpi_tp[0]}, {kpi_tp[1]}).Value = Format(CLng(sumPred), "#,##0")
    wsDash.Cells({kpi_vr[0]}, {kpi_vr[1]}).Value = nVisible

    ' --- Запись итогов на лист «Данные» ---
    summaryRow = lastRow + 2

    wsData.Cells(summaryRow, factCol).Value = sumFact
    wsData.Cells(summaryRow, errCol).Value = sumErr
    wsData.Cells(summaryRow, accCol).Value = Round(meanAcc, 2)

    If factFtsCol > 0 Then wsData.Cells(summaryRow, factFtsCol).Value = sumFactFts

    maRow = summaryRow + 1
    wsData.Cells(maRow, accCol).Value = Round(meanAcc, 2)

    stRow = summaryRow + 2
    wsData.Cells(stRow, accCol).Value = Round(stab, 2)

    qiRow = summaryRow + 3
    wsData.Cells(qiRow, accCol).Value = Round(qi, 2)

    Application.ScreenUpdating = True
    Exit Sub

ErrHandler:
    Application.ScreenUpdating = True
    MsgBox "Ошибка пересчёта метрик: " & Err.Description, vbExclamation
End Sub
'''


# ---------------------------------------------------------------------------
#  Лист «Данные»
# ---------------------------------------------------------------------------


def build_data_sheet(wb: Workbook, df: pd.DataFrame) -> dict:
    ws = wb.create_sheet("Данные")

    cols_to_write = [c for c in DATA_COLS if c in df.columns]
    headers = [DATA_HEADERS_RU.get(c, c) for c in cols_to_write]

    for ci, h in enumerate(headers, 1):
        ws.cell(row=1, column=ci, value=h)
    style_header_row(ws, 1, len(headers))

    for ri, (_, row) in enumerate(df.iterrows(), 2):
        for ci, col in enumerate(cols_to_write, 1):
            val = row[col]
            if isinstance(val, (np.integer,)):
                val = int(val)
            elif isinstance(val, (np.floating,)):
                val = float(val)
            ws.cell(row=ri, column=ci, value=val)

    last_row = ws.max_row
    last_col_letter = get_column_letter(len(headers))
    ws.auto_filter.ref = f"A1:{last_col_letter}{last_row}"

    col_indices = {c: cols_to_write.index(c) + 1 for c in cols_to_write}

    acc_idx = col_indices.get("accuracy_pct")
    if acc_idx:
        letter = get_column_letter(acc_idx)
        ws.conditional_formatting.add(
            f"{letter}2:{letter}{last_row}",
            ColorScaleRule(
                start_type="num", start_value=80, start_color="F8696B",
                mid_type="num", mid_value=90, mid_color="FFEB84",
                end_type="num", end_value=100, end_color="63BE7B",
            ),
        )

    summary_row = last_row + 2
    ws.cell(row=summary_row, column=1, value="Итого по видимым строкам:")
    ws.cell(row=summary_row, column=1).font = Font(bold=True)

    ma_row = summary_row + 1
    ws.cell(row=ma_row, column=1, value="Точность (среднее), %:")
    ws.cell(row=ma_row, column=1).font = Font(bold=True, color="4472C4")

    st_row = summary_row + 2
    ws.cell(row=st_row, column=1, value="Стабильность, %:")
    ws.cell(row=st_row, column=1).font = Font(bold=True, color="4472C4")

    qi_row = summary_row + 3
    ws.cell(row=qi_row, column=1, value="Качество, %:")
    ws.cell(row=qi_row, column=1).font = Font(bold=True, color="4472C4")

    fact_ci = col_indices.get("fact_value")
    err_ci = col_indices.get("abs_error")
    acc_ci = col_indices.get("accuracy_pct")
    fact_fts_ci = col_indices.get("fact_fts")

    for ci, series_name, fmt in [
        (fact_ci, "fact_value", '#,##0'),
        (err_ci, "abs_error", '#,##0'),
        (fact_fts_ci, "fact_fts", '#,##0.00'),
    ]:
        if ci and series_name in df.columns:
            ws.cell(row=summary_row, column=ci, value=float(df[series_name].sum()))
            ws.cell(row=summary_row, column=ci).font = Font(bold=True)
            ws.cell(row=summary_row, column=ci).number_format = fmt

    if acc_ci:
        m_acc = calc_mean_accuracy(df)
        ws.cell(row=summary_row, column=acc_ci, value=m_acc)
        ws.cell(row=summary_row, column=acc_ci).font = Font(bold=True)

        ws.cell(row=ma_row, column=acc_ci, value=m_acc)
        ws.cell(row=ma_row, column=acc_ci).font = Font(bold=True, color="4472C4", size=14)

        stab = calc_stability(df)
        ws.cell(row=st_row, column=acc_ci, value=stab)
        ws.cell(row=st_row, column=acc_ci).font = Font(bold=True, color="4472C4", size=14)

        qi = calc_quality_index(m_acc, stab)
        ws.cell(row=qi_row, column=acc_ci, value=qi)
        ws.cell(row=qi_row, column=acc_ci).font = Font(bold=True, color="4472C4", size=14)

    auto_column_width(ws)

    return {"last_row": last_row, "col_indices": col_indices}


# ---------------------------------------------------------------------------
#  Лист «Оценка прогноза»
# ---------------------------------------------------------------------------


def build_dashboard_sheet(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Оценка прогноза")

    m_acc = calc_mean_accuracy(df)
    stab = calc_stability(df)
    qi = calc_quality_index(m_acc, stab)
    total_fact = int(df["fact_value"].sum())

    ws.merge_cells("A1:L1")
    ws.cell(row=1, column=1, value="Оценка качества прогноза (по средней точности)")
    ws.cell(row=1, column=1).font = Font(bold=True, size=16)
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center")

    def _fill_for(val: float) -> PatternFill:
        if val >= 90:
            return GOOD_FILL
        if val >= 80:
            return NEUTRAL_FILL
        return BAD_FILL

    write_kpi_card(ws, *KPI_CELLS["mean_accuracy"],
                   "Точность", f"{m_acc:.1f}%", _fill_for(m_acc))
    write_kpi_card(ws, *KPI_CELLS["stability"],
                   "Стабильность", f"{stab:.1f}%", _fill_for(stab))
    write_kpi_card(ws, *KPI_CELLS["quality_index"],
                   "Качество", f"{qi:.1f}%", _fill_for(qi))
    write_kpi_card(ws, *KPI_CELLS["total_fact"],
                   "Факт\nвсего", f"{total_fact:,}", GOOD_FILL)
    write_kpi_card(ws, *KPI_CELLS["total_pred"],
                   "Прогноз\nвсего", f"{int(df['fact_predict'].sum()):,}", GOOD_FILL)
    write_kpi_card(ws, *KPI_CELLS["visible_rows"],
                   "Кол-во\nстрок", len(df), GOOD_FILL)

    ws.row_dimensions[3].height = 50
    ws.row_dimensions[4].height = 55

    ws.cell(row=2, column=1, value=(
        "Метрики пересчитываются автоматически при фильтрации на листе «Данные». "
        "Если нужно пересчитать вручную: Alt+F8 → RecalcMetrics → Выполнить."
    ))
    ws.cell(row=2, column=1).font = Font(italic=True, size=10, color="555555")
    ws.merge_cells("A2:L2")

    ws.cell(row=6, column=1, value="Как считаются показатели:").font = Font(bold=True, size=12)
    ws.cell(row=6, column=9, value="Формулы excel")
    formulas_text = [
        ("Точность",
         "Среднее арифметическое «Точности прогноза» по всем видимым строкам. Все строки равны.",
         "Формула 1"),
        ("Стабильность",
         "(1 - CV) * 100%, где CV - отношение разброса к среднему. Чем меньше разброс, тем стабильнее.",
         "Формула 2"),
        ("Качество",
         "Гармоническое среднее Точности и Стабильности. Провал любого показателя снижает рейтинг.",
         "Формула 3"),
    ]
    for i, (name, desc, formula_label) in enumerate(formulas_text):
        row = 7 + i * 2  # 7, 9, 11 — с пустой строкой между блоками
        ws.cell(row=row, column=1, value=name).font = Font(bold=True, size=10)
        ws.cell(row=row, column=3, value=desc).font = Font(size=10, color="555555")
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=8)
        ws.cell(row=row, column=9, value=formula_label)

    top_section_row = 14
    ws.cell(row=top_section_row, column=1,
            value="Топ-10 моделей (resist_id) с ХУДШИМ качеством (крупные)")
    ws.cell(row=top_section_row, column=1).font = Font(bold=True, size=12, color="C00000")
    ws.merge_cells(start_row=top_section_row, start_column=1,
                   end_row=top_section_row, end_column=9)

    div_stats = _division_stats(df)
    worst = div_stats.nsmallest(10, "quality_index")
    _write_div_table(ws, top_section_row + 1, worst, is_worst=True)

    best_section_row = top_section_row + len(worst) + 3
    ws.cell(row=best_section_row, column=1,
            value="Топ-10 моделей (resist_id) с ЛУЧШИМ качеством (крупные)")
    ws.cell(row=best_section_row, column=1).font = Font(bold=True, size=12, color="007030")
    ws.merge_cells(start_row=best_section_row, start_column=1,
                   end_row=best_section_row, end_column=9)
    best = div_stats.nlargest(10, "quality_index")
    _write_div_table(ws, best_section_row + 1, best, is_worst=False)

    scatter_row = best_section_row + len(best) + 3
    ws.cell(row=scatter_row, column=1,
            value="Точность, стабильность и качество по моделям (resist_id)")
    ws.cell(row=scatter_row, column=1).font = Font(bold=True, size=12)
    ws.merge_cells(start_row=scatter_row, start_column=1,
                   end_row=scatter_row, end_column=9)

    scatter_headers = [
        "resist_id", "Подразделение", "Точность, %", "Стабильность, %",
        "Качество, %", "Факт, шт.",
    ]
    for ci, h in enumerate(scatter_headers, 1):
        ws.cell(row=scatter_row + 1, column=ci, value=h)
    style_header_row(ws, scatter_row + 1, len(scatter_headers))

    for ri, (_, row) in enumerate(div_stats.iterrows(), scatter_row + 2):
        ws.cell(row=ri, column=1, value=row["resist_id"])
        ws.cell(row=ri, column=2, value=row["division_title"])
        ws.cell(row=ri, column=3, value=row["mean_accuracy"])
        ws.cell(row=ri, column=4, value=row["stability"])
        ws.cell(row=ri, column=5, value=row["quality_index"])
        ws.cell(row=ri, column=6, value=int(row["fact_sum"]))

    for col in range(1, 13):
        ws.column_dimensions[get_column_letter(col)].width = 18


def _division_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Агрегация метрик по resist_id (названия подразделений менялись со временем)."""
    groups = df.groupby("resist_id", dropna=True)
    rows = []
    for rid, grp in groups:
        m_acc = calc_mean_accuracy(grp)
        stab = calc_stability(grp)
        qi = calc_quality_index(m_acc, stab)
        div_titles = grp["division_title"].dropna() if "division_title" in grp.columns else pd.Series(dtype=object)
        div_title = div_titles.iloc[0] if len(div_titles) > 0 else ""
        div_title = div_title if pd.notna(div_title) and str(div_title).strip() else "(не указано)"
        rows.append({
            "resist_id": rid,
            "division_title": div_title,
            "fact_sum": grp["fact_value"].sum(),
            "pred_sum": grp["fact_predict"].sum(),
            "error_sum": grp["abs_error"].sum(),
            "mean_accuracy": m_acc,
            "stability": stab,
            "quality_index": qi,
        })
    return pd.DataFrame(rows)


def _write_div_table(ws, start_row: int, data: pd.DataFrame, is_worst: bool) -> None:
    headers = [
        "resist_id", "Подразделение", "Факт, шт.", "Прогноз, шт.", "Ошибка, шт.",
        "Точность, %", "Стабильность, %", "Качество, %",
    ]
    for ci, h in enumerate(headers, 1):
        ws.cell(row=start_row, column=ci, value=h)
    style_header_row(ws, start_row, len(headers))

    fill = BAD_FILL if is_worst else GOOD_FILL
    for ri, (_, row) in enumerate(data.iterrows(), start_row + 1):
        ws.cell(row=ri, column=1, value=row["resist_id"])
        ws.cell(row=ri, column=2, value=row["division_title"])
        ws.cell(row=ri, column=3, value=int(row["fact_sum"]))
        ws.cell(row=ri, column=4, value=int(row["pred_sum"]))
        ws.cell(row=ri, column=5, value=int(row["error_sum"]))
        ws.cell(row=ri, column=6, value=row["mean_accuracy"])
        ws.cell(row=ri, column=7, value=row["stability"])
        ws.cell(row=ri, column=8, value=row["quality_index"])
        for ci in range(1, 9):
            ws.cell(row=ri, column=ci).border = THIN_BORDER
        ws.cell(row=ri, column=6).fill = fill
        ws.cell(row=ri, column=6).number_format = '0.00'
        ws.cell(row=ri, column=7).number_format = '0.00'
        ws.cell(row=ri, column=8).number_format = '0.00'


# ---------------------------------------------------------------------------
#  Лист «Тепловая карта»
# ---------------------------------------------------------------------------


def build_heatmap_sheet(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Тепловая карта")

    MONTH_NAMES = [
        "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
        "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
    ]

    months_present = sorted(df["month"].unique())
    resist_ids = sorted(
        [x for x in df["resist_id"].unique() if pd.notna(x)],
        key=lambda x: (0, x) if isinstance(x, (int, float)) else (1, str(x)),
    )

    # resist_id | division_title | months
    last_month_col = len(months_present) + 2

    ws.cell(row=1, column=1,
            value="Тепловая карта: Качество (%) по моделям (resist_id) и месяцам")
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, start_column=1, end_row=1,
                   end_column=last_month_col)

    ws.cell(row=3, column=1, value="resist_id")
    ws.cell(row=3, column=2, value="Подразделение")
    for mi, m in enumerate(months_present, 3):
        label = MONTH_NAMES[m - 1] if 1 <= m <= 12 else str(m)
        ws.cell(row=3, column=mi, value=label)
    style_header_row(ws, 3, last_month_col)

    for di, rid in enumerate(resist_ids, 4):
        slice_any = df[df["resist_id"] == rid]
        div_titles = slice_any["division_title"].dropna()
        div_title = div_titles.iloc[0] if len(div_titles) > 0 else "(не указано)"
        div_title = div_title if pd.notna(div_title) and str(div_title).strip() else "(не указано)"

        ws.cell(row=di, column=1, value=rid)
        ws.cell(row=di, column=1).border = THIN_BORDER
        ws.cell(row=di, column=2, value=div_title)
        ws.cell(row=di, column=2).border = THIN_BORDER

        for mi, m in enumerate(months_present, 3):
            slice_df = df[(df["resist_id"] == rid) & (df["month"] == m)]
            if slice_df.empty or slice_df["fact_value"].sum() == 0:
                ws.cell(row=di, column=mi, value="—")
                ws.cell(row=di, column=mi).alignment = Alignment(horizontal="center")
            else:
                m_acc = calc_mean_accuracy(slice_df)
                stab = calc_stability(slice_df)
                qi = calc_quality_index(m_acc, stab)
                ws.cell(row=di, column=mi, value=qi)
                ws.cell(row=di, column=mi).number_format = '0.0'
            ws.cell(row=di, column=mi).border = THIN_BORDER

    last_data_row = 3 + len(resist_ids)
    for mi in range(3, last_month_col + 1):
        col_letter = get_column_letter(mi)
        rng = f"{col_letter}4:{col_letter}{last_data_row}"
        ws.conditional_formatting.add(
            rng,
            ColorScaleRule(
                start_type="num", start_value=80, start_color="F8696B",
                mid_type="num", mid_value=90, mid_color="FFEB84",
                end_type="num", end_value=100, end_color="63BE7B",
            ),
        )

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 35
    for ci in range(3, last_month_col + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 10

    total_row = last_data_row + 1
    ws.cell(row=total_row, column=1, value="ИТОГО")
    ws.cell(row=total_row, column=1).font = Font(bold=True, size=12)
    ws.cell(row=total_row, column=1).border = THIN_BORDER
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=2)

    for mi, m in enumerate(months_present, 3):
        slice_df = df[df["month"] == m]
        if slice_df.empty or slice_df["fact_value"].sum() == 0:
            ws.cell(row=total_row, column=mi, value="—")
        else:
            m_acc = calc_mean_accuracy(slice_df)
            stab = calc_stability(slice_df)
            qi = calc_quality_index(m_acc, stab)
            ws.cell(row=total_row, column=mi, value=qi)
            ws.cell(row=total_row, column=mi).number_format = '0.0'
        ws.cell(row=total_row, column=mi).border = THIN_BORDER
        ws.cell(row=total_row, column=mi).font = Font(bold=True)

    legend_row = total_row + 2
    ws.cell(row=legend_row, column=1, value="Легенда:").font = Font(bold=True)
    ws.cell(row=legend_row + 1, column=1, value="Красный — качество < 80%")
    ws.cell(row=legend_row + 1, column=1).font = Font(color="C00000")
    ws.cell(row=legend_row + 2, column=1, value="Жёлтый — качество 80-90%")
    ws.cell(row=legend_row + 2, column=1).font = Font(color="BF8F00")
    ws.cell(row=legend_row + 3, column=1, value="Зелёный — качество > 90%")
    ws.cell(row=legend_row + 3, column=1).font = Font(color="007030")


# ---------------------------------------------------------------------------
#  VBA-инструкция
# ---------------------------------------------------------------------------


def _save_vba_instructions(xlsx_path: Path, vba_code: str) -> None:
    vba_file = xlsx_path.with_suffix(".vba.txt")
    instructions = (
        "=== ИНСТРУКЦИЯ ПО УСТАНОВКЕ МАКРОСА ===\n\n"
        "Файл дашборда сохранён в формате .xlsx и открывается без ошибок.\n"
        "Чтобы метрики пересчитывались при фильтрации автоматически,\n"
        "выполните следующие шаги ОДИН РАЗ:\n\n"
        "1. Откройте .xlsx файл в Excel.\n"
        "2. Файл → Сохранить как → выберите тип «Книга Excel с поддержкой\n"
        "   макросов (*.xlsm)». Сохраните.\n"
        "3. Нажмите Alt+F11 (откроется редактор VBA).\n"
        "4. В левой панели найдите «ЭтаКнига» (ThisWorkbook), дважды кликните.\n"
        "5. Вставьте код из секции «КОД ДЛЯ ЭтаКнига» ниже.\n"
        "6. В меню Insert → Module. Вставьте код из секции «КОД ДЛЯ МОДУЛЯ».\n"
        "7. Закройте редактор VBA (Alt+Q), сохраните файл (Ctrl+S).\n\n"
        "После этого при каждом изменении фильтра на листе «Данные» все метрики\n"
        "на листе «Оценка прогноза» пересчитаются автоматически.\n"
        "Ручной запуск: Alt+F8 → RecalcMetrics → Выполнить.\n\n"
        "=== КОД ДЛЯ «ЭтаКнига» (ThisWorkbook) ===\n\n"
        "Private Sub Workbook_SheetCalculate(ByVal Sh As Object)\n"
        "    If Sh.Index = 1 Then\n"
        "        RecalcMetrics\n"
        "    End If\n"
        "End Sub\n\n"
        "=== КОД ДЛЯ МОДУЛЯ (Insert → Module) ===\n\n"
        f"{vba_code}\n"
    )
    vba_file.write_text(instructions, encoding="utf-8")
    print(f"VBA-инструкция сохранена: {vba_file}")


# ---------------------------------------------------------------------------
#  Главная функция
# ---------------------------------------------------------------------------


def build_dashboard(
    input_path: str | Path,
    output_path: str | Path | None = None,
    forecast_col: str = "fact_predict",
) -> Path:
    df_raw = load_dataframe(input_path)
    df = prepare_dataframe(df_raw, forecast_col=forecast_col)

    wb = Workbook()
    wb.remove(wb.active)

    data_meta = build_data_sheet(wb, df)
    build_dashboard_sheet(wb, df)
    build_heatmap_sheet(wb, df)

    if output_path is None:
        out_dir = Path(input_path).parent
        output_path = out_dir / "forecast_dashboard_simple.xlsx"
    else:
        output_path = Path(output_path)
        if output_path.suffix not in (".xlsx", ".xls"):
            output_path = output_path.with_suffix(".xlsx")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))

    vba_code = _build_vba_code(
        last_data_row=data_meta["last_row"],
        col_indices=data_meta["col_indices"],
    )
    _save_vba_instructions(output_path, vba_code)

    print(f"Дашборд сохранён: {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Сборка Excel-дашборда (по средней точности, без взвешивания)"
    )
    parser.add_argument(
        "--input", "-i",
        default="data/processed/predictions_history.xlsx",
        help="Путь к входному файлу xlsx/csv",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Путь к выходному xlsx (default: forecast_dashboard_simple.xlsx)",
    )
    parser.add_argument(
        "--forecast-col", "-f",
        default="fact_predict",
        help="Колонка с прогнозом для оценки (default: fact_predict)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Файл не найден: {input_path}", file=sys.stderr)
        sys.exit(1)

    build_dashboard(input_path, args.output, forecast_col=args.forecast_col)


if __name__ == "__main__":
    main()
