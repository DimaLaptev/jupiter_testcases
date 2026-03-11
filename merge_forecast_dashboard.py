"""
Скрипт добавляет в файл отчёта (dashboard) данные по другому прогнозу.

Читает два Excel-дашборда, объединяет их: в базовый файл добавляются колонки
прогноза «Комби» из второго файла. KPI, топ-10 и тепловая карта на листе
«Оценка прогноза» пересчитываются по новому (комбинированному) прогнозу.

Пути к файлам задаются в константах FILE_BASE и FILE_COMB в начале скрипта.

Использование:
    python merge_forecast_dashboard.py
    python merge_forecast_dashboard.py --output data/processed/forecast_dashboard_merged.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
#  Пути к файлам (задаются пользователем)
# ---------------------------------------------------------------------------

FILE_BASE = Path("data/processed/forecast_dashboard_xgb_log1p.xlsx")
FILE_COMB = Path("data/processed/forecast_dashboard_combined.xlsx")

# ---------------------------------------------------------------------------
#  Стили (соответствуют build_metrics_dashboard_simple)
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

KPI_CELLS = {
    "mean_accuracy": (3, 1),
    "stability": (3, 3),
    "quality_index": (3, 5),
    "total_fact": (3, 7),
    "total_pred": (3, 9),
    "visible_rows": (3, 11),
}

# Маппинг заголовков Excel -> внутренние имена колонок
HEADER_TO_COL = {
    "модель (resist_id)": "resist_id",
    "подразделение (division)": "division_title",
    "id операции (operation_id)": "operation_id",
    "дата (date)": "date",
    "месяц (month)": "month",
    "год (year)": "year",
    "факт, шт. (fact_value)": "fact_value",
    "прогноз, шт. (fact_predict)": "fact_predict",
    "ошибка, шт. (abs_error)": "abs_error",
    "точность прогноза, % (forecast accuracy)": "accuracy_pct",
    "факт, пше (fact_fts)": "fact_fts",
}


def _normalize_header(h: str) -> str:
    return str(h).strip().lower() if pd.notna(h) else ""


def _read_data_sheet(path: Path) -> pd.DataFrame:
    """Читает лист «Данные» из dashboard xlsx и нормализует имена колонок."""
    df = pd.read_excel(path, sheet_name="Данные")
    rename = {}
    for c in df.columns:
        norm = _normalize_header(c)
        if norm in HEADER_TO_COL:
            rename[c] = HEADER_TO_COL[norm]
    df = df.rename(columns=rename)
    return df


def _read_input_file(path: Path) -> pd.DataFrame:
    """Читает forecast_input_*.xlsx и подготавливает (abs_error, accuracy_pct)."""
    from build_metrics_dashboard_simple import load_dataframe, prepare_dataframe
    df_raw = load_dataframe(path)
    return prepare_dataframe(df_raw, forecast_col="fact_predict")


def _load_combi_data(path: Path) -> pd.DataFrame:
    """Загружает данные комби-прогноза из dashboard или input файла."""
    if path.suffix not in (".xlsx", ".xls"):
        raise ValueError(f"Неподдерживаемый формат: {path.suffix}")
    wb = load_workbook(path, read_only=True, data_only=True)
    if "Данные" in wb.sheetnames:
        wb.close()
        return _read_data_sheet(path)
    wb.close()
    return _read_input_file(path)


def _merge_key(row) -> tuple:
    rid = row.get("resist_id", row.get("resist_id"))
    oid = row.get("operation_id", "")
    d = row.get("date")
    if pd.isna(d):
        d = (row.get("year", ""), row.get("month", ""))
    return (rid, oid, d)


def _calc_combi_fts(df: pd.DataFrame, combi_predict: pd.Series) -> pd.Series:
    """ПШЕ нового прогноза: combi_predict * (fact_fts / fact_value) при fact_value != 0."""
    fv = pd.to_numeric(df["fact_value"], errors="coerce").fillna(0)
    fts = pd.to_numeric(df["fact_fts"], errors="coerce").fillna(0)
    pred = pd.to_numeric(combi_predict, errors="coerce").fillna(0)
    ratio = np.where(fv > 0, fts / fv, 0)
    return pred * ratio


def merge_and_add_columns(df_base: pd.DataFrame, df_comb: pd.DataFrame) -> pd.DataFrame:
    """Объединяет данные и добавляет колонки Комби."""
    df_base = df_base.copy()
    df_comb = df_comb.copy()

    for df in (df_base, df_comb):
        df["_merge_key"] = list(zip(
            df["resist_id"].astype(str),
            df["operation_id"].astype(str),
            pd.to_datetime(df["date"], errors="coerce").astype(str),
        ))

    combi_cols = {
        "fact_predict": "combi_predict",
        "abs_error": "combi_abs_error",
        "accuracy_pct": "combi_accuracy_pct",
    }
    merge_df = df_comb[["_merge_key"] + list(combi_cols.keys())].copy()
    merge_df = merge_df.rename(columns=combi_cols)

    df_base = df_base.merge(merge_df, on="_merge_key", how="left", suffixes=("", "_y"))
    df_base = df_base.drop(columns=["_merge_key"], errors="ignore")

    df_base["combi_fact_fts"] = _calc_combi_fts(
        df_base,
        df_base["combi_predict"].fillna(df_base.get("fact_predict", 0)),
    )

    return df_base


def _find_col_index(headers: list[str], fragment: str) -> int:
    """Находит индекс колонки по фрагменту названия (регистронезависимо)."""
    frag = fragment.lower()
    for i, h in enumerate(headers):
        if frag in str(h).lower():
            return i + 1
    return -1


def calc_mean_accuracy(df: pd.DataFrame, acc_col: str = "accuracy_pct") -> float:
    if df.empty or acc_col not in df.columns:
        return 0.0
    return round(df[acc_col].mean(), 2)


def calc_stability(df: pd.DataFrame, acc_col: str = "accuracy_pct") -> float:
    if df.empty or acc_col not in df.columns:
        return 0.0
    mean_acc = df[acc_col].mean()
    if mean_acc == 0 or pd.isna(mean_acc):
        return 0.0
    cv = df[acc_col].std(ddof=0) / mean_acc
    return round(max(0.0, (1 - cv)) * 100, 2)


def calc_quality_index(accuracy: float, stability: float) -> float:
    if accuracy + stability == 0:
        return 0.0
    return round(2 * accuracy * stability / (accuracy + stability), 2)


def _division_stats(df: pd.DataFrame, pred_col: str, err_col: str, acc_col: str) -> pd.DataFrame:
    """Агрегация метрик по resist_id для заданных колонок прогноза."""
    rows = []
    for rid, grp in df.groupby("resist_id", dropna=True):
        m_acc = calc_mean_accuracy(grp, acc_col)
        stab = calc_stability(grp, acc_col)
        qi = calc_quality_index(m_acc, stab)
        div_titles = grp["division_title"].dropna() if "division_title" in grp.columns else pd.Series(dtype=object)
        div_title = div_titles.iloc[0] if len(div_titles) > 0 else ""
        div_title = div_title if pd.notna(div_title) and str(div_title).strip() else "(не указано)"
        rows.append({
            "resist_id": rid,
            "division_title": div_title,
            "fact_sum": grp["fact_value"].sum(),
            "pred_sum": grp[pred_col].sum(),
            "error_sum": grp[err_col].sum(),
            "mean_accuracy": m_acc,
            "stability": stab,
            "quality_index": qi,
        })
    return pd.DataFrame(rows)


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


def style_header_row(ws, row: int, max_col: int) -> None:
    for col in range(1, max_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER


def _rebuild_dashboard_sheet(ws, df_comb: pd.DataFrame) -> None:
    """Перестраивает лист «Оценка прогноза» по данным комби-прогноза."""
    m_acc = calc_mean_accuracy(df_comb, "combi_accuracy_pct")
    stab = calc_stability(df_comb, "combi_accuracy_pct")
    qi = calc_quality_index(m_acc, stab)
    total_fact = int(df_comb["fact_value"].sum())
    total_pred = int(df_comb["combi_predict"].sum())

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
                   "Прогноз\nвсего", f"{total_pred:,}", GOOD_FILL)
    write_kpi_card(ws, *KPI_CELLS["visible_rows"],
                   "Кол-во\nстрок", len(df_comb), GOOD_FILL)

    ws.row_dimensions[3].height = 50
    ws.row_dimensions[4].height = 55

    ws.cell(row=2, column=1, value=(
        "Метрики рассчитаны по прогнозу «Комби». "
        "Колонки Комби на листе «Данные» добавлены для сравнения."
    ))
    ws.cell(row=2, column=1).font = Font(italic=True, size=10, color="555555")
    ws.merge_cells("A2:L2")

    div_stats = _division_stats(
        df_comb, "combi_predict", "combi_abs_error", "combi_accuracy_pct"
    )
    worst = div_stats.nsmallest(10, "quality_index")
    best = div_stats.nlargest(10, "quality_index")

    top_section_row = 14
    ws.cell(row=top_section_row, column=1,
            value="Топ-10 моделей (resist_id) с ХУДШИМ качеством (Комби)")
    ws.cell(row=top_section_row, column=1).font = Font(bold=True, size=12, color="C00000")
    ws.merge_cells(start_row=top_section_row, start_column=1,
                   end_row=top_section_row, end_column=9)
    _write_div_table(ws, top_section_row + 1, worst, is_worst=True)

    best_section_row = top_section_row + len(worst) + 3
    ws.cell(row=best_section_row, column=1,
            value="Топ-10 моделей (resist_id) с ЛУЧШИМ качеством (Комби)")
    ws.cell(row=best_section_row, column=1).font = Font(bold=True, size=12, color="007030")
    ws.merge_cells(start_row=best_section_row, start_column=1,
                   end_row=best_section_row, end_column=9)
    _write_div_table(ws, best_section_row + 1, best, is_worst=False)

    scatter_row = best_section_row + len(best) + 3
    ws.cell(row=scatter_row, column=1,
            value="Точность, стабильность и качество по моделям (resist_id)")
    ws.cell(row=scatter_row, column=1).font = Font(bold=True, size=12)
    ws.merge_cells(start_row=scatter_row, start_column=1,
                   end_row=scatter_row, end_column=10)

    scatter_headers = [
        "resist_id", "Подразделение",
        "Точность, %", "Стабильность, %", "Качество, %",
        "Комби Точность, %", "Комби Стабильность, %", "Комби Качество, %",
        "Факт, шт.",
    ]
    for ci, h in enumerate(scatter_headers, 1):
        ws.cell(row=scatter_row + 1, column=ci, value=h)
    style_header_row(ws, scatter_row + 1, len(scatter_headers))

    div_stats_base = _division_stats(
        df_comb, "fact_predict", "abs_error", "accuracy_pct"
    ) if "abs_error" in df_comb.columns and "accuracy_pct" in df_comb.columns else pd.DataFrame()
    div_stats_comb = _division_stats(
        df_comb, "combi_predict", "combi_abs_error", "combi_accuracy_pct"
    )

    for row_idx, (_, r) in enumerate(div_stats_comb.iterrows()):
        rid = r["resist_id"]
        ri = scatter_row + 2 + row_idx
        row_base = div_stats_base[div_stats_base["resist_id"] == rid] if not div_stats_base.empty else pd.DataFrame()
        ws.cell(row=ri, column=1, value=r["resist_id"])
        ws.cell(row=ri, column=2, value=r["division_title"])
        if not row_base.empty:
            rb = row_base.iloc[0]
            ws.cell(row=ri, column=3, value=rb["mean_accuracy"])
            ws.cell(row=ri, column=4, value=rb["stability"])
            ws.cell(row=ri, column=5, value=rb["quality_index"])
        ws.cell(row=ri, column=6, value=r["mean_accuracy"])
        ws.cell(row=ri, column=7, value=r["stability"])
        ws.cell(row=ri, column=8, value=r["quality_index"])
        ws.cell(row=ri, column=9, value=int(r["fact_sum"]))
        for ci in range(1, 10):
            ws.cell(row=ri, column=ci).border = THIN_BORDER

    for col in range(1, 13):
        ws.column_dimensions[get_column_letter(col)].width = 18


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


def _rebuild_heatmap_sheet(ws, df_comb: pd.DataFrame) -> None:
    """Перестраивает тепловую карту по комби-прогнозу."""
    from build_metrics_dashboard_simple import (
        build_heatmap_sheet as build_heatmap,
        calc_mean_accuracy,
        calc_stability,
        calc_quality_index,
    )
    df_for_heatmap = df_comb.copy()
    df_for_heatmap["fact_predict"] = df_comb["combi_predict"]
    df_for_heatmap["abs_error"] = (df_for_heatmap["fact_value"] - df_for_heatmap["fact_predict"]).abs()
    acc = np.where(
        df_for_heatmap["fact_value"] == 0,
        np.where(df_for_heatmap["fact_predict"] == 0, 100.0, 0.0),
        np.clip(100.0 - df_for_heatmap["abs_error"] / df_for_heatmap["fact_value"] * 100.0, 0, 100),
    )
    df_for_heatmap["accuracy_pct"] = np.round(acc, 2)

    wb = ws.parent
    build_heatmap(wb, df_for_heatmap)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Добавление прогноза «Комби» в файл отчёта дашборда"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Путь к выходному xlsx (по умолчанию: forecast_dashboard_merged.xlsx)",
    )
    args = parser.parse_args()

    if not FILE_BASE.exists():
        print(f"Базовый файл не найден: {FILE_BASE}", file=sys.stderr)
        sys.exit(1)
    if not FILE_COMB.exists():
        print(f"Файл комби-прогноза не найден: {FILE_COMB}", file=sys.stderr)
        sys.exit(1)

    print("Загрузка данных...")
    df_base = _read_data_sheet(FILE_BASE)
    df_comb_raw = _load_combi_data(FILE_COMB)

    print("Объединение и добавление колонок Комби...")
    df_merged = merge_and_add_columns(df_base, df_comb_raw)
    if df_merged["combi_predict"].isna().all():
        print("Предупреждение: совпадений строк не найдено. Проверьте ключи слияния.", file=sys.stderr)

    output_path = Path(args.output) if args.output else FILE_BASE.parent / "forecast_dashboard_merged.xlsx"
    if output_path.suffix not in (".xlsx", ".xls"):
        output_path = output_path.with_suffix(".xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Модификация листа «Данные»...")
    wb = load_workbook(FILE_BASE)
    ws_data = wb["Данные"]

    headers = [ws_data.cell(row=1, column=c).value for c in range(1, ws_data.max_column + 1)]

    col_idx_pred = _find_col_index(headers, "Прогноз")
    col_idx_err = _find_col_index(headers, "Ошибка")
    col_idx_acc = _find_col_index(headers, "Точность прогноза")
    col_idx_fts = _find_col_index(headers, "Факт, ПШЕ")

    def _ins(col: int, new_h: list, key: str) -> None:
        if col < 0:
            return
        ws_data.insert_cols(col + 1, len(new_h))
        for i, h in enumerate(new_h):
            c = col + 1 + i
            ws_data.cell(row=1, column=c, value=h)
            ws_data.cell(row=1, column=c).fill = HEADER_FILL
            ws_data.cell(row=1, column=c).font = HEADER_FONT
            for r in range(2, len(df_merged) + 2):
                ws_data.cell(row=r, column=c, value=df_merged.iloc[r - 2][key])

    ins_col = col_idx_pred
    if ins_col > 0:
        ws_data.insert_cols(ins_col + 1, 1)
        ws_data.cell(row=1, column=ins_col + 1, value="Комби, шт")
        ws_data.cell(row=1, column=ins_col + 1).fill = HEADER_FILL
        ws_data.cell(row=1, column=ins_col + 1).font = HEADER_FONT
        for r in range(2, len(df_merged) + 2):
            ws_data.cell(row=r, column=ins_col + 1, value=df_merged.iloc[r - 2]["combi_predict"])
        col_idx_err = col_idx_err + 1 if col_idx_err >= ins_col else col_idx_err
        col_idx_acc = col_idx_acc + 1 if col_idx_acc >= ins_col else col_idx_acc
        col_idx_fts = col_idx_fts + 1 if col_idx_fts >= ins_col else col_idx_fts

    ins_col = col_idx_err
    if ins_col > 0:
        ws_data.insert_cols(ins_col + 1, 1)
        ws_data.cell(row=1, column=ins_col + 1, value="Комби Ошибка, шт")
        ws_data.cell(row=1, column=ins_col + 1).fill = HEADER_FILL
        ws_data.cell(row=1, column=ins_col + 1).font = HEADER_FONT
        for r in range(2, len(df_merged) + 2):
            ws_data.cell(row=r, column=ins_col + 1, value=df_merged.iloc[r - 2]["combi_abs_error"])
        col_idx_acc = col_idx_acc + 1 if col_idx_acc >= ins_col else col_idx_acc
        col_idx_fts = col_idx_fts + 1 if col_idx_fts >= ins_col else col_idx_fts

    ins_col = col_idx_acc
    if ins_col > 0:
        ws_data.insert_cols(ins_col + 1, 1)
        ws_data.cell(row=1, column=ins_col + 1, value="Комби Точность, %")
        ws_data.cell(row=1, column=ins_col + 1).fill = HEADER_FILL
        ws_data.cell(row=1, column=ins_col + 1).font = HEADER_FONT
        for r in range(2, len(df_merged) + 2):
            ws_data.cell(row=r, column=ins_col + 1, value=df_merged.iloc[r - 2]["combi_accuracy_pct"])
        col_idx_fts = col_idx_fts + 1 if col_idx_fts >= ins_col else col_idx_fts

    ins_col = col_idx_fts
    if ins_col > 0:
        ws_data.insert_cols(ins_col + 1, 1)
        ws_data.cell(row=1, column=ins_col + 1, value="Комби Факт, ПШЕ")
        ws_data.cell(row=1, column=ins_col + 1).fill = HEADER_FILL
        ws_data.cell(row=1, column=ins_col + 1).font = HEADER_FONT
        for r in range(2, len(df_merged) + 2):
            ws_data.cell(row=r, column=ins_col + 1, value=df_merged.iloc[r - 2]["combi_fact_fts"])

    last_col = get_column_letter(ws_data.max_column)
    ws_data.auto_filter.ref = f"A1:{last_col}{ws_data.max_row}"

    print("Пересборка листа «Оценка прогноза» по комби-прогнозу...")
    ws_dash = wb["Оценка прогноза"]
    for row in range(1, ws_dash.max_row + 1):
        for col in range(1, ws_dash.max_column + 1):
            ws_dash.cell(row=row, column=col).value = None
    _rebuild_dashboard_sheet(ws_dash, df_merged)

    print("Пересборка листа «Тепловая карта» по комби-прогнозу...")
    wb.remove(wb["Тепловая карта"])
    from build_metrics_dashboard_simple import build_heatmap_sheet
    df_heatmap = df_merged.copy()
    df_heatmap["fact_predict"] = df_merged["combi_predict"]
    df_heatmap["abs_error"] = (df_heatmap["fact_value"] - df_heatmap["fact_predict"]).abs()
    acc = np.where(
        df_heatmap["fact_value"] == 0,
        np.where(df_heatmap["fact_predict"] == 0, 100.0, 0.0),
        np.clip(100.0 - df_heatmap["abs_error"] / df_heatmap["fact_value"] * 100.0, 0, 100),
    )
    df_heatmap["accuracy_pct"] = np.round(acc, 2)
    build_heatmap_sheet(wb, df_heatmap)

    wb.save(str(output_path))
    print(f"Дашборд сохранён: {output_path}")


if __name__ == "__main__":
    main()
