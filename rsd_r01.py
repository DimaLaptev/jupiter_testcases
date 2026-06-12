"""Парсинг RSD R-01 xlsx из RSD_EXL."""

from __future__ import annotations

from pathlib import Path

from path_bootstrap import bootstrap

bootstrap()

from rsd_r01_xlsx import parse_r01_xlsx, parse_section_code

from models import DepoReportRow, SourceKind


def iter_rsd_r01_rows(directory: Path) -> list[DepoReportRow]:
    if not directory.is_dir():
        return []
    out: list[DepoReportRow] = []
    for path in sorted(directory.rglob("*.xlsx")) + sorted(directory.rglob("*.XLSX")):
        if path.name.startswith("~"):
            continue
        parsed = parse_r01_xlsx(path)
        if parsed is None:
            continue
        for row in parsed.rows:
            ngri = (row.reg_number or "").strip()
            if not ngri:
                continue
            out.append(
                DepoReportRow(
                    source_kind=SourceKind.RSD_XLS,
                    source_file=path.name,
                    schet_depo=parsed.depo_account,
                    razdel_scheta=parse_section_code(row.section_raw),
                    ngri_v_depo=ngri,
                    status="На хранении",
                    data_priema=row.exec_date_display or None,
                ),
            )
    return out
