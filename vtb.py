"""Парсинг выписки ВТБ СД."""

from __future__ import annotations

from pathlib import Path

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets
from sql_upload.values import cell_to_sql_value

from models import DepoReportRow, SourceKind


def _parse_vtb_sheet(sheet_rows: list[list[str]], source_file: str) -> list[DepoReportRow]:
    if cell_at(sheet_rows, 11, 6) != "Залогодатель":
        return []

    schet = cell_to_sql_value(cell_at(sheet_rows, 6, 7)) or ""
    last_row = last_row_in_column(sheet_rows, 3)
    out: list[DepoReportRow] = []

    for r in range(13, last_row + 1):
        section_text = cell_at(sheet_rows, r, 2)
        ngri = cell_at(sheet_rows, r, 9)
        if not ngri.strip() and not section_text.strip():
            continue
        if not ngri.strip():
            continue

        data_priema = cell_at(sheet_rows, r, 5) or None
        fio = cell_at(sheet_rows, r, 6) or None
        nomer_kd = None
        basis = cell_at(sheet_rows, r, 8)
        if basis.strip():
            nomer_kd = basis.strip()

        razdel = section_text.strip()
        if " - " in razdel:
            razdel = razdel.split(" - ", 1)[0].strip()
        elif razdel.startswith("["):
            parts = razdel.split("]", 1)
            if len(parts) > 1:
                razdel = parts[0].lstrip("[").strip()

        out.append(
            DepoReportRow(
                source_kind=SourceKind.VTBSD,
                source_file=source_file,
                schet_depo=schet,
                razdel_scheta=razdel or section_text.strip(),
                ngri_v_depo=ngri.strip(),
                status=None,
                data_priema=data_priema,
                fio=fio,
                nomer_kd=nomer_kd,
                section_text=section_text.strip(),
            ),
        )
    return out


def iter_vtb_rows(directory: Path) -> list[DepoReportRow]:
    if not directory.is_dir():
        return []
    out: list[DepoReportRow] = []
    for path in sorted(directory.rglob("*.xlsx")) + sorted(directory.rglob("*.xls")):
        if path.name.startswith("~"):
            continue
        for _name, sheet_rows in read_workbook_sheets(path):
            out.extend(_parse_vtb_sheet(sheet_rows, path.name))
    return out
