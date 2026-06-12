"""Парсинг RSD R_*.MSG (ReportType:R)."""

from __future__ import annotations

import re
from pathlib import Path

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.msg_grid import msg_path_to_rows, sheet_a7_empty

from models import DepoReportRow, SourceKind


def _parse_header(rows: list[list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows[:10]:
        if len(row) != 1:
            continue
        line = (row[0] or "").strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip()
    return out


def _field(parts: list[str], idx: int) -> str:
    if idx >= len(parts):
        return ""
    return (parts[idx] or "").strip()


def parse_rsd_r_msg(path: Path) -> list[DepoReportRow]:
    rows = msg_path_to_rows(path)
    if not sheet_a7_empty(rows):
        return []

    header = _parse_header(rows)
    source_name = header.get("ReportName") or path.name

    out: list[DepoReportRow] = []
    for r_idx in range(7, len(rows)):
        row = rows[r_idx]
        if not row or not any((c or "").strip() for c in row):
            continue
        if len(row) == 1 and ";" in (row[0] or ""):
            parts = (row[0] or "").split(";")
        else:
            parts = row

        if len(parts) < 6:
            continue
        ngri = _field(parts, 5)
        if not ngri:
            continue

        out.append(
            DepoReportRow(
                source_kind=SourceKind.RSD_MSG,
                source_file=source_name,
                schet_depo=_field(parts, 1),
                razdel_scheta=_field(parts, 2),
                ngri_v_depo=ngri,
                status="На хранении",
            ),
        )
    return out


def iter_rsd_msg_rows(directory: Path) -> list[DepoReportRow]:
    if not directory.is_dir():
        return []
    result: list[DepoReportRow] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.MSG")):
        key = str(path.resolve()).casefold()
        if key in seen:
            continue
        seen.add(key)
        if re.match(r"R_\d+_", path.name, re.IGNORECASE):
            result.extend(parse_rsd_r_msg(path))
    return result
