"""Парсинг отчётов I*.MSG (INSTRUCTIONS). Образец: scrins/GBP_I_example.jpg."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gpb_d_msg import read_text_with_encoding


# Индексы полей (0-based) по строке `I_102_20260115_00248.MSG` (GBP_I_example.jpg)
# 102;5405426;;12005;18;33563;233;25;98070.111;10934;233;0;98040.000;1;102459261;ZKL...;НГРИ;10000
# H/I — счёт и раздел списания (debit); J/K — зачисления (credit); см. build_svod_row (svod_excel).
#
# «Компактная» строка (без пустого зарезервированного поля и без F/G в MSG), напр.:
# 102;5406274;12212;7;26716;204;70;98040.000;32169;0;… — код оп. с инд. 2, H/I с 4–5, J/K с 8–9.
#
# «Выгрузка в Excel» при пустом [2] (как I_102_20260128_00109.MSG): те же 4–5 и 8–9 для колонок
# списание/зачисление в СВОД, при этом F/G остаются на 5–6 для поля F сообщения (см. resolve).
GPB_I_ROW_MIN_LEN = 18
GPB_I_ROW_MIN_LEN_COMPACT = 17


class IField:
    DEPO = 0
    INTERNAL_NO = 1
    RESERVED = 2
    OP_CODE = 3
    AUX_CODE = 4
    F_DEPO_ACC = 5
    G_DEPO_SEC = 6
    H_DEBIT_ACC = 7
    I_DEBIT_SEC = 8
    J_CREDIT_ACC = 9
    K_CREDIT_SEC = 10
    EXTRA1 = 11
    EXTRA2 = 12
    QTY = 13
    ID_NUM = 14
    BASIS = 15
    NRN = 16
    EXEC_CODE = 17  # последнее поле


@dataclass
class IMsgHeader:
    raw: dict[str, str]

    def get(self, key: str, default: str = "") -> str:
        return self.raw.get(key, default)


def _gpb_dom_sheet_excel_format(parts: list[str]) -> bool:
    """
    True — формат как в выгрузке I.MSG в Excel (ДОМ.РФ): [2] пустой, пары списание/зачисление
    в физических индексах 4–5 и 8–9. Отличие от «эталонной» строки ГПБ: K (логич. 10) обычно 0 или 1.
    """
    if len(parts) <= 10:
        return False
    if parts[2].strip():
        return False
    try:
        k_std = int(float((parts[10] or "0").strip() or 0))
    except (ValueError, TypeError):
        return False
    return k_std <= 1


def gpb_i_row_layout(parts: list[str]) -> str:
    """
    standard — эталон GBP_I_example (H–K с инд. 7–10).
    compact — нет пустого [2], нет F/G в привычных позициях (код оп. с [2]).
    sheet — пустой [2], но списание/зачисление для СВОД с [4–5] и [8–9] (как на скрине Excel).
    """
    if len(parts) < 3:
        return "standard"
    if parts[2].strip():
        return "compact"
    if _gpb_dom_sheet_excel_format(parts):
        return "sheet"
    return "standard"


def gpb_i_resolve_field_index(parts: list[str], std_index: int) -> int | None:
    """
    Сопоставляет «логический» индекс IField со смещением в фактической строке.
    В compact F/G в файле нет — get вернёт пусто; хвост со сдвигом −1 относительно standard.
    """
    layout = gpb_i_row_layout(parts)
    if layout == "standard":
        if std_index < 0 or std_index >= len(parts):
            return None
        return std_index

    if layout == "sheet":
        if std_index in (IField.DEPO, IField.INTERNAL_NO, IField.RESERVED):
            return std_index if std_index < len(parts) else None
        if std_index == IField.OP_CODE:
            return 3 if 3 < len(parts) else None
        if std_index == IField.AUX_CODE:
            return 4 if 4 < len(parts) else None
        if std_index in (IField.F_DEPO_ACC, IField.G_DEPO_SEC):
            return std_index if std_index < len(parts) else None
        if std_index == IField.H_DEBIT_ACC:
            return 4 if 4 < len(parts) else None
        if std_index == IField.I_DEBIT_SEC:
            return 5 if 5 < len(parts) else None
        if std_index == IField.J_CREDIT_ACC:
            return 8 if 8 < len(parts) else None
        if std_index == IField.K_CREDIT_SEC:
            return 9 if 9 < len(parts) else None
        if std_index >= IField.EXTRA1:
            ri = std_index - 1
            return ri if 0 <= ri < len(parts) else None
        return None

    if std_index in (IField.DEPO, IField.INTERNAL_NO):
        return std_index if std_index < len(parts) else None
    if std_index == IField.RESERVED:
        return None
    if std_index == IField.OP_CODE:
        return 2 if 2 < len(parts) else None
    if std_index == IField.AUX_CODE:
        return 3 if 3 < len(parts) else None
    if std_index in (IField.F_DEPO_ACC, IField.G_DEPO_SEC):
        return None
    if std_index == IField.H_DEBIT_ACC:
        return 4 if 4 < len(parts) else None
    if std_index == IField.I_DEBIT_SEC:
        return 5 if 5 < len(parts) else None
    if std_index == IField.J_CREDIT_ACC:
        return 8 if 8 < len(parts) else None
    if std_index == IField.K_CREDIT_SEC:
        return 9 if 9 < len(parts) else None
    if std_index >= IField.EXTRA1:
        ri = std_index - 1
        return ri if 0 <= ri < len(parts) else None
    return None


@dataclass
class IMsgDataRow:
    parts: list[str]

    def get(self, idx: int, default: str = "") -> str:
        ri = gpb_i_resolve_field_index(self.parts, idx)
        if ri is None:
            return default
        if 0 <= ri < len(self.parts):
            return self.parts[ri].strip()
        return default


@dataclass
class IMsgFile:
    path: Path
    header: IMsgHeader
    rows: list[IMsgDataRow]


def _parse_header_lines(lines: list[str], start: int) -> tuple[dict[str, str], int]:
    header: dict[str, str] = {}
    i = start
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            break
        if ":" in line:
            key, _, value = line.partition(":")
            header[key.strip()] = value.strip()
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return header, i


def _split_row(line: str) -> list[str]:
    line = line.rstrip("\r\n")
    parts = line.split(";")
    while parts and parts[-1] == "":
        parts.pop()
    return parts


def parse_i_msg_text(text: str) -> tuple[IMsgHeader, list[IMsgDataRow]]:
    lines = text.splitlines()
    raw_header, idx = _parse_header_lines(lines, 0)
    header = IMsgHeader(raw=raw_header)
    rows: list[IMsgDataRow] = []
    while idx < len(lines):
        line = lines[idx]
        idx += 1
        if not line.strip():
            continue
        parts = _split_row(line)
        if not parts:
            continue
        rows.append(IMsgDataRow(parts=parts))
    return header, rows


def parse_i_msg_file(path: Path) -> IMsgFile:
    text = read_text_with_encoding(path)
    header, rows = parse_i_msg_text(text)
    return IMsgFile(path=path, header=header, rows=rows)


def execution_code_int(row: IMsgDataRow) -> int | None:
    """Код исполнения — последнее поле строки (например 10000)."""
    if not row.parts:
        return None
    last = row.parts[-1].strip()
    if not last:
        return None
    try:
        return int(float(last))
    except (ValueError, TypeError):
        return None


def passes_execution_filter(row: IMsgDataRow, min_code: int = 10000) -> bool:
    ec = execution_code_int(row)
    if ec is None:
        return False
    return ec >= min_code


def is_gpb_i_row(parts: list[str]) -> bool:
    """Табличная строка ГПБ INSTRUCTIONS: полная (≥18 полей) или компактная (≥17, без [2] и без F/G)."""
    layout = gpb_i_row_layout(parts)
    if layout == "compact":
        return len(parts) >= GPB_I_ROW_MIN_LEN_COMPACT
    return len(parts) >= GPB_I_ROW_MIN_LEN


def compute_depot_section(
    f: str,
    g: str,
    h: str,
    i: str,
    j: str,
    k: str,
) -> str:
    """
    §4.4 ТЗ: если F совпадает с H — раздел из I; если F с J — из K; иначе G.
    Сравнение счетов — по числовому значению при возможности.
    """

    def norm_acc(x: str) -> str:
        s = str(x).strip()
        if not s:
            return ""
        try:
            return str(int(float(s)))
        except (ValueError, TypeError):
            return s

    fn, hn, jn = norm_acc(f), norm_acc(h), norm_acc(j)
    if fn and fn == hn:
        return str(i).strip()
    if fn and fn == jn:
        return str(k).strip()
    return str(g).strip()
