"""Чтение листа «Коды» и поиск «Тип поручения» / «Тип операции»."""

from __future__ import annotations

import re
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
    content_gpb_rep: str = ""
    content_rsd: str = ""
    content_region: str = ""
    content_vtb: str = ""


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


def _col_content_gpb_rep(col_map: dict[str, int]) -> int | None:
    """Колонка «Содержание ГПБ в REP» (если есть в шапке листа «Коды»)."""
    for key, idx in col_map.items():
        if "содержание" in key and "rep" in key:
            return idx
    return None


def _col_content_region(col_map: dict[str, int]) -> int | None:
    """Колонка «Содержание РЕГИОН» или длинный заголовок «… в отчёте P»."""
    for key, idx in col_map.items():
        if "содержание" in key and "регион" in key:
            return idx
    for key, idx in col_map.items():
        if "отчете" in key and "тип операции" in key:
            return idx
    return None


def _col_content_vtb(col_map: dict[str, int]) -> int | None:
    """Колонка «Содержание ВТБСД»."""
    for key, idx in col_map.items():
        if "содержание" in key and "втб" in key:
            return idx
    return None


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
    c_rsd = col("содержание рсд")
    c_inst = col("тип поручения")
    c_com = col("комментарий")
    c_gpb_rep = _col_content_gpb_rep(col_map)
    c_region = _col_content_region(col_map)
    c_vtb = _col_content_vtb(col_map)

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
        rsd = _cell(ws, r, c_rsd) if c_rsd else ""
        if _is_dash(rsd):
            rsd = ""
        inst = _cell(ws, r, c_inst)
        com = _cell(ws, r, c_com) if c_com else ""
        gpb_rep = _cell(ws, r, c_gpb_rep) if c_gpb_rep else ""
        reg_c = _cell(ws, r, c_region) if c_region else ""
        if _is_dash(reg_c):
            reg_c = ""
        vtb_c = _cell(ws, r, c_vtb) if c_vtb else ""
        if _is_dash(vtb_c):
            vtb_c = ""
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
                content_gpb_rep=gpb_rep,
                content_rsd=rsd,
                content_region=reg_c,
                content_vtb=vtb_c,
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


def _norm_match_snippet(s: str) -> str:
    t = (s or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def lookup_codifier_rsd(
    rows: list[CodifierRow],
    op_code_raw: str,
    aux_code_raw: str,
    description: str,
) -> tuple[str, str]:
    """
    Маппинг для отчёта РСД I*.MSG: код операции + 4-битный код исполнения (0011/1100).
    При нескольких строках (напр. 12214 + 1100) — уточнение по «Содержание РСД» и полю описания в MSG.
    """
    op = _norm_op_code(op_code_raw)
    if not op:
        return "", ""

    candidates = [r for r in rows if _norm_op_code(r.op_code) == op]
    if not candidates:
        return "", ""

    aux = aux_code_raw.strip()
    exec_matched: list[CodifierRow] = []

    if aux:
        a_norm = _norm_exec(aux)
        for r in candidates:
            ex_s = r.exec_code.strip()
            if not ex_s:
                continue
            ex = _norm_exec(ex_s)
            if ex == a_norm or ex_s == aux:
                exec_matched.append(r)

    if not exec_matched:
        for r in candidates:
            if not r.exec_code.strip():
                exec_matched.append(r)
    if not exec_matched:
        exec_matched = list(candidates)

    if len(exec_matched) == 1:
        r0 = exec_matched[0]
        return r0.instruction_type, r0.op_type

    desc_n = _norm_match_snippet(description)
    best: CodifierRow | None = None
    best_score = -1

    for r in exec_matched:
        cr = (r.content_rsd or "").strip()
        if not cr:
            score = 0
        else:
            cr_n = _norm_match_snippet(cr)
            score = 0
            if cr_n and cr_n in desc_n:
                score = len(cr_n)
            elif cr_n and desc_n and (
                desc_n.startswith(cr_n[: min(12, len(cr_n))]) or desc_n.startswith(cr_n)
            ):
                score = max(1, len(cr_n) // 2)
        if score > best_score:
            best_score = score
            best = r

    chosen = best if best is not None and best_score > 0 else exec_matched[0]
    return chosen.instruction_type, chosen.op_type


def lookup_codifier_r01_operation_type(
    rows: list[CodifierRow],
    label: str,
) -> tuple[str, str, str]:
    """
    Маппинг текста «Тип операции» из R-01 xlsx на строку кодификатора.
    Возвращает (тип_поручения, тип_операции, код_операции).
    """
    if not (label or "").strip():
        return "", "", ""

    lab = _norm_match_snippet(label)
    if not lab:
        return "", "", ""

    best: CodifierRow | None = None
    best_score = 0

    for r in rows:
        score = 0
        cr = _norm_match_snippet(r.content_rsd)
        ot = _norm_match_snippet(r.op_type)
        cg = _norm_match_snippet(r.content_gpb)

        for token, weight in ((cr, 3), (ot, 2), (cg, 1)):
            if not token:
                continue
            if token in lab:
                score = max(score, len(token) * weight)
            elif lab in token and len(lab) >= 4:
                score = max(score, min(len(lab), len(token)) * weight)

        if score > best_score:
            best_score = score
            best = r

    if best is None or best_score == 0:
        return "", "", ""

    opc_raw = (best.op_code or "").strip()
    if _is_dash(opc_raw):
        opc_raw = ""
    opc = _norm_op_code(opc_raw) if opc_raw else ""
    return (
        best.instruction_type.strip(),
        best.op_type.strip(),
        opc,
    )


def lookup_codifier_region(
    rows: list[CodifierRow],
    operation_type_label: str,
) -> tuple[str, str, str]:
    """
    Маппинг текста «Тип операции» из отчёта REGION IS*.xls на строку кодификатора.
    Возвращает (тип_поручения, тип_операции, код_операции).
    Приоритет: «Содержание РЕГИОН», затем «Содержание РСД», «Тип операции», «Содержание ГПБ».
    """
    if not (operation_type_label or "").strip():
        return "", "", ""

    lab = _norm_match_snippet(operation_type_label)
    if not lab:
        return "", "", ""

    best: CodifierRow | None = None
    best_score = 0

    for r in rows:
        score = 0
        creg = _norm_match_snippet(r.content_region)
        cr = _norm_match_snippet(r.content_rsd)
        ot = _norm_match_snippet(r.op_type)
        cg = _norm_match_snippet(r.content_gpb)

        for token, weight in ((creg, 4), (cr, 3), (ot, 2), (cg, 1)):
            if not token:
                continue
            if token in lab:
                score = max(score, len(token) * weight)
            elif lab in token and len(lab) >= 4:
                score = max(score, min(len(lab), len(token)) * weight)

        if score > best_score:
            best_score = score
            best = r

    if best is None or best_score == 0:
        return "", "", ""

    opc_raw = (best.op_code or "").strip()
    if _is_dash(opc_raw):
        opc_raw = ""
    opc = _norm_op_code(opc_raw) if opc_raw else ""
    return (
        best.instruction_type.strip(),
        best.op_type.strip(),
        opc,
    )


def _vtb_temp_withdrawal_pick_12002(
    candidates: list[CodifierRow],
    src_blob: str,
    dst_blob: str,
) -> CodifierRow | None:
    """
    Для кода 12002 в кодификаторе две строки (T зачисление / Y списание).
    Правило: участие раздела «Временное изъятие» со стороны списания или зачисления.
    """
    needle = "временное изъятие"
    s_low = _norm_match_snippet(src_blob)
    d_low = _norm_match_snippet(dst_blob)
    has_s = needle in s_low
    has_d = needle in d_low
    if has_d and not has_s:
        for r in candidates:
            if r.instruction_type.strip().upper() == "T":
                return r
            if "зачисление" in r.op_type.lower() and "списание" not in r.op_type.lower():
                return r
    if has_s and not has_d:
        for r in candidates:
            if r.instruction_type.strip().upper() == "Y":
                return r
            if "списание" in r.op_type.lower() and "зачисление" not in r.op_type.lower():
                return r
    return None


def lookup_codifier_vtb(
    rows: list[CodifierRow],
    stage_name: str,
    *,
    src_sections_blob: str = "",
    dst_sections_blob: str = "",
) -> tuple[str, str, str]:
    """
    Маппинг этапа исполнения ВТБ СД (F752 XML) на строку кодификатора.
    Возвращает (тип_поручения, тип_операции, код_операции).
    Приоритет: «Содержание ВТБСД», затем РСД, тип операции, РЕГИОН, ГПБ.
    Для 12002 — уточнение по «Временное изъятие» в текстах разделов src/dst.
    """
    if not (stage_name or "").strip():
        return "", "", ""

    lab = _norm_match_snippet(stage_name)
    if not lab:
        return "", "", ""

    scored: list[tuple[int, CodifierRow]] = []

    for r in rows:
        score = 0
        cv = _norm_match_snippet(r.content_vtb)
        cr = _norm_match_snippet(r.content_rsd)
        ot = _norm_match_snippet(r.op_type)
        creg = _norm_match_snippet(r.content_region)
        cg = _norm_match_snippet(r.content_gpb)

        for token, weight in ((cv, 5), (cr, 3), (ot, 2), (creg, 2), (cg, 1)):
            if not token:
                continue
            if token in lab:
                score = max(score, len(token) * weight)
            elif lab in token and len(lab) >= 4:
                score = max(score, min(len(lab), len(token)) * weight)

        if score > 0:
            scored.append((score, r))

    scored.sort(key=lambda x: -x[0])
    if not scored:
        return "", "", ""

    top_score = scored[0][0]
    best_rows = [r for s, r in scored if s == top_score]

    chosen: CodifierRow | None = None
    if len(best_rows) > 1:
        by_op: dict[str, list[CodifierRow]] = {}
        for r in best_rows:
            k = _norm_op_code(r.op_code) if r.op_code.strip() else ""
            by_op.setdefault(k, []).append(r)
        for op_k, group in by_op.items():
            if op_k == "12002" and len(group) >= 2:
                picked = _vtb_temp_withdrawal_pick_12002(
                    group,
                    src_sections_blob,
                    dst_sections_blob,
                )
                if picked:
                    chosen = picked
                    break
        if chosen is None:
            chosen = best_rows[0]
    else:
        chosen = best_rows[0]

    opc_raw = (chosen.op_code or "").strip()
    if _is_dash(opc_raw):
        opc_raw = ""
    opc = _norm_op_code(opc_raw) if opc_raw else ""

    # повторная попытка для 12002 если одна строка с кодом 12002 но не та сторона
    if opc == "12002":
        cands_12002 = [r for r in rows if _norm_op_code(r.op_code) == "12002"]
        if len(cands_12002) >= 2:
            picked = _vtb_temp_withdrawal_pick_12002(
                cands_12002,
                src_sections_blob,
                dst_sections_blob,
            )
            if picked and picked is not chosen:
                # если score выбрал не ту строку — заменить при явном temp withdrawal
                s_low = _norm_match_snippet(src_sections_blob)
                d_low = _norm_match_snippet(dst_sections_blob)
                if ("временное изъятие" in s_low) ^ ("временное изъятие" in d_low):
                    chosen = picked
                    opc = _norm_op_code(chosen.op_code)

    return (
        chosen.instruction_type.strip(),
        chosen.op_type.strip(),
        opc,
    )


def normalize_svod_document_op_type_display(op_type: str) -> str:
    """
    Приводит «Тип операции» к виду как на эталонном скрине Excel:
    «Документы - зачисление» (пробел — дефис — пробел), вместо длинного тире «—».
    """
    t = (op_type or "").strip()
    if not t:
        return t
    t = t.replace("—", "-").replace("–", "-")
    t = re.sub(r"\s*-\s*", " - ", t)
    return t.strip()


def lookup_document_op_type_by_instruction(
    rows: list[CodifierRow],
    instruction_type_raw: str,
) -> str:
    """
    Для строк СВОД из отчёта D: тип поручения (instruction type) DF/DP и пустой код операции
    в строке кодификатора «Документы …». Возвращает нормализованный «Тип операции» или пусто.
    """
    inst = instruction_type_raw.strip().upper()
    if inst not in ("DF", "DP"):
        return ""

    for r in rows:
        if r.op_code.strip():
            continue
        if r.instruction_type.strip().upper() != inst:
            continue
        ot = r.op_type.strip()
        if not ot:
            continue
        if "документ" not in ot.lower():
            continue
        return normalize_svod_document_op_type_display(ot)

    return ""


def fallback_document_op_type(instruction_type_raw: str) -> str:
    """Если в «Коды» нет строки для DF/DP-документов — эталонные подписи колонки D."""
    inst = instruction_type_raw.strip().upper()
    if inst == "DF":
        return "Документы - зачисление"
    if inst == "DP":
        return "Документы - списание"
    return ""
