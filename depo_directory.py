"""Загрузка и поиск по листу «Счета депо» в книге Excel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet


@dataclass
class DepoDirectoryRow:
    portfolio_section: str
    depository: str
    account_number: str
    originator: str
    servicing_agent: str
    deal_dom_rf_ia: str
    comment: str
    gpb_code_dom: str
    gpb_code_bank: str
    owner: str


def _norm_header(cell: Any) -> str:
    if cell is None or cell.value is None:
        return ""
    return str(cell.value).strip().lower()


def _find_header_row(ws: Worksheet, max_scan: int = 40) -> tuple[int, dict[str, int]]:
    for r in range(1, min(max_scan, (ws.max_row or 1) + 25) + 1):
        col_map: dict[str, int] = {}
        for c in range(1, (ws.max_column or 15) + 1):
            h = _norm_header(ws.cell(row=r, column=c))
            if h:
                col_map[h] = c
        if "номер счета депо" in col_map:
            return r, col_map
    return 1, {}


def normalize_match_token(value: Any) -> str:
    """Сопоставление ClientID с кодами выписки (70, 70.0, '070' → '70')."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    try:
        f = float(s.replace(",", "."))
        if f == int(f):
            return str(int(f))
    except (ValueError, TypeError):
        pass
    return s


def read_depo_directory_rows(
    workbook_path: str,
    sheet_name: str = "Счета депо",
) -> list[DepoDirectoryRow]:
    """Все строки справочника (для поиска счёта по ClientID)."""
    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return []
    ws = wb[sheet_name]
    header_row, col_map = _find_header_row(ws)
    if not col_map:
        wb.close()
        return []

    def col(name: str) -> int | None:
        return col_map.get(name)

    c_acc = col("номер счета депо")
    if not c_acc:
        wb.close()
        return []

    c_pf = col("раздел консолидированного портфеля")
    c_dep = col("депозитарий")
    c_orig = col("оригинатор")
    c_agent = col("агент по сопровождению")
    c_deal = col("сделка дом.рф иа")
    c_com = col("комментарий")
    c_cd = col("код выписки гпб (дом)")
    c_cb = col("код выписки гпб (банк)")
    c_own = col("владелец счета депо")

    rows_out: list[DepoDirectoryRow] = []

    def cell_val(r: int, ci: int | None) -> str:
        if not ci:
            return ""
        v = ws.cell(row=r, column=ci).value
        if v is None:
            return ""
        return str(v).strip()

    for r in range(header_row + 1, (ws.max_row or 0) + 1):
        acc_cell = ws.cell(row=r, column=c_acc).value
        if acc_cell is None or str(acc_cell).strip() == "":
            continue

        rows_out.append(
            DepoDirectoryRow(
                portfolio_section=cell_val(r, c_pf),
                depository=cell_val(r, c_dep),
                account_number=str(acc_cell).strip(),
                originator=cell_val(r, c_orig),
                servicing_agent=cell_val(r, c_agent),
                deal_dom_rf_ia=cell_val(r, c_deal),
                comment=cell_val(r, c_com),
                gpb_code_dom=cell_val(r, c_cd),
                gpb_code_bank=cell_val(r, c_cb),
                owner=cell_val(r, c_own),
            )
        )

    wb.close()
    return rows_out


def lookup_account_by_client_id(
    rows: list[DepoDirectoryRow],
    client_id: str,
) -> str | None:
    """
    «Номер счета депо»: строка справочника, где ClientID совпал с
    «Код выписки ГПБ (ДОМ)» или «Код выписки ГПБ (БАНК)».
    """
    target = normalize_match_token(client_id)
    if not target:
        return None
    for row in rows:
        dom = normalize_match_token(row.gpb_code_dom)
        bank = normalize_match_token(row.gpb_code_bank)
        if target == dom or target == bank:
            return row.account_number
    return None


def load_depo_index(
    workbook_path: str,
    sheet_name: str = "Счета депо",
) -> dict[str, DepoDirectoryRow]:
    """Индекс по номеру счёта депо (для совместимости)."""
    rows = read_depo_directory_rows(workbook_path, sheet_name)
    index: dict[str, DepoDirectoryRow] = {}
    for row in rows:
        acc_key = normalize_account_key(row.account_number)
        if acc_key:
            index[acc_key] = row
            try:
                index[str(int(float(row.account_number)))] = row
            except (ValueError, TypeError):
                pass
    return index


def normalize_account_key(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
    except (ValueError, TypeError):
        pass
    return s


def lookup_depo(index: dict[str, DepoDirectoryRow], depo_num: str) -> DepoDirectoryRow | None:
    if not depo_num.strip():
        return None
    k = normalize_account_key(depo_num.strip())
    if k in index:
        return index[k]
    raw = depo_num.strip()
    if raw in index:
        return index[raw]
    return None
