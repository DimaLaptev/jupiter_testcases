"""Парсинг текстовых отчётов D*.MSG (DOC_INSTRUCT)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DMsgHeader:
    raw: dict[str, str]

    def get(self, key: str, default: str = "") -> str:
        return self.raw.get(key, default)


@dataclass
class DMsgDataRow:
    depo_col: str
    ngri: str
    ref_contract: str
    doc_type: str
    doc_num: str
    doc_date: str
    extra: str


@dataclass
class DMsgFile:
    path: Path
    header: DMsgHeader
    rows: list[DMsgDataRow]


def read_text_with_encoding(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


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


def _normalize_data_row(parts: list[str]) -> DMsgDataRow:
    while parts and parts[-1] == "":
        parts = parts[:-1]
    padded: list[str] = (parts + [""] * 7)[:7]
    return DMsgDataRow(
        depo_col=padded[0].strip(),
        ngri=padded[1].strip(),
        ref_contract=padded[2].strip(),
        doc_type=padded[3].strip(),
        doc_num=padded[4].strip(),
        doc_date=padded[5].strip(),
        extra=padded[6].strip(),
    )


def parse_d_msg_text(text: str) -> tuple[DMsgHeader, list[DMsgDataRow]]:
    lines = text.splitlines()
    raw_header, idx = _parse_header_lines(lines, 0)
    header = DMsgHeader(raw=raw_header)
    rows: list[DMsgDataRow] = []
    while idx < len(lines):
        line = lines[idx]
        idx += 1
        if not line.strip():
            continue
        parts = line.rstrip("\r\n").split(";")
        rows.append(_normalize_data_row(parts))
    return header, rows


def parse_d_msg_file(path: Path) -> DMsgFile:
    text = read_text_with_encoding(path)
    header, rows = parse_d_msg_text(text)
    return DMsgFile(path=path, header=header, rows=rows)


def display_doc_date(raw: str) -> str:
    if raw.strip() in ("", "01.01.1900"):
        return ""
    return raw.strip()


def depo_num_for_lookup(header: DMsgHeader, row: DMsgDataRow) -> str:
    h = header.get("DepoNum").strip()
    if h:
        return h
    return row.depo_col.strip()
