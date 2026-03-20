"""
Сквозная аналитика по листам «{RESIST_ID} Итог» в model_comparison.xlsx:
топ-20 / топ-5, варианты и конфиги «ни разу», табличные наборы признаков.
Добавляет листы «Аналитика таблицы» и «Аналитика диаграммы» в тот же файл.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.utils.dataframe import dataframe_to_rows

REQUIRED_COLUMNS = [
    "Комбинация",
    "Конфигурация",
    "Набор признаков",
    "Качество, %",
    "Тип",
]

SHEET_SUFFIX = " Итог"
SHEET_TABLES = "Аналитика таблицы"
SHEET_CHARTS = "Аналитика диаграммы"
TOP_20 = 20
TOP_5 = 5
CHART_TOP_N = 15

# Per-series строки в экспорте (em dash U+2014)
DASH_FS = "\u2014"


def _default_xlsx_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "processed" / "model_comparison.xlsx"


def _is_tabular_row(fs: object) -> bool:
    if fs is None or (isinstance(fs, float) and pd.isna(fs)):
        return False
    s = str(fs).strip()
    return s != DASH_FS and s != "-" and s != ""


def load_itog_sheets(xlsx_path: Path) -> tuple[list[str], dict[str, pd.DataFrame]]:
    xl = pd.ExcelFile(xlsx_path, engine="openpyxl")
    itog_names = sorted(n for n in xl.sheet_names if n.endswith(SHEET_SUFFIX))
    if not itog_names:
        raise SystemExit(
            f"Не найдено листов с суффиксом «{SHEET_SUFFIX}» в {xlsx_path}"
        )
    frames: dict[str, pd.DataFrame] = {}
    for name in itog_names:
        df = pd.read_excel(xlsx_path, sheet_name=name, engine="openpyxl")
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise SystemExit(
                f"Лист «{name}»: нет колонок {missing}. Ожидались: {REQUIRED_COLUMNS}"
            )
        df = df[REQUIRED_COLUMNS].copy()
        df["Качество, %"] = pd.to_numeric(df["Качество, %"], errors="coerce")
        df = df.sort_values("Качество, %", ascending=False, na_position="last").reset_index(
            drop=True
        )
        frames[name] = df
    return itog_names, frames


def aggregate(
    frames: dict[str, pd.DataFrame],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """Возвращает таблицы для блоков 1–5 и сводку по листам."""
    combo_top20: dict[str, int] = {}
    combo_top5: dict[str, int] = {}
    configs_in_top20: set[str] = set()
    fs_in_top20: set[str] = set()

    all_combos: set[str] = set()
    all_configs: set[str] = set()
    all_fs_tabular: set[str] = set()

    sheet_rows: list[dict[str, object]] = []

    for sheet_name, df in frames.items():
        n = len(df)
        t20 = min(TOP_20, n)
        t5 = min(TOP_5, n)
        top20_df = df.iloc[:t20]
        top5_df = df.iloc[:t5]

        for _, r in df.iterrows():
            all_combos.add(str(r["Комбинация"]))
            all_configs.add(str(r["Конфигурация"]))
            if _is_tabular_row(r["Набор признаков"]):
                all_fs_tabular.add(str(r["Набор признаков"]).strip())

        for _, r in top20_df.iterrows():
            c = str(r["Комбинация"])
            combo_top20[c] = combo_top20.get(c, 0) + 1
            configs_in_top20.add(str(r["Конфигурация"]))
            if _is_tabular_row(r["Набор признаков"]):
                fs_in_top20.add(str(r["Набор признаков"]).strip())

        for _, r in top5_df.iterrows():
            c = str(r["Комбинация"])
            combo_top5[c] = combo_top5.get(c, 0) + 1

        sheet_rows.append(
            {
                "Лист": sheet_name,
                "Строк в сводке": n,
                "Топ-20 (фактически)": t20,
                "Топ-5 (фактически)": t5,
            }
        )

    # 1 — частота в топ-20
    df1 = pd.DataFrame(
        [{"Комбинация": k, "Число_листов_в_топ20": v} for k, v in combo_top20.items()]
    )
    df1 = df1.sort_values(["Число_листов_в_топ20", "Комбинация"], ascending=[False, True])

    # 2 — ни разу в топ-20 (среди встречавшихся в данных)
    never20 = sorted(c for c in all_combos if combo_top20.get(c, 0) == 0)
    df2 = pd.DataFrame({"Комбинация": never20})

    # 3 — табличные наборы, ни разу в топ-20
    never_fs = sorted(fs for fs in all_fs_tabular if fs not in fs_in_top20)
    df3 = pd.DataFrame({"Набор признаков": never_fs})

    # 4 — конфиги, ни разу в топ-20
    never_cfg = sorted(c for c in all_configs if c not in configs_in_top20)
    df4 = pd.DataFrame({"Конфигурация": never_cfg})

    # 5 — топ-5 частота + ранг
    df5 = pd.DataFrame(
        [{"Комбинация": k, "Число_листов_в_топ5": v} for k, v in combo_top5.items()]
    )
    df5 = df5.sort_values(
        ["Число_листов_в_топ5", "Комбинация"], ascending=[False, True]
    ).reset_index(drop=True)
    df5.insert(0, "Ранг_по_частоте_топ5", range(1, len(df5) + 1))

    df_sheets = pd.DataFrame(sheet_rows)
    return df1, df2, df3, df4, df5, df_sheets


def _remove_sheets(wb_path: Path, names: list[str]) -> None:
    wb = load_workbook(wb_path)
    changed = False
    for sn in names:
        if sn in wb.sheetnames:
            wb.remove(wb[sn])
            changed = True
    if changed:
        wb.save(wb_path)
    wb.close()


def _add_bar_chart(
    ws,
    title: str,
    anchor: str,
    data_start_row: int,
    data_nrows: int,
    value_col: int = 2,
) -> None:
    """Столбчатая диаграмма (bar): категории в col 1, значения в value_col."""
    chart = BarChart()
    chart.type = "bar"
    chart.title = title
    chart.y_axis.title = "Листов"
    chart.x_axis.title = None
    chart.height = 12
    chart.width = 22

    cats = Reference(
        ws,
        min_col=1,
        min_row=data_start_row,
        max_row=data_start_row + data_nrows - 1,
    )
    data = Reference(
        ws,
        min_col=value_col,
        min_row=data_start_row - 1,
        max_row=data_start_row + data_nrows - 1,
    )
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.legend = None
    ws.add_chart(chart, anchor)


def _append_title_and_df(ws, r: int, title: str, df: pd.DataFrame) -> int:
    """Пишет заголовок блока и таблицу; возвращает следующую свободную строку (1-based)."""
    ws.cell(row=r, column=1, value=title)
    r += 1
    for row in dataframe_to_rows(df, index=False, header=True):
        for c, val in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=val)
        r += 1
    return r + 2


def _write_analytics_tables_sheet(
    xlsx_path: Path,
    meta: pd.DataFrame,
    df_sheets: pd.DataFrame,
    df1: pd.DataFrame,
    df2: pd.DataFrame,
    df3: pd.DataFrame,
    df4: pd.DataFrame,
    df5: pd.DataFrame,
) -> None:
    """Один лист без повторных to_excel на одно имя (иначе pandas перезаписывает лист)."""
    wb = load_workbook(xlsx_path)
    if SHEET_TABLES in wb.sheetnames:
        wb.remove(wb[SHEET_TABLES])
    ws = wb.create_sheet(SHEET_TABLES)
    r = 1
    for row in dataframe_to_rows(meta, index=False, header=True):
        for c, val in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=val)
        r += 1
    r += 1
    for row in dataframe_to_rows(df_sheets, index=False, header=True):
        for c, val in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=val)
        r += 1
    r += 1

    r = _append_title_and_df(
        ws,
        r,
        "1. Чаще всего в топ-20 (Комбинация = конфиг + набор; per-series — только конфиг)",
        df1,
    )
    r = _append_title_and_df(
        ws,
        r,
        "2. Варианты (Комбинация), ни разу не попавшие в топ-20 ни на одном листе",
        df2,
    )
    r = _append_title_and_df(
        ws,
        r,
        "3. Наборы признаков (табличные, без «—»), ни разу не встречавшиеся в топ-20",
        df3,
    )
    r = _append_title_and_df(
        ws,
        r,
        "4. Конфигурации, ни разу не попавшие в топ-20 ни на одном листе",
        df4,
    )
    _append_title_and_df(
        ws,
        r,
        "5. Варианты по частоте попадания в топ-5 (Ранг 1 — самая высокая частота)",
        df5,
    )

    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 22

    wb.save(xlsx_path)
    wb.close()


def run_analytics(xlsx_path: Path) -> None:
    if not xlsx_path.is_file():
        raise SystemExit(f"Файл не найден: {xlsx_path}")

    itog_names, frames = load_itog_sheets(xlsx_path)
    df1, df2, df3, df4, df5, df_sheets = aggregate(frames)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    n_itog = len(itog_names)

    _remove_sheets(xlsx_path, [SHEET_TABLES, SHEET_CHARTS])

    meta = pd.DataFrame(
        {
            "Параметр": [
                "Дата расчёта (UTC)",
                "Число листов «* Итог»",
                "Топ-20 / Топ-5",
            ],
            "Значение": [generated_at, n_itog, f"{TOP_20} / {TOP_5}"],
        }
    )
    _write_analytics_tables_sheet(
        xlsx_path, meta, df_sheets, df1, df2, df3, df4, df5
    )

    n1 = min(CHART_TOP_N, len(df1))
    n5 = min(CHART_TOP_N, len(df5))
    sub1 = df1.head(n1)
    sub5 = df5.head(n5)

    wb = load_workbook(xlsx_path)
    if SHEET_CHARTS in wb.sheetnames:
        wb.remove(wb[SHEET_CHARTS])
    ws = wb.create_sheet(SHEET_CHARTS)

    r = 1
    ws.cell(row=r, column=1, value=f"Топ-{CHART_TOP_N} по попаданиям в топ-20")
    r = 3
    ws.cell(row=r, column=1, value="Комбинация")
    ws.cell(row=r, column=2, value="Число_листов_в_топ20")
    data_top20_start = r + 1
    for i, (_, row_df) in enumerate(sub1.iterrows(), start=data_top20_start):
        ws.cell(row=i, column=1, value=row_df["Комбинация"])
        ws.cell(row=i, column=2, value=row_df["Число_листов_в_топ20"])
    if n1 > 0:
        _add_bar_chart(
            ws,
            title=f"Топ-{n1} вариантов — попадания в топ-20",
            anchor="E2",
            data_start_row=data_top20_start,
            data_nrows=n1,
            value_col=2,
        )

    gap = 4
    r = data_top20_start + max(n1, 0) + gap
    ws.cell(row=r, column=1, value=f"Топ-{CHART_TOP_N} по попаданиям в топ-5")
    r += 1
    hdr5 = r
    for j, h in enumerate(
        ["Ранг_по_частоте_топ5", "Комбинация", "Число_листов_в_топ5"], start=1
    ):
        ws.cell(row=hdr5, column=j, value=h)
    data_top5_start = hdr5 + 1
    for i, (_, row_df) in enumerate(sub5.iterrows(), start=data_top5_start):
        ws.cell(row=i, column=1, value=int(row_df["Ранг_по_частоте_топ5"]))
        ws.cell(row=i, column=2, value=row_df["Комбинация"])
        ws.cell(row=i, column=3, value=row_df["Число_листов_в_топ5"])

    if n5 > 0:
        chart2 = BarChart()
        chart2.type = "bar"
        chart2.title = f"Топ-{n5} вариантов — попадания в топ-5"
        chart2.y_axis.title = "Листов"
        chart2.height = 12
        chart2.width = 22
        cats2 = Reference(
            ws,
            min_col=2,
            min_row=data_top5_start,
            max_row=data_top5_start + n5 - 1,
        )
        data2 = Reference(
            ws,
            min_col=3,
            min_row=hdr5,
            max_row=data_top5_start + n5 - 1,
        )
        chart2.add_data(data2, titles_from_data=True)
        chart2.set_categories(cats2)
        chart2.legend = None
        anchor_row = max(2, hdr5 - 2)
        ws.add_chart(chart2, f"F{anchor_row}")

    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 18

    wb.save(xlsx_path)
    wb.close()

    print(f"Готово: {xlsx_path.resolve()}")
    print(f"  Листов «* Итог»: {n_itog}")
    print(f"  Добавлены: «{SHEET_TABLES}», «{SHEET_CHARTS}»")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description="Аналитика по листам «RESIST_ID Итог» в model_comparison.xlsx"
    )
    p.add_argument(
        "xlsx",
        nargs="?",
        type=Path,
        default=None,
        help="Путь к model_comparison.xlsx (по умолчанию data/processed/model_comparison.xlsx)",
    )
    args = p.parse_args(argv)
    path = args.xlsx if args.xlsx is not None else _default_xlsx_path()
    run_analytics(path)


if __name__ == "__main__":
    main()
