"""Парсинг отчётов REGION: формат 1/2 + legacy balance (40-col / Region2)."""

from __future__ import annotations

import re
from pathlib import Path

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets
from sql_upload.loaders.region2 import _match_header_columns
from sql_upload.values import cell_to_sql_value

from extract.region_formats import (
    apply_status_from_format2,
    build_status_by_ngri,
    is_format1_path,
    is_format2_path,
    parse_format1_xml,
    parse_format2_vl_xls,
    read_region_sheet_rows,
)
from models import DepoReportRow, SourceKind


def _division_to_section(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""
    m = re.match(r"^(\d+)", s)
    if m:
        return m.group(1)
    return s


def _row_from_region2(sheet_rows: list[list[str]], source_file: str) -> list[DepoReportRow]:
    a1 = cell_at(sheet_rows, 1, 1)
    a2 = cell_at(sheet_rows, 2, 1)
    if a1 != "/DEPOACCOUNT_BALANCE_REPORT" and a2 != "/ReportBody/OperationInfo/Date":
        return []
    if len(sheet_rows) < 2:
        return []

    col_indices = _match_header_columns(sheet_rows[1])
    if col_indices is None:
        return []

    last_row = last_row_in_column(sheet_rows, 1)
    out: list[DepoReportRow] = []
    for r in range(3, last_row + 1):
        if r - 1 >= len(sheet_rows):
            break
        row = sheet_rows[r - 1]
        values = [cell_to_sql_value(row[i] if i < len(row) else "") for i in col_indices]
        if not any(v for v in values):
            continue
        schet, division, _qty, kd, ngri = values
        if not ngri:
            continue
        out.append(
            DepoReportRow(
                source_kind=SourceKind.REGION,
                source_file=source_file,
                schet_depo=schet or "",
                razdel_scheta=_division_to_section(division or ""),
                ngri_v_depo=ngri,
                status=None,
                nomer_kd=kd or None,
            ),
        )
    return out


def _row_from_region_v1(sheet_rows: list[list[str]], source_file: str) -> list[DepoReportRow]:
    if cell_at(sheet_rows, 1, 1) != "/DEPOACCOUNT_BALANCE_REPORT":
        return []

    header = sheet_rows[1] if len(sheet_rows) > 1 else []
    col_indices = _match_header_columns(header)
    if col_indices is not None:
        return _row_from_region2(sheet_rows, source_file)

    paths_map = {
        "account": "/ReportHeader/DepoAccount/DepoAccount",
        "division": "/ReportBody/PositionList/Position/DivisionList/Division/DivisionInfo/DivisionName",
        "ngri": "/ReportBody/PositionList/Position/PositionInfo/Mortgage/RegistrationNumber",
        "kd": "/ReportBody/PositionList/Position/PositionInfo/Mortgage/AgreementNumber",
        "status": "/ReportBody/PositionList/Position/PositionInfo/Mortgage/Status",
    }
    indices: dict[str, int] = {}
    for key, xpath in paths_map.items():
        try:
            indices[key] = header.index(xpath)
        except ValueError:
            pass

    if "ngri" not in indices:
        return []

    last_row = last_row_in_column(sheet_rows, 1)
    out: list[DepoReportRow] = []
    for r in range(3, last_row + 1):
        if r - 1 >= len(sheet_rows):
            break
        row = sheet_rows[r - 1]

        def g(k: str) -> str:
            i = indices.get(k)
            if i is None or i >= len(row):
                return ""
            return cell_to_sql_value(row[i]) or ""

        ngri = g("ngri")
        if not ngri:
            continue
        out.append(
            DepoReportRow(
                source_kind=SourceKind.REGION,
                source_file=source_file,
                schet_depo=g("account"),
                razdel_scheta=_division_to_section(g("division")),
                ngri_v_depo=ngri,
                status=g("status") or None,
                nomer_kd=g("kd") or None,
            ),
        )
    return out


def _parse_region_file(path: Path) -> list[DepoReportRow]:
    if is_format2_path(path):
        return parse_format2_vl_xls(path)

    if is_format1_path(path):
        sheet = read_region_sheet_rows(path)
        return parse_format1_xml(path, sheet)

    suffix = path.suffix.lower()
    if suffix not in (".xls", ".xlsx", ".xml"):
        return []

    if suffix == ".xml":
        sheet = read_region_sheet_rows(path)
        rows = parse_format1_xml(path, sheet)
        if rows:
            return rows

    for _name, sheet_rows in read_workbook_sheets(path):
        parsed = _row_from_region2(sheet_rows, path.name)
        if parsed:
            return parsed
        parsed = _row_from_region_v1(sheet_rows, path.name)
        if parsed:
            return parsed
    return []


def iter_region_rows(
    directory: Path,
    exclude_accounts: list[str] | None = None,
) -> list[DepoReportRow]:
    if not directory.is_dir():
        return []
    exclude = {a.strip().casefold() for a in (exclude_accounts or [])}

    format2_all: list[DepoReportRow] = []
    other_all: list[DepoReportRow] = []
    seen_paths: set[str] = set()

    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name.startswith("~"):
            continue
        if path.suffix.lower() in (".sig", ".pdf", ".zip", ".7z"):
            continue
        key = str(path.resolve()).casefold()
        if key in seen_paths:
            continue
        seen_paths.add(key)

        parsed = _parse_region_file(path)
        if not parsed:
            continue

        if is_format2_path(path):
            format2_all.extend(parsed)
        else:
            other_all.extend(parsed)

    status_by_ngri = build_status_by_ngri(format2_all)
    apply_status_from_format2(other_all, status_by_ngri)

    combined = format2_all + other_all
    out: list[DepoReportRow] = []
    seen_ngri: set[str] = set()

    for row in combined:
        if exclude and row.schet_depo.strip().casefold() in exclude:
            continue
        ngri_key = row.ngri_v_depo.strip().casefold()
        if ngri_key in seen_ngri:
            continue
        seen_ngri.add(ngri_key)
        out.append(row)

    return out
