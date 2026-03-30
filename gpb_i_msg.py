"""Парсинг отчётов I*.MSG (INSTRUCTIONS). Образец: scrins/GBP_I_example.jpg."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gpb_d_msg import read_text_with_encoding


# Индексы полей (0-based) по строке `I_102_20260115_00248.MSG` (GBP_I_example.jpg)
# 102;5405426;;12005;18;33563;233;25;98070.111;10934;233;0;98040.000;1;102459261;ZKL...;НГРИ;10000
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


@dataclass
class IMsgDataRow:
    parts: list[str]

    def get(self, idx: int, default: str = "") -> str:
        if 0 <= idx < len(self.parts):
            return self.parts[idx].strip()
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
