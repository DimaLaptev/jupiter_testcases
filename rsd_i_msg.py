"""Строки данных отчёта РСД I*.MSG (semicolon-separated), см. scrins/RSD_MSG_example.png."""

from __future__ import annotations

# Минимальная длина строки: индексы 0..14 и четыре флага в конце
RSD_ROW_MIN_LEN = 15
GPB_I_ROW_MIN_LEN = 18

TECHNICAL_SECTION_CODE = "210000"


class RsdIField:
    CLIENT_NAME = 0
    ACCOUNT_F = 1
    SECTION_G = 2
    INTERNAL_ID = 3
    NRN = 4
    OP_CODE = 5
    QTY = 6
    DESCRIPTION = 7
    DEPARTMENT = 8


def _norm_section_code(s: str) -> str:
    t = str(s).strip()
    try:
        return str(int(float(t)))
    except (ValueError, TypeError):
        return t


def is_rsd_technical_row(parts: list[str]) -> bool:
    """Строки «в пути» с разделом 210000 — не попадают в СВОД."""
    if len(parts) <= RsdIField.SECTION_G:
        return False
    return _norm_section_code(parts[RsdIField.SECTION_G]) == _norm_section_code(
        TECHNICAL_SECTION_CODE,
    )


def rsd_execution_code(parts: list[str]) -> str:
    """Четыре последних поля 0/1 → строка вида 0011, 1100."""
    if len(parts) < 4:
        return ""
    tail = [p.strip() for p in parts[-4:]]
    if len(tail) != 4 or any(t not in ("0", "1") for t in tail):
        return ""
    return "".join(tail)


def is_rsd_i_row(parts: list[str]) -> bool:
    """Отличие от ГПБ: меньше полей, последние четыре — биты кода исполнения."""
    if len(parts) < RSD_ROW_MIN_LEN:
        return False
    if len(parts) >= GPB_I_ROW_MIN_LEN:
        return False
    return bool(rsd_execution_code(parts))


def is_gpb_i_row(parts: list[str]) -> bool:
    """Табличная строка формата ГПБ INSTRUCTIONS (≥18 полей, код исполнения — число в конце)."""
    return len(parts) >= GPB_I_ROW_MIN_LEN


def rsd_debit_credit_columns(
    exec_four: str,
    f_acc: str,
    g_sec: str,
    op_type: str,
) -> tuple[str, str, str, str]:
    """
    Правило РСД: один счёт из отчёта — зачисление (credit) только J/K, списание (debit) только H/I.
    exec_four: 0011 — зачисление, 1100 — списание.
    """
    if exec_four == "0011":
        return "", "", f_acc, g_sec
    if exec_four == "1100":
        return f_acc, g_sec, "", ""

    ot = (op_type or "").lower()
    if "зачисление" in ot:
        return "", "", f_acc, g_sec
    if "списание" in ot:
        return f_acc, g_sec, "", ""

    return "", "", "", ""


def rsd_exec_four_from_operation_type_label(label: str) -> str:
    """
    Для отчёта R-01 xlsx: по тексту «Тип операции» — псевдо-код 0011 (зачисление) / 1100 (списание)
    для вызова rsd_debit_credit_columns.
    """
    t = (label or "").lower()
    if "зачисление цб" in t:
        return "0011"
    if "списание цб" in t:
        return "1100"
    if "зачисление" in t and "списание" not in t:
        return "0011"
    if "списание" in t and "зачисление" not in t:
        return "1100"
    return ""
