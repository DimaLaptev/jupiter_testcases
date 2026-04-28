"""Парсинг отчётов I*.MSG (INSTRUCTIONS). Образец: scrins/GBP_I_example.jpg."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from gpb_d_msg import read_text_with_encoding


def normalize_ngri_for_match(raw: str) -> str:
    """Единая нормализация НГРИ для сопоставления D↔I (пробелы (whitespace))."""
    s = (raw or "").strip()
    s = re.sub(r"\s+", " ", s, flags=re.UNICODE)
    return s


def gpb_instruction_pair_key(path: Path) -> str | None:
    """
    Ключ пары I/D по имени файла: I_102_20260114_00070.MSG и D_102_20260114_00070.MSG → 102_20260114_00070.
    """
    stem = path.stem
    m = re.match(r"^[iIdD]_(.+)$", stem)
    if not m:
        return None
    return m.group(1).strip()


# Строка данных I*.MSG ГПБ (INSTRUCTIONS): после split(';') не менее 18 полей. Разделение ГПБ/РСД — по каталогу
# входа в `fill_svod_from_i_msg.py` (`--input-dir` vs `--input-dir-rsd`). Поле [2] может быть пустым или заполненным;
# код операции и блоки 5–6 / 9–10 считаются с фиксированных позиций (см. `gpb_i_resolve_field_index`).
# Пример: 102;5406274;;12212;7;26716;204;70;98040.000;32169;0;0;98000.100;1;…;10000
#
# Логические имена IField (§ ТЗ) сопоставляются с физическими индексами (0-based):
# OP_CODE→3, AUX→4, F/G счёта депо→5–6; для колонок СВОД «списание/зачисление» те же 5–6 и 9–10
# (H/I дублируют F/G по позициям; J/K на 9–10). Хвост с 11 — как в эталонной длине строки.
GPB_I_ROW_MIN_LEN = 18


class IField:
    """Именованные поля строки; физические индексы через `gpb_i_resolve_field_index`."""
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


def gpb_i_resolve_field_index(parts: list[str], std_index: int) -> int | None:
    """
    Единая раскладка ГПБ I*.MSG (выгрузка Excel): пустой резерв [2], списание в СВОД 5–6, зачисление 9–10.
    """
    if std_index < 0:
        return None
    if std_index in (IField.DEPO, IField.INTERNAL_NO, IField.RESERVED):
        return std_index if std_index < len(parts) else None
    if std_index == IField.OP_CODE:
        return 3 if 3 < len(parts) else None
    if std_index == IField.AUX_CODE:
        return 4 if 4 < len(parts) else None
    if std_index == IField.F_DEPO_ACC:
        return 5 if 5 < len(parts) else None
    if std_index == IField.G_DEPO_SEC:
        return 6 if 6 < len(parts) else None
    if std_index == IField.H_DEBIT_ACC:
        return 5 if 5 < len(parts) else None
    if std_index == IField.I_DEBIT_SEC:
        return 6 if 6 < len(parts) else None
    if std_index == IField.J_CREDIT_ACC:
        return 9 if 9 < len(parts) else None
    if std_index == IField.K_CREDIT_SEC:
        return 10 if 10 < len(parts) else None
    if std_index >= IField.EXTRA1:
        return std_index if std_index < len(parts) else None
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
    """Достаточно полей для разбора строки табличной части ГПБ INSTRUCTIONS (маршрут ГПБ/РСД — по каталогу файла в скрипте)."""
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
