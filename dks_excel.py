"""Создание книги и запись листа Dks."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook
from depo_directory import DepoDirectoryRow
from gpb_d_msg import DMsgDataRow, DMsgFile, display_doc_date


DKS_HEADERS = [
    "Файл_отчета",
    "Дата_отчета",
    "ClientID",
    "DepoNum",
    "InstrNum",
    "ClientName",
    "NGRI",
    "Референс_договора",
    "Тип_документа",
    "Номер_документа",
    "Дата_документа",
    "Доп_описание",
    "Раздел_консолидированного_портфеля",
    "Депозитарий_справочник",
    "Оригинатор",
    "Агент_по_сопровождению",
    "Сделка_ДОМ_РФ_ИА",
    "Комментарий_счета",
    "Код_выписки_ГПБ_ДОМ",
    "Код_выписки_ГПБ_БАНК",
    "Владелец_счета_депо",
    "Справочник_сопоставлен",
]

SCHEETA_DEPO_HEADERS = [
    "Раздел консолидированного портфеля",
    "Депозитарий",
    "Номер счета депо",
    "Оригинатор",
    "Агент по сопровождению",
    "Сделка ДОМ.РФ ИА",
    "Комментарий",
    "Код выписки ГПБ (ДОМ)",
    "Код выписки ГПБ (БАНК)",
    "Владелец счета депо",
]


def create_workbook_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    default = wb.active
    default.title = "Dks"
    for col, title in enumerate(DKS_HEADERS, start=1):
        default.cell(row=1, column=col, value=title)

    ws_dep = wb.create_sheet("Счета депо")
    for col, title in enumerate(SCHEETA_DEPO_HEADERS, start=1):
        ws_dep.cell(row=1, column=col, value=title)

    wb.save(path)


def clear_dks_data(ws) -> None:
    max_r = ws.max_row or 1
    if max_r <= 1:
        return
    for r in range(2, max_r + 1):
        for c in range(1, len(DKS_HEADERS) + 1):
            ws.cell(row=r, column=c, value=None)


def ensure_dks_sheet(wb) -> None:
    if "Dks" not in wb.sheetnames:
        ws = wb.create_sheet("Dks")
    else:
        ws = wb["Dks"]
    for col, title in enumerate(DKS_HEADERS, start=1):
        ws.cell(row=1, column=col, value=title)


def row_values(
    parsed: DMsgFile,
    data: DMsgDataRow,
    ref: DepoDirectoryRow | None,
) -> list:
    h = parsed.header
    matched = "Да" if ref else "Нет"
    ref_vals = (
        [
            ref.portfolio_section,
            ref.depository,
            ref.originator,
            ref.servicing_agent,
            ref.deal_dom_rf_ia,
            ref.comment,
            ref.gpb_code_dom,
            ref.gpb_code_bank,
            ref.owner,
        ]
        if ref
        else ["", "", "", "", "", "", "", "", ""]
    )
    return [
        parsed.path.name,
        h.get("ReportDate"),
        h.get("ClientID"),
        h.get("DepoNum"),
        h.get("InstrNum"),
        h.get("ClientName"),
        data.ngri,
        data.ref_contract,
        data.doc_type,
        data.doc_num,
        display_doc_date(data.doc_date),
        data.extra,
        *ref_vals,
        matched,
    ]


def write_dks_rows(path: Path, rows_out: list[list]) -> None:
    wb = load_workbook(path)
    ensure_dks_sheet(wb)
    ws = wb["Dks"]
    clear_dks_data(ws)
    for i, row in enumerate(rows_out, start=2):
        for j, val in enumerate(row, start=1):
            ws.cell(row=i, column=j, value=val)
    wb.save(path)
