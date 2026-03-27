"""Чтение листа «Коды» и поиск «Тип поручения» / «Тип операции»."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openpyxl import load_workbook


@dataclass
class CodifierRow:
    op_code: str
    exec_code: str
    op_type: str
    content_gpb: str
    instruction_type: str
    comment: str


def _norm_header(cell: Any) -> str:
    if cell is None or cell.value is None:
        return ""
    return str(cell.value).strip().lower()


def _find_header_row(ws, max_scan: int = 40) -> tuple[int, dict[str, int]]:
    for r in range(1, min(max_scan, (ws.max_row or 1) + 30) + 1):
        col_map: dict[str, int] = {}
        for c in range(1, (ws.max_column or 20) + 1):
            h = _norm_header(ws.cell(row=r, column=c))
            if h:
                col_map[h] = c
        if "код операции" in col_map and "тип поручения" in col_map:
            return r, col_map
    return 1, {}


def _cell(ws, r: int, col: int | None) -> str:
    if not col:
        return ""
    v = ws.cell(row=r, column=col).value
    if v is None:
        return ""
    return str(v).strip()


def _is_dash(s: str) -> bool:
    t = s.strip()
    return t in ("", "—", "-", "–", "None")


def read_codifier_rows(workbook_path: str, sheet_name: str = "Коды") -> list[CodifierRow]:
    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return []
    ws = wb[sheet_name]
    hr, col_map = _find_header_row(ws)
    if not col_map:
        wb.close()
        return []

    def col(*names: str) -> int | None:
        for n in names:
            k = n.lower()
            if k in col_map:
                return col_map[k]
        return None

    c_op = col("код операции")
    c_ex = col("код исполнения")
    c_type = col("тип операции")
    c_gpb = col("содержание гпб")
    c_inst = col("тип поручения")
    c_com = col("комментарий")

    if not c_op or not c_inst:
        wb.close()
        return []

    out: list[CodifierRow] = []
    for r in range(hr + 1, (ws.max_row or 0) + 1):
        op = _cell(ws, r, c_op)
        if _is_dash(op):
            op = ""
        ex = _cell(ws, r, c_ex) if c_ex else ""
        if _is_dash(ex):
            ex = ""
        ot = _cell(ws, r, c_type) if c_type else ""
        gpb = _cell(ws, r, c_gpb) if c_gpb else ""
        inst = _cell(ws, r, c_inst)
        com = _cell(ws, r, c_com) if c_com else ""
        if not op and not ot and not inst:
            continue
        out.append(
            CodifierRow(
                op_code=op,
                exec_code=ex,
                op_type=ot,
                content_gpb=gpb,
                instruction_type=inst,
                comment=com,
            )
        )
    wb.close()
    return out


def _norm_op_code(s: str) -> str:
    try:
        return str(int(float(str(s).strip())))
    except (ValueError, TypeError):
        return str(s).strip()


def _norm_exec(s: str) -> str:
    t = str(s).strip()
    if not t:
        return ""
    try:
        n = int(float(t))
        return f"{n:04d}"[-4:]
    except (ValueError, TypeError):
        return t


def lookup_codifier(
    rows: list[CodifierRow],
    op_code_raw: str,
    aux_code_raw: str,
    f_acc: str,
    h_acc: str,
    j_acc: str,
) -> tuple[str, str]:
    """
    Возвращает (тип_поручения, тип_операции).
    Операция: код из MSG + вспомогательное поле; при нескольких строках в кодификаторе —
    различение по коду исполнения (если задан в таблице) или по зачисление/списание и F vs H/J.
    """
    op = _norm_op_code(op_code_raw)
    if not op:
        return "", ""

    candidates = [r for r in rows if _norm_op_code(r.op_code) == op]
    if not candidates:
        return "", ""

    aux = aux_code_raw.strip()

    def try_exec_match() -> CodifierRow | None:
        if not aux:
            return None
        a_norm = _norm_exec(aux)
        for r in candidates:
            if not r.exec_code.strip():
                continue
            ex = _norm_exec(r.exec_code)
            if ex == a_norm or r.exec_code.strip() == aux:
                return r
        return None

    m = try_exec_match()
    if m:
        return m.instruction_type, m.op_type

    if len(candidates) == 1:
        r = candidates[0]
        return r.instruction_type, r.op_type

    def nf(x: str) -> str:
        try:
            return str(int(float(str(x).strip())))
        except (ValueError, TypeError):
            return str(x).strip()

    fn, hn, jn = nf(f_acc), nf(h_acc), nf(j_acc)

    for r in candidates:
        ot = r.op_type.lower()
        if "зачисление" in ot and fn and jn and fn == jn:
            return r.instruction_type, r.op_type
        if "списание" in ot and fn and hn and fn == hn:
            return r.instruction_type, r.op_type

    r0 = candidates[0]
    return r0.instruction_type, r0.op_type
