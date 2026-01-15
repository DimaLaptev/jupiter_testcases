from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import openpyxl


RU_MONTH = {
    "янв": "01",
    "фев": "02",
    "мар": "03",
    "апр": "04",
    "май": "05",
    "июн": "06",
    "июл": "07",
    "авг": "08",
    "сен": "09",
    "окт": "10",
    "ноя": "11",
    "дек": "12",
}


@dataclass
class SvodDivisionWorkload:
    division_title: str
    months: list[str]  # ISO: YYYY-MM-01
    workload_ml_pct: list[float]  # 11-я строка блока: “Нагрузка (ML), %”
    workload_manual_pct: list[float]  # 12-я строка блока: “Нагрузка, %” (manual)


def parse_month_label(label: Any) -> str | None:
    """Пример: 'дек.24' -> '2024-12-01'."""
    if label is None:
        return None
    s = str(label).strip().lower()
    m = re.search(r"(янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)\.(\d{2})", s)
    if not m:
        return None
    mm = RU_MONTH[m.group(1)]
    yyyy = 2000 + int(m.group(2))
    return f"{yyyy}-{mm}-01"


def to_pct(value: Any) -> float | None:
    """Нормализует проценты (percent) из Excel.

    Поддерживает:
    - '135%' -> 135.0
    - 135 -> 135.0
    - 1.35 -> 135.0 (если хранится как доля)
    """
    if value is None:
        return None

    if isinstance(value, str):
        s = value.strip().replace(",", ".").replace("%", "")
        try:
            v = float(s)
        except Exception:
            return None
        return v

    try:
        v = float(value)
    except Exception:
        return None

    # эвристика: 0..3 -> доля -> проценты
    if 0 <= v <= 3:
        return v * 100.0
    return v


def parse_svod_first_sheet_from_xlsx_bytes(
    xlsx_bytes: bytes,
    *,
    month_header_row: int = 3,
    month_start_col: int = 3,  # C
    blocks_start_row: int = 18,
    block_height: int = 13,
    block_gap: int = 2,
    title_col: int = 2,  # B
    ml_row_in_block: int = 11,  # 1-based внутри блока
    manual_row_in_block: int = 12,
) -> dict[str, SvodDivisionWorkload]:
    """Парсит первый лист "Сводный отчет" по структуре блоков.

    Структура:
    - первый блок начинается с 18 строки
    - каждый блок 13 строк
    - между блоками 2 строки отступа
    - название подразделения в B{start_row}
    - 11-я строка блока: Нагрузка (ML), %
    - 12-я строка блока: Нагрузка, % (manual)
    """
    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True)
    ws = wb.worksheets[0]

    # 1) читаем месяцы из строки 3 начиная с колонки C до первого пустого
    months: list[str] = []
    month_cols: list[int] = []
    col = month_start_col
    while True:
        iso = parse_month_label(ws.cell(row=month_header_row, column=col).value)
        if iso is None:
            break
        months.append(iso)
        month_cols.append(col)
        col += 1

    if not months:
        raise ValueError("Не удалось распарсить месяцы: проверь month_header_row/month_start_col")

    stride = block_height + block_gap
    row = blocks_start_row

    out: dict[str, SvodDivisionWorkload] = {}
    while True:
        title = ws.cell(row=row, column=title_col).value
        if title is None or str(title).strip() == "":
            break

        division_title = str(title).strip()
        ml_row = row + (ml_row_in_block - 1)
        manual_row = row + (manual_row_in_block - 1)

        ml_vals = [to_pct(ws.cell(row=ml_row, column=c).value) for c in month_cols]
        manual_vals = [to_pct(ws.cell(row=manual_row, column=c).value) for c in month_cols]

        out[division_title] = SvodDivisionWorkload(
            division_title=division_title,
            months=months,
            workload_ml_pct=[v if v is not None else float("nan") for v in ml_vals],
            workload_manual_pct=[v if v is not None else float("nan") for v in manual_vals],
        )

        row += stride

    return out

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import openpyxl


RU_MONTH = {
    "янв": "01",
    "фев": "02",
    "мар": "03",
    "апр": "04",
    "май": "05",
    "июн": "06",
    "июл": "07",
    "авг": "08",
    "сен": "09",
    "окт": "10",
    "ноя": "11",
    "дек": "12",
}


@dataclass
class SvodDivisionWorkload:
    division_title: str
    months: list[str]  # ISO: YYYY-MM-01
    workload_ml_pct: list[float]  # 11-я строка блока: “Нагрузка (ML), %”
    workload_manual_pct: list[float]  # 12-я строка блока: “Нагрузка, %” (manual)


def parse_month_label(label: Any) -> str | None:
    """
    Пример: 'дек.24' -> '2024-12-01'
    """
    if label is None:
        return None
    s = str(label).strip().lower()
    m = re.search(r"(янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)\.(\d{2})", s)
    if not m:
        return None
    mm = RU_MONTH[m.group(1)]
    yyyy = 2000 + int(m.group(2))
    return f"{yyyy}-{mm}-01"


def to_pct(value: Any) -> float | None:
    """
    Нормализуем проценты:
    - '135%' -> 135.0
    - 135 -> 135.0
    - 1.35 -> 135.0 (если вдруг хранится как доля)
    """
    if value is None:
        return None

    if isinstance(value, str):
        s = value.strip().replace(",", ".").replace("%", "")
        try:
            v = float(s)
        except Exception:
            return None
        return v

    try:
        v = float(value)
    except Exception:
        return None

    # эвристика: 0..3 -> доля -> проценты
    if 0 <= v <= 3:
        return v * 100.0
    return v


def parse_svod_first_sheet_from_xlsx_bytes(
    xlsx_bytes: bytes,
    *,
    month_header_row: int = 3,
    month_start_col: int = 3,  # C
    blocks_start_row: int = 18,
    block_height: int = 13,
    block_gap: int = 2,
    title_col: int = 2,  # B
    ml_row_in_block: int = 11,
    manual_row_in_block: int = 12,
) -> dict[str, SvodDivisionWorkload]:
    """
    Парсит первый лист “Сводный отчет” по структуре блоков:
    - первый блок начинается с 18 строки
    - каждый блок 13 строк
    - между блоками 2 строки отступа (stride = 15)
    - название подразделения в B{start_row} (merged cell top-left)
    - 11-я строка блока: Нагрузка (ML), %
    - 12-я строка блока: Нагрузка, % (manual)
    """
    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True)
    ws = wb.worksheets[0]

    # 1) читаем месяцы из строки 3 начиная с колонки C до первого пустого
    months: list[str] = []
    month_cols: list[int] = []

    col = month_start_col
    while True:
        iso = parse_month_label(ws.cell(row=month_header_row, column=col).value)
        if iso is None:
            break
        months.append(iso)
        month_cols.append(col)
        col += 1

    if not months:
        raise ValueError("Не удалось распарсить месяцы: проверь month_header_row/month_start_col")

    stride = block_height + block_gap
    row = blocks_start_row

    out: dict[str, SvodDivisionWorkload] = {}
    while True:
        title = ws.cell(row=row, column=title_col).value
        if title is None or str(title).strip() == "":
            break

        division_title = str(title).strip()

        ml_row = row + (ml_row_in_block - 1)
        manual_row = row + (manual_row_in_block - 1)

        ml_vals = [to_pct(ws.cell(row=ml_row, column=c).value) for c in month_cols]
        manual_vals = [to_pct(ws.cell(row=manual_row, column=c).value) for c in month_cols]

        out[division_title] = SvodDivisionWorkload(
            division_title=division_title,
            months=months,
            workload_ml_pct=[v if v is not None else float("nan") for v in ml_vals],
            workload_manual_pct=[v if v is not None else float("nan") for v in manual_vals],
        )

        row += stride

    return out


