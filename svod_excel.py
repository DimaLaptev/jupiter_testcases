"""Лист «СВОД_операций» в 2026_01_Ord_Quantity.xlsx."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook

from codifier_table import CodifierRow, lookup_codifier
from depo_directory import DepoDirectoryRow, lookup_depo_row_by_account_number, lookup_depo_row_by_client_id
from gpb_i_msg import IField, IMsgDataRow, IMsgFile, compute_depot_section


SVOD_HEADERS = [
    "Дата операции",
    "Депозитарий",
    "Код операции",
    "Тип операции",
    "Владелец",
    "Счет депо",
    "Раздел депо",
    "Счет списания",
    "Раздел списания",
    "Счет зачисления",
    "Раздел зачисления",
    "НРН",
    "Количество закладных",
    "Тип поручения",
    "Комментарий",
    "Основание",
    "ОдноТипОперТипРазд",
    "Источник",
]


def svod_technical_key(
    account_f: str,
    section_g: str,
    instruction_n: str,
    date_op: str,
) -> str:
    """Колонка Q: F_G_N_дата (как на скрине СВОД_операций)."""
    return f"{account_f.strip()}_{section_g.strip()}_{instruction_n.strip()}_{date_op.strip()}"


def build_svod_row(
    parsed: IMsgFile,
    data: IMsgDataRow,
    depo_rows: list[DepoDirectoryRow],
    codifier_rows: list[CodifierRow],
    client_id: str,
) -> list:
    h = parsed.header
    op_date = (h.get("ReportDate") or "").strip()

    f_raw = data.get(IField.F_DEPO_ACC)
    g_raw = data.get(IField.G_DEPO_SEC)
    h_acc = data.get(IField.H_DEBIT_ACC)
    i_sec = data.get(IField.I_DEBIT_SEC)
    j_acc = data.get(IField.J_CREDIT_ACC)
    k_sec = data.get(IField.K_CREDIT_SEC)

    g_out = compute_depot_section(f_raw, g_raw, h_acc, i_sec, j_acc, k_sec)

    op_code = data.get(IField.OP_CODE)
    aux = data.get(IField.AUX_CODE)

    inst_type, op_type = lookup_codifier(
        codifier_rows,
        op_code,
        aux,
        f_raw,
        h_acc,
        j_acc,
    )

    depo_by_client = lookup_depo_row_by_client_id(depo_rows, client_id)
    depository = depo_by_client.depository if depo_by_client else ""
    owner_row = lookup_depo_row_by_account_number(depo_rows, f_raw)
    owner = owner_row.owner if owner_row else (depo_by_client.owner if depo_by_client else "")

    nrn = data.get(IField.NRN)
    qty = data.get(IField.QTY) or "1"
    basis = data.get(IField.BASIS)

    tech = svod_technical_key(f_raw, g_out, inst_type, op_date)

    return [
        op_date,
        depository,
        op_code,
        op_type,
        owner,
        f_raw,
        g_out,
        h_acc,
        i_sec,
        j_acc,
        k_sec,
        nrn,
        qty,
        inst_type,
        "",
        basis,
        tech,
        parsed.path.name,
    ]


def ensure_svod_sheet(wb) -> None:
    if "СВОД_операций" not in wb.sheetnames:
        wb.create_sheet("СВОД_операций")
    ws = wb["СВОД_операций"]
    for col, title in enumerate(SVOD_HEADERS, start=1):
        ws.cell(row=1, column=col, value=title)


def clear_svod_data(ws) -> None:
    max_r = ws.max_row or 1
    if max_r <= 1:
        return
    for r in range(2, max_r + 1):
        for c in range(1, len(SVOD_HEADERS) + 1):
            ws.cell(row=r, column=c, value=None)


def write_svod_rows(path: Path, rows_out: list[list]) -> None:
    wb = load_workbook(path)
    ensure_svod_sheet(wb)
    ws = wb["СВОД_операций"]
    clear_svod_data(ws)
    for i, row in enumerate(rows_out, start=2):
        for j, val in enumerate(row, start=1):
            ws.cell(row=i, column=j, value=val)
    wb.save(path)


def create_workbook_with_svod_only(path: Path) -> None:
    """Минимальная книга только с заголовком СВОД (если файла нет)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "СВОД_операций"
    for col, title in enumerate(SVOD_HEADERS, start=1):
        ws.cell(row=1, column=col, value=title)
    wb.save(path)
