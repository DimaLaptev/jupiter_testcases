"""Лист «СВОД_операций» в 2026_01_Ord_Quantity.xlsx."""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook, load_workbook

from codifier_table import (
    CodifierRow,
    fallback_document_op_type,
    lookup_codifier,
    lookup_codifier_r01_operation_type,
    lookup_codifier_region,
    lookup_codifier_rsd,
    lookup_codifier_vtb,
    lookup_document_op_type_by_instruction,
)
from depo_directory import (
    DepoDirectoryRow,
    lookup_account_by_client_id,
    lookup_account_by_gpb_bank_code,
    lookup_account_by_gpb_dom_code,
    lookup_depo_row_by_account_number,
    lookup_depo_row_by_client_id,
    normalize_account_key,
)
from gpb_d_msg import DMsgDataRow, DMsgFile, instruction_type_df_dp
from gpb_i_msg import IField, IMsgDataRow, IMsgFile, compute_depot_section
from rsd_i_msg import (
    RsdIField,
    rsd_debit_credit_columns,
    rsd_exec_four_from_operation_type_label,
    rsd_execution_code,
)
from region_is_xls import RegionParseResult, RegionTableRow
from rsd_r01_xlsx import R01DataRow, R01ParseResult, parse_section_code
from vtb_f752_xml import VtbF752ParseResult, vtb_combine_section


SVOD_DASH = "-"

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
    "НГРИ",
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
    """Колонка Q: счёт_раздел_N_дата — счёт и раздел как в колонках «Счет депо» и «Раздел депо» строки."""
    return f"{account_f.strip()}_{section_g.strip()}_{instruction_n.strip()}_{date_op.strip()}"


def svod_technical_key_d(account_f: str, instruction_n: str, date_op: str) -> str:
    """Колонка Q для строк из отчёта D: F_N_дата (напр. 10934_DF_04.02.2025)."""
    return f"{account_f.strip()}_{instruction_n.strip()}_{date_op.strip()}"


def svod_technical_key_vtb(
    account_f: str,
    section_g: str,
    instruction_n: str,
    date_op: str,
    ngri: str,
) -> str:
    """Колонка Q для ВТБ СД: базовый ключ + НГРИ (NRN), чтобы строки по закладным не схлопывались."""
    base = svod_technical_key(account_f, section_g, instruction_n, date_op)
    n = (ngri or "").strip()
    if not n or n == SVOD_DASH:
        return base
    safe = re.sub(r"[^\w\-.:]+", "_", n, flags=re.UNICODE)
    return f"{base}_{safe}"


def depository_fallback_from_source_path(path: Path) -> str:
    """
    Резерв для колонки «Депозитарий»: по сегменту пути входного файла.
    Порядок: RSD → GPB → REGION → VTBSD (без учёта регистра).
    """
    p = Path(path)
    try:
        parts_upper = {part.upper() for part in p.resolve().parts}
    except (OSError, RuntimeError):
        parts_upper = {part.upper() for part in p.parts}
    for segment, label in (
        ("RSD", 'ООО "РСД"'),
        ("GPB", "Банк ГПБ АО"),
        ("REGION", 'АО "ДК РЕГИОН"'),
        ("VTBSD", 'АО "ВТБ СД"'),
    ):
        if segment in parts_upper:
            return label
    return ""


def _format_depo_account_cell(acc: str | None) -> str:
    if not acc or not str(acc).strip():
        return ""
    s = str(acc).strip()
    try:
        return str(int(float(s)))
    except (ValueError, TypeError):
        return s


def _gpb_depo_flow_hint(
    f_svod: str,
    h_acc: str,
    i_sec: str,
    j_acc: str,
    k_sec: str,
) -> str | None:
    """
    Направление для «Коды»: «Счет депо» совпал с любым из пары списания (H/I) → debit,
    с любым из пары зачисления (J/K) → credit (формат Excel: в I могут быть и счёт, и раздел).
    """
    ks = normalize_account_key(f_svod)
    if not ks:
        return None
    debit_keys = {normalize_account_key(h_acc), normalize_account_key(i_sec)} - {""}
    credit_keys = {normalize_account_key(j_acc), normalize_account_key(k_sec)} - {""}
    on_debit = ks in debit_keys
    on_credit = ks in credit_keys
    if on_debit and not on_credit:
        return "debit"
    if on_credit and not on_debit:
        return "credit"
    return None


def _gpb_g_depo_section(
    f_svod: str,
    f_raw: str,
    g_raw: str,
    h_acc: str,
    i_sec: str,
    j_acc: str,
    k_sec: str,
) -> str:
    """Колонка «Раздел депо»: раздел списания или зачисления по стороне «Счет депо»; иначе §4.4 ТЗ."""
    ks = normalize_account_key(f_svod)
    if not ks:
        return compute_depot_section(f_raw, g_raw, h_acc, i_sec, j_acc, k_sec)
    debit_keys = {normalize_account_key(h_acc), normalize_account_key(i_sec)} - {""}
    credit_keys = {normalize_account_key(j_acc), normalize_account_key(k_sec)} - {""}
    on_debit = ks in debit_keys
    on_credit = ks in credit_keys
    if on_debit and not on_credit:
        return str(i_sec).strip()
    if on_credit and not on_debit:
        return str(k_sec).strip()
    return compute_depot_section(f_raw, g_raw, h_acc, i_sec, j_acc, k_sec)


def _format_section_cell(sec: str | None) -> str:
    if sec is None or not str(sec).strip():
        return ""
    s = str(sec).strip()
    try:
        return str(int(float(s)))
    except (ValueError, TypeError):
        return s


def _region_op_date_from_stem(stem: str) -> str:
    """IS250205… → 05.02.2025 (дата из имени файла (filename), если нет в шапке)."""
    m = re.match(r"^IS(\d{2})(\d{2})(\d{2})", stem, flags=re.IGNORECASE)
    if not m:
        return ""
    yy, mm, dd = m.groups()
    return f"{dd}.{mm}.20{yy}"


def _region_fgh_ijk(
    label_raw: str,
    op_type_resolved: str,
    from_acc: str,
    from_sec: str,
    to_acc: str,
    to_sec: str,
) -> tuple[str, str, str, str, str, str]:
    """F/G и H–K для отчёта REGION: перевод (transfer), зачисление (credit), списание (debit)."""
    lab = f"{label_raw} {op_type_resolved}".lower()
    fa, fs = (from_acc or "").strip(), (from_sec or "").strip()
    ta, ts = (to_acc or "").strip(), (to_sec or "").strip()
    has_from, has_to = bool(fa), bool(ta)

    if has_from and has_to:
        return ta, ts, fa, fs, ta, ts

    if "зачисление" in lab and "списание" not in lab:
        acc, sec = (ta, ts) if has_to else (fa, fs)
        if acc:
            return acc, sec, "", "", acc, sec
        return "", "", "", "", "", ""

    if "списание" in lab and "зачисление" not in lab:
        acc, sec = (fa, fs) if has_from else (ta, ts)
        if acc:
            return acc, sec, acc, sec, "", ""
        return "", "", "", "", "", ""

    ex = rsd_exec_four_from_operation_type_label(label_raw)
    f0 = fa or ta
    g0 = fs or ts
    if not f0:
        return "", "", "", "", "", ""
    h, i, j, k = rsd_debit_credit_columns(ex, f0, g0, op_type_resolved)
    return f0, g0, h, i, j, k


def build_svod_row_from_d(
    parsed: DMsgFile,
    data: DMsgDataRow,
    depo_rows: list[DepoDirectoryRow],
    codifier_rows: list[CodifierRow],
    client_id: str,
) -> list:
    """Одна строка «СВОД_операций» из отчёта DOC_INSTRUCT (D*.MSG), эталон 2025_02."""
    h = parsed.header
    op_date = (h.get("ReportDate") or "").strip()

    acc_raw = lookup_account_by_client_id(depo_rows, client_id)
    f_str = _format_depo_account_cell(acc_raw)
    if not f_str:
        f_str = SVOD_DASH

    depo_by_client = lookup_depo_row_by_client_id(depo_rows, client_id)
    depository = (depo_by_client.depository if depo_by_client else "").strip()
    if not depository:
        depository = depository_fallback_from_source_path(parsed.path).strip()
    if not depository:
        depository = SVOD_DASH

    acc_for_inst = f_str if f_str != SVOD_DASH else ""
    inst_type = instruction_type_df_dp(acc_for_inst)

    op_type = lookup_document_op_type_by_instruction(codifier_rows, inst_type)
    if not op_type:
        op_type = fallback_document_op_type(inst_type) or SVOD_DASH

    if f_str != SVOD_DASH:
        owner_row = lookup_depo_row_by_account_number(depo_rows, f_str)
        owner = (owner_row.owner if owner_row else (depo_by_client.owner if depo_by_client else "")).strip()
    else:
        owner = (depo_by_client.owner if depo_by_client else "").strip()
    if not owner:
        owner = SVOD_DASH

    nrn = data.ngri.strip()
    tech = svod_technical_key_d(f_str, inst_type, op_date)

    return [
        op_date or SVOD_DASH,
        depository,
        SVOD_DASH,
        op_type,
        owner,
        f_str,
        SVOD_DASH,
        SVOD_DASH,
        SVOD_DASH,
        SVOD_DASH,
        SVOD_DASH,
        nrn or SVOD_DASH,
        "1",
        inst_type,
        SVOD_DASH,
        SVOD_DASH,
        tech,
        parsed.path.name,
    ]


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

    op_code = data.get(IField.OP_CODE)
    aux = data.get(IField.AUX_CODE)

    depo_by_client = lookup_depo_row_by_client_id(depo_rows, client_id)
    depository = depo_by_client.depository if depo_by_client else ""

    acc_from_ref = lookup_account_by_gpb_dom_code(depo_rows, client_id)
    if not acc_from_ref:
        acc_from_ref = lookup_account_by_gpb_bank_code(depo_rows, client_id)
    f_svod = (
        _format_depo_account_cell(acc_from_ref)
        if acc_from_ref
        else (_format_depo_account_cell(f_raw) or (f_raw or "").strip())
    )

    flow_hint = _gpb_depo_flow_hint(f_svod, h_acc, i_sec, j_acc, k_sec)
    g_out = _gpb_g_depo_section(f_svod, f_raw, g_raw, h_acc, i_sec, j_acc, k_sec)

    inst_type, op_type = lookup_codifier(
        codifier_rows,
        op_code,
        aux,
        f_svod,
        h_acc,
        j_acc,
        flow_hint=flow_hint,
    )

    owner_row = lookup_depo_row_by_account_number(depo_rows, f_svod or f_raw)
    owner = owner_row.owner if owner_row else (depo_by_client.owner if depo_by_client else "")

    nrn = data.get(IField.NRN)
    qty = data.get(IField.QTY) or "1"
    basis = data.get(IField.BASIS)

    tech = svod_technical_key(f_svod, g_out, inst_type, op_date)

    h_out = _format_depo_account_cell(h_acc) or (h_acc or "").strip()
    i_out = _format_section_cell(i_sec) or (i_sec or "").strip()
    j_out = _format_depo_account_cell(j_acc) or (j_acc or "").strip()
    k_out = _format_section_cell(k_sec) or (k_sec or "").strip()

    return [
        op_date,
        depository,
        op_code,
        op_type,
        owner,
        f_svod,
        g_out,
        h_out,
        i_out,
        j_out,
        k_out,
        nrn,
        qty,
        inst_type,
        "",
        basis,
        tech,
        parsed.path.name,
    ]


def build_svod_row_rsd(
    parsed: IMsgFile,
    data: IMsgDataRow,
    depo_rows: list[DepoDirectoryRow],
    codifier_rows: list[CodifierRow],
    client_id: str,
) -> list:
    """Одна строка «СВОД_операций» из отчёта РСД I*.MSG (формат RSD_MSG_example)."""
    h = parsed.header
    op_date = (h.get("ReportDate") or "").strip()
    parts = data.parts

    f_raw = _format_depo_account_cell(parts[RsdIField.ACCOUNT_F]) or parts[
        RsdIField.ACCOUNT_F
    ].strip()
    g_raw = _format_section_cell(parts[RsdIField.SECTION_G]) or parts[
        RsdIField.SECTION_G
    ].strip()

    op_code = parts[RsdIField.OP_CODE].strip()
    desc = parts[RsdIField.DESCRIPTION].strip() if len(parts) > RsdIField.DESCRIPTION else ""
    exec_c = rsd_execution_code(parts)

    inst_type, op_type = lookup_codifier_rsd(
        codifier_rows,
        op_code,
        exec_c,
        desc,
    )

    h_acc, i_sec, j_acc, k_sec = rsd_debit_credit_columns(
        exec_c,
        f_raw,
        g_raw,
        op_type,
    )

    depo_by_client = lookup_depo_row_by_client_id(depo_rows, client_id)
    depository = (depo_by_client.depository if depo_by_client else "").strip()
    if not depository:
        depository = depository_fallback_from_source_path(parsed.path).strip()
    owner_row = lookup_depo_row_by_account_number(depo_rows, f_raw)
    owner = owner_row.owner if owner_row else (depo_by_client.owner if depo_by_client else "")

    nrn = parts[RsdIField.NRN].strip() if len(parts) > RsdIField.NRN else ""
    qty = (
        parts[RsdIField.QTY].strip()
        if len(parts) > RsdIField.QTY
        else "1"
    ) or "1"

    tech = svod_technical_key(f_raw, g_raw, inst_type, op_date)

    return [
        op_date,
        depository,
        op_code,
        op_type,
        owner,
        f_raw,
        g_raw,
        h_acc,
        i_sec,
        j_acc,
        k_sec,
        nrn,
        qty,
        inst_type,
        "",
        desc,
        tech,
        parsed.path.name,
    ]


def build_svod_row_r01(
    result: R01ParseResult,
    data: R01DataRow,
    depo_rows: list[DepoDirectoryRow],
    codifier_rows: list[CodifierRow],
    *,
    skip_instruction_e: bool = True,
) -> list | None:
    """Одна строка «СВОД_операций» из отчёта РСД R-01 *.xlsx."""
    low_op = data.operation_type.lower()
    if skip_instruction_e and "перевод между разделами" in low_op:
        return None

    inst_type, op_type, op_code = lookup_codifier_r01_operation_type(
        codifier_rows,
        data.operation_type,
    )
    if skip_instruction_e and inst_type.strip().upper() == "E":
        return None

    f_raw = _format_depo_account_cell(result.depo_account) or result.depo_account.strip()
    g_raw = parse_section_code(data.section_raw)

    exec_c = rsd_exec_four_from_operation_type_label(data.operation_type)
    h_acc, i_sec, j_acc, k_sec = rsd_debit_credit_columns(
        exec_c,
        f_raw,
        g_raw,
        op_type,
    )

    owner_row = lookup_depo_row_by_account_number(depo_rows, f_raw)
    depository = (owner_row.depository if owner_row else "").strip()
    if not depository:
        depository = depository_fallback_from_source_path(result.path).strip()
    owner = owner_row.owner if owner_row else ""

    op_date = data.exec_date_display.strip()
    nrn = data.reg_number.strip()
    qty = data.qty.strip() or "1"
    basis = data.basis.strip()

    op_code_cell = op_code if op_code else SVOD_DASH

    tech = svod_technical_key(f_raw, g_raw, inst_type, op_date)

    return [
        op_date,
        depository,
        op_code_cell,
        op_type,
        owner,
        f_raw,
        g_raw,
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
        result.path.name,
    ]


def build_svod_row_vtb(
    parsed: VtbF752ParseResult,
    ngri: str,
    depo_rows: list[DepoDirectoryRow],
    codifier_rows: list[CodifierRow],
) -> list:
    """Одна строка «СВОД_операций» из отчёта ВТБ СД F752 (*.xml) + НГРИ из приложения (appendix) ZIP."""
    op_date = (
        parsed.stage_overlay_date.strip()
        or parsed.execution_date.strip()
        or parsed.order_date.strip()
    )
    if not op_date:
        op_date = SVOD_DASH

    src_blob = f"{parsed.src_section_name} {parsed.src_sp_section_code}".strip()
    dst_blob = f"{parsed.dst_section_name} {parsed.dst_sp_section_code}".strip()

    inst_type, op_type, op_code = lookup_codifier_vtb(
        codifier_rows,
        parsed.stage_name,
        src_sections_blob=src_blob,
        dst_sections_blob=dst_blob,
    )
    op_code_cell = op_code if op_code else SVOD_DASH
    if not (op_type or "").strip():
        op_type = SVOD_DASH
    inst_cell = inst_type.strip() if (inst_type or "").strip() else SVOD_DASH

    src_sec = vtb_combine_section(parsed.src_section_name, parsed.src_sp_section_code)
    dst_sec = vtb_combine_section(parsed.dst_section_name, parsed.dst_sp_section_code)

    h_acc = _format_depo_account_cell(parsed.src_account) or (parsed.src_account or "").strip()
    i_sec = _format_section_cell(src_sec) or src_sec
    j_acc = _format_depo_account_cell(parsed.dst_account) or (parsed.dst_account or "").strip()
    k_sec = _format_section_cell(dst_sec) or dst_sec

    f_raw = (j_acc or h_acc).strip() or SVOD_DASH
    g_raw = (k_sec or i_sec).strip() or SVOD_DASH

    owner_row = (
        None
        if f_raw == SVOD_DASH
        else lookup_depo_row_by_account_number(depo_rows, f_raw)
    )
    depository = (owner_row.depository if owner_row else "").strip()
    if not depository:
        depository = (parsed.depository_name or "").strip()
    if not depository:
        depository = depository_fallback_from_source_path(parsed.path).strip()
    if not depository:
        depository = SVOD_DASH
    owner = (owner_row.owner if owner_row else "").strip() or SVOD_DASH

    basis_parts: list[str] = []
    if parsed.order_number.strip():
        basis_parts.append(f"№{parsed.order_number.strip()}")
    if parsed.basis.strip():
        basis_parts.append(parsed.basis.strip())
    if parsed.dop_info.strip():
        basis_parts.append(parsed.dop_info.strip())
    basis = " ".join(basis_parts) if basis_parts else SVOD_DASH

    nrn_cell = (ngri or "").strip() or SVOD_DASH
    qty_cell = (parsed.qty or "1").strip() or "1"

    tech = svod_technical_key_vtb(f_raw, g_raw, inst_cell, op_date, nrn_cell)

    comment = (parsed.stage_name or "").strip() or SVOD_DASH

    return [
        op_date,
        depository,
        op_code_cell,
        op_type,
        owner,
        f_raw,
        g_raw,
        h_acc or SVOD_DASH,
        i_sec or SVOD_DASH,
        j_acc or SVOD_DASH,
        k_sec or SVOD_DASH,
        nrn_cell,
        qty_cell,
        inst_cell,
        comment,
        basis,
        tech,
        parsed.path.name,
    ]


def build_svod_row_region(
    result: RegionParseResult,
    table_row: RegionTableRow,
    depo_rows: list[DepoDirectoryRow],
    codifier_rows: list[CodifierRow],
) -> list:
    """Одна строка «СВОД_операций» из отчёта REGION IS*.xls (одна строка таблицы — одна строка СВОД)."""
    op_date = (result.op_date or "").strip() or _region_op_date_from_stem(
        result.path.stem,
    )

    inst_type, op_type, op_code = lookup_codifier_region(
        codifier_rows,
        result.operation_type,
    )
    if not op_type.strip():
        op_type = SVOD_DASH
    op_code_cell = op_code if op_code else SVOD_DASH

    f_raw, g_raw, h_acc, i_sec, j_acc, k_sec = _region_fgh_ijk(
        result.operation_type,
        op_type,
        result.from_acc,
        result.from_sec,
        result.to_acc,
        result.to_sec,
    )
    f_raw = _format_depo_account_cell(f_raw) or f_raw
    g_raw = _format_section_cell(g_raw) or g_raw
    h_acc = _format_depo_account_cell(h_acc) or h_acc
    i_sec = _format_section_cell(i_sec) or i_sec
    j_acc = _format_depo_account_cell(j_acc) or j_acc
    k_sec = _format_section_cell(k_sec) or k_sec

    owner_row = lookup_depo_row_by_account_number(depo_rows, f_raw)
    depository = (owner_row.depository if owner_row else "").strip()
    if not depository:
        depository = depository_fallback_from_source_path(result.path).strip()
    owner = (owner_row.owner if owner_row else "").strip()

    nrn = (table_row.ngri or "").strip() or SVOD_DASH
    basis = (result.reg_footer or result.basis or "").strip()
    inst_cell = inst_type.strip() or SVOD_DASH

    tech = svod_technical_key(f_raw, g_raw, inst_cell, op_date)

    return [
        op_date,
        depository,
        op_code_cell,
        op_type,
        owner,
        f_raw,
        g_raw,
        h_acc,
        i_sec,
        j_acc,
        k_sec,
        nrn,
        "1",
        inst_cell,
        "",
        basis,
        tech,
        result.path.name,
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
