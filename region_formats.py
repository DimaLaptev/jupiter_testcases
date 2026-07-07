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
_VRSN_LKK_STEM_RE = re.compile(r"^(?:BpCH|ВрСн)_VL([\w]+)_\d+$", re.IGNORECASE)
_VRSN_LKK_DIR_MARKERS = ("врсн", "лкк")


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


def _xml_child(parent: ET.Element, tag: str) -> ET.Element | None:
    for child in parent:
        if _xml_local_tag(child.tag) == tag:
            return child
    return None


def _xml_text(parent: ET.Element, tag: str) -> str:
    child = _xml_child(parent, tag)
    if child is None:
        return ""
    return (child.text or "").strip()


def is_depoaccount_balance_root(root: ET.Element) -> bool:
    return _xml_local_tag(root.tag) == "DEPOACCOUNT_BALANCE_REPORT"


def _depoaccount_from_balance_root(root: ET.Element) -> str:
    header = _xml_child(root, "ReportHeader")
    if header is None:
        return ""
    depo_wrap = _xml_child(header, "DepoAccount")
    if depo_wrap is None:
        return ""
    return _xml_text(depo_wrap, "DepoAccount")


def parse_depoaccount_balance_xml(
    path: Path,
    root: ET.Element | None = None,
) -> list[DepoReportRow]:
    """
    Сырой XML отчёта DEPOACCOUNT_BALANCE_REPORT (не SpreadsheetML).
    Position -> Mortgage (RegistrationNumber, AgreementNumber) + DivisionList.
    """
    if root is None:
        root = _read_xml_root(path)
    if root is None or not is_depoaccount_balance_root(root):
        return []

    schet_file = account_from_bracket_filename(path) or ""
    schet_report = _depoaccount_from_balance_root(root)
    schet_default = schet_report or schet_file

    body = _xml_child(root, "ReportBody")
    if body is None:
        return []

    out: list[DepoReportRow] = []
    for pos_el in body.iter():
        if _xml_local_tag(pos_el.tag) != "Position":
            continue

        pos_info = _xml_child(pos_el, "PositionInfo")
        mortgage = _xml_child(pos_info, "Mortgage") if pos_info is not None else None
        if mortgage is None:
            continue

        ngri = _xml_text(mortgage, "RegistrationNumber")
        if not ngri:
            continue
        kd = _xml_text(mortgage, "AgreementNumber") or None

        division_list = _xml_child(pos_el, "DivisionList")
        divisions: list[str] = []
        if division_list is not None:
            for div_el in division_list:
                if _xml_local_tag(div_el.tag) != "Division":
                    continue
                div_info = _xml_child(div_el, "DivisionInfo")
                if div_info is None:
                    continue
                name = _xml_text(div_info, "DivisionName")
                code = _xml_text(div_info, "DivisionCode")
                division = name or code
                if division:
                    divisions.append(division)

        if not divisions:
            divisions = [""]

        for division in divisions:
            out.append(
                DepoReportRow(
                    source_kind=SourceKind.REGION,
                    source_file=path.name,
                    schet_depo=schet_default,
                    razdel_scheta=division,
                    ngri_v_depo=ngri,
                    status=None,
                    nomer_kd=kd,
                ),
            )
    return out


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


def is_vrsn_lkk_path(path: Path) -> bool:
    """BpCH_VL0160_1.xlsx / ВрСн_VL0160_1.xlsx в «ОтчетыВрСн из ЛКК»."""
    if path.suffix.lower() not in (".xls", ".xlsx"):
        return False
    if _VRSN_LKK_STEM_RE.match(path.stem):
        return True
    parts = path.as_posix().casefold()
    return all(marker in parts for marker in _VRSN_LKK_DIR_MARKERS)


def schet_from_vrsn_lkk_filename(path: Path) -> str:
    m = _VRSN_LKK_STEM_RE.match(path.stem)
    if not m:
        return ""
    return f"VL{m.group(1)}".upper()


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


def _find_vrsn_lkk_header_row(sheet_rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    for r in range(1, min(20, len(sheet_rows) + 1)):
        cmap = _header_col_map(sheet_rows, r)
        keys = set(cmap.keys())
        if "статус" in keys and ("номер гри" in keys or "нгри" in keys):
            return r, cmap
    return None


def parse_vrsn_lkk_xlsx(path: Path, sheet_rows: list[list[str]] | None = None) -> list[DepoReportRow]:
    """
    ОтчетыВрСн из ЛКК: BpCH_VL0160_1.xlsx — колонки «Номер ГРИ», «Статус».
    Используется только для подстановки состояния по НГРИ.
    """
    rows = sheet_rows if sheet_rows is not None else read_region_sheet_rows(path)
    if not rows:
        return []

    found = _find_vrsn_lkk_header_row(rows)
    if found is None:
        return []

    header_row, col_map = found
    schet = schet_from_vrsn_lkk_filename(path)
    ngri_col = col_map.get("номер гри", col_map.get("нгри", 1))
    data_start = header_row + 1
    last = last_row_in_column(rows, ngri_col + 1)
    out: list[DepoReportRow] = []

    for r in range(data_start, last + 1):
        if r - 1 >= len(rows):
            break
        row = rows[r - 1]
        ngri = _cell_by_header(row, col_map, "Номер ГРИ", "НГРИ", "NGRI")
        if not ngri:
            continue
        status = _cell_by_header(row, col_map, "Статус", "Состояние", "Status")
        if not status:
            continue
        out.append(
            DepoReportRow(
                source_kind=SourceKind.REGION,
                source_file=path.name,
                schet_depo=schet,
                razdel_scheta="",
                ngri_v_depo=ngri,
                status=status,
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


def merge_status_by_ngri(
    primary: dict[str, str],
    extra_rows: list[DepoReportRow],
) -> dict[str, str]:
    """Дополняет карту статусов (без перезаписи уже известных НГРИ)."""
    out = dict(primary)
    for row in extra_rows:
        key = (row.ngri_v_depo or "").strip().casefold()
        if key and row.status and key not in out:
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
