"""REGION: формат 1 (xml в []) и формат 2 (VL####.xls) — см. memory/DO_column_mapping.md."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets
from sql_upload.values import cell_to_sql_value

from models import DepoReportRow, SourceKind

_BRACKET_ACCOUNT_RE = re.compile(r"^\[([^\]]+)\]")
_VL_STEM_RE = re.compile(r"^VL[\w]+$", re.IGNORECASE)


def _xml_local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _xml_attr(element: ET.Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if key == name or key.endswith(f"}}{name}"):
            return value
    return None


def _read_xml_root(path: Path) -> ET.Element | None:
    """SpreadsheetML Region часто в UTF-16; ET.parse(path) без encoding может не сработать."""
    raw = path.read_bytes()
    if not raw.strip():
        return None
    for enc in ("utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "cp1251"):
        try:
            return ET.fromstring(raw.decode(enc))
        except (UnicodeDecodeError, ET.ParseError):
            continue
    try:
        return ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None


def _read_spreadsheet_ml(path: Path) -> list[list[str]]:
    root = _read_xml_root(path)
    if root is None:
        return []

    rows_out: list[list[str]] = []
    for row_el in root.iter():
        if _xml_local_tag(row_el.tag) != "Row":
            continue
        row: list[str] = []
        col_idx = 0
        for cell in row_el:
            if _xml_local_tag(cell.tag) != "Cell":
                continue
            index_attr = _xml_attr(cell, "Index")
            if index_attr:
                target = int(index_attr) - 1
                while col_idx < target:
                    row.append("")
                    col_idx += 1
            val = ""
            for child in cell:
                if _xml_local_tag(child.tag) == "Data":
                    val = (child.text or "").strip()
                    break
            row.append(val)
            col_idx += 1
        if any(c.strip() for c in row):
            rows_out.append(row)
    return rows_out


def account_from_bracket_filename(path: Path) -> str | None:
    """[VL0032][][IS...].xml -> VL0032"""
    m = _BRACKET_ACCOUNT_RE.match(path.name)
    if not m:
        return None
    acc = (m.group(1) or "").strip()
    return acc or None


def is_format1_path(path: Path) -> bool:
    if path.suffix.lower() != ".xml":
        return False
    return account_from_bracket_filename(path) is not None


def is_format2_path(path: Path) -> bool:
    return _VL_STEM_RE.match(path.stem) and path.suffix.lower() in (".xls", ".xlsx")


def read_region_sheet_rows(path: Path) -> list[list[str]]:
    """Чтение .xml (SpreadsheetML) или Excel."""
    if path.suffix.lower() == ".xml":
        head = path.read_bytes()[:4]
        if head[:2] == b"PK":
            sheets = read_workbook_sheets(path)
            if sheets:
                return sheets[0][1]
        return _read_spreadsheet_ml(path)
    sheets = read_workbook_sheets(path)
    if sheets:
        return sheets[0][1]
    return []


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().casefold())


def _header_col_map(sheet_rows: list[list[str]], header_row: int = 1) -> dict[str, int]:
    if header_row - 1 >= len(sheet_rows):
        return {}
    header = sheet_rows[header_row - 1]
    return {_norm_header(h): i for i, h in enumerate(header) if (h or "").strip()}


def _cell_by_header(row: list[str], col_map: dict[str, int], *names: str) -> str:
    for name in names:
        idx = col_map.get(_norm_header(name))
        if idx is None:
            continue
        if idx < len(row):
            v = cell_to_sql_value(row[idx])
            if v:
                return v
    return ""


def _find_ngri_header(col_map: dict[str, int]) -> int | None:
    for key, idx in col_map.items():
        if key in ("registrationnumber", "ngri", "нгри"):
            return idx
        if "registration" in key and "number" in key:
            return idx
        if "гос" in key and "рег" in key:
            return idx
    return None


def parse_format1_xml(path: Path, sheet_rows: list[list[str]] | None = None) -> list[DepoReportRow]:
    """
    Формат 1: [VL0032][][IS...].xml, шапка строка 1, данные с 2.
    DepoAccount, DivisionName, AgreementNumber, FIO; NGRI — RegistrationNumber или аналог.
    """
    rows = sheet_rows if sheet_rows is not None else read_region_sheet_rows(path)
    if not rows:
        return []

    col_map = _header_col_map(rows, 1)
    if "depoaccount" not in col_map and not account_from_bracket_filename(path):
        return []

    schet_file = account_from_bracket_filename(path) or ""
    ngri_idx = _find_ngri_header(col_map)
    last = last_row_in_column(rows, 1)
    out: list[DepoReportRow] = []

    for r in range(2, last + 1):
        if r - 1 >= len(rows):
            break
        row = rows[r - 1]
        if not any((c or "").strip() for c in row):
            continue

        schet = _cell_by_header(row, col_map, "DepoAccount") or schet_file
        division = _cell_by_header(row, col_map, "DivisionName", "DivisionCode")
        ngri = ""
        if ngri_idx is not None and ngri_idx < len(row):
            ngri = cell_to_sql_value(row[ngri_idx]) or ""
        if not ngri:
            ngri = _cell_by_header(
                row,
                col_map,
                "RegistrationNumber",
                "StateRegistrationNumber",
                "MortgageRegistrationNumber",
            )
        if not ngri:
            continue

        kd = _cell_by_header(row, col_map, "AgreementNumber")
        fio = _cell_by_header(row, col_map, "FIO")

        out.append(
            DepoReportRow(
                source_kind=SourceKind.REGION,
                source_file=path.name,
                schet_depo=schet,
                razdel_scheta=division,
                ngri_v_depo=ngri,
                status=None,
                nomer_kd=kd or None,
                fio=fio or None,
            ),
        )
    return out


def _find_format2_header_row(sheet_rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    for r in range(1, min(20, len(sheet_rows) + 1)):
        cmap = _header_col_map(sheet_rows, r)
        keys = set(cmap.keys())
        if "состояние" in keys and "нгри" in keys:
            return r, cmap
    return None


def parse_format2_vl_xls(path: Path, sheet_rows: list[list[str]] | None = None) -> list[DepoReportRow]:
    """
    Формат 2: VL0089.XLS — «Отчет об остатках закладных».
    A Состояние, B НГРИ, E Номер КД, H Раздел счета ДЕПО; счёт из имени файла.
    """
    rows = sheet_rows if sheet_rows is not None else read_region_sheet_rows(path)
    if not rows:
        return []

    found = _find_format2_header_row(rows)
    if found is None:
        return []

    header_row, col_map = found
    schet = path.stem.upper()
    data_start = header_row + 1
    last = last_row_in_column(rows, col_map.get("нгри", 2) + 1)
    out: list[DepoReportRow] = []

    for r in range(data_start, last + 1):
        if r - 1 >= len(rows):
            break
        row = rows[r - 1]
        ngri = _cell_by_header(row, col_map, "НГРИ", "NGRI")
        if not ngri:
            continue
        status = _cell_by_header(row, col_map, "Состояние", "Status")
        kd = _cell_by_header(
            row,
            col_map,
            "Номер кредитного договора",
            "AgreementNumber",
        )
        razdel = _cell_by_header(row, col_map, "Раздел счета ДЕПО", "DivisionName")
        fio = _cell_by_header(row, col_map, "Депонент", "FIO")

        out.append(
            DepoReportRow(
                source_kind=SourceKind.REGION,
                source_file=path.name,
                schet_depo=schet,
                razdel_scheta=razdel,
                ngri_v_depo=ngri,
                status=status or None,
                nomer_kd=kd or None,
                fio=fio or None,
            ),
        )
    return out


def build_status_by_ngri(format2_rows: list[DepoReportRow]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in format2_rows:
        key = (row.ngri_v_depo or "").strip().casefold()
        if key and row.status:
            out[key] = row.status
    return out


def apply_status_from_format2(
    rows: list[DepoReportRow],
    status_by_ngri: dict[str, str],
) -> None:
    for row in rows:
        if row.status:
            continue
        key = (row.ngri_v_depo or "").strip().casefold()
        if key and key in status_by_ngri:
            row.status = status_by_ngri[key]
