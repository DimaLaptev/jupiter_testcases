"""Парсинг GPB R_102_*.MSG (ReportType:REMAINDERS)."""

from __future__ import annotations

import re
from pathlib import Path

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.msg_grid import cell_at, msg_path_to_rows, sheet_a8_empty

from models import DepoReportRow, SourceKind


def _parse_header(rows: list[list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows[:12]:
        if len(row) != 1:
            continue
        line = (row[0] or "").strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip()
    return out


def _field(row: list[str], idx: int) -> str:
    if idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def parse_gpb_r_msg(path: Path) -> list[DepoReportRow]:
    rows = msg_path_to_rows(path)
    if not sheet_a8_empty(rows):
        return []

    header = _parse_header(rows)
    source_name = path.name
    if header.get("ReportName"):
        source_name = header["ReportName"]

    out: list[DepoReportRow] = []
    for r_idx in range(8, len(rows)):
        row = rows[r_idx]
        if not row or not any((c or "").strip() for c in row):
            continue
        # Одна ячейка с ; или уже split
        if len(row) == 1 and ";" in (row[0] or ""):
            parts = (row[0] or "").split(";")
        else:
            parts = row

        if len(parts) < 9:
            continue
        ngri = _field(parts, 8)
        if not ngri:
            continue

        status = _field(parts, 9) if len(parts) >= 10 else "На хранении"
        out.append(
            DepoReportRow(
                source_kind=SourceKind.GPB,
                source_file=source_name,
                schet_depo=_field(parts, 1),
                razdel_scheta=_field(parts, 2),
                ngri_v_depo=ngri,
                status=status or "На хранении",
            ),
        )
    return out


def _unique_paths(directory: Path, pattern: str) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in sorted(directory.glob(pattern)):
        key = str(p.resolve()).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def iter_gpb_rows(directory: Path) -> list[DepoReportRow]:
    if not directory.is_dir():
        return []
    result: list[DepoReportRow] = []
    for path in _unique_paths(directory, "*.MSG"):
        if re.match(r"R_\d+_", path.name, re.IGNORECASE):
            result.extend(parse_gpb_r_msg(path))
    return result
