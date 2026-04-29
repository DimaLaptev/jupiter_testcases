"""Парсинг отчётов ВТБ СД F752 (*.xml) и приложений ZIP (список НГРИ в .xls)."""

from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

# Макет «Приложение 33.xls»: заголовки строка 6, данные с 8, НГРИ — колонка B (см. scrins/VTBSD_zip_2).
VTB_APPENDIX_DATA_START_1BASED = 8
VTB_APPENDIX_NGRI_COL_1BASED = 2


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _text_direct_child(parent: ET.Element, local: str) -> str:
    for child in parent:
        if _local_tag(child.tag) == local:
            return (child.text or "").strip()
    return ""


def vtb_combine_section(name: str, sp_code: str) -> str:
    """Раздел счёта (account section) + «_» + раздел в месте хранения (storage section code)."""
    a = (name or "").strip()
    b = (sp_code or "").strip()
    if not a and not b:
        return ""
    if not a:
        return b
    if not b:
        return a
    return f"{a}_{b}"


@dataclass
class VtbTableStageRow:
    stage_name: str
    odk_date: str
    overlay_depositary_date: str


@dataclass
class VtbF752ParseResult:
    path: Path
    order_number: str
    order_date: str
    execution_date: str
    basis: str
    depository_name: str
    dop_info: str
    qty: str
    src_account: str
    src_section_name: str
    src_sp_section_code: str
    dst_account: str
    dst_section_name: str
    dst_sp_section_code: str
    stage_overlay_date: str
    stage_name: str
    table_stages: list[VtbTableStageRow]


def parse_vtb_f752_xml(path: Path) -> VtbF752ParseResult | None:
    """Разбор F752: блок ClientCashDataOrder, этап с непустым OverlayDepositaryDate."""
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return None
    root = tree.getroot()

    order_el: ET.Element | None = None
    for el in root.iter():
        if _local_tag(el.tag) == "ClientCashDataOrder":
            order_el = el
            break
    if order_el is None:
        return None

    def ord_t(name: str) -> str:
        return _text_direct_child(order_el, name)

    stages: list[VtbTableStageRow] = []
    for el in order_el:
        if _local_tag(el.tag) != "ClientCashDataTable":
            continue
        stages.append(
            VtbTableStageRow(
                stage_name=_text_direct_child(el, "StageName"),
                odk_date=_text_direct_child(el, "ODKDate"),
                overlay_depositary_date=_text_direct_child(el, "OverlayDepositaryDate"),
            ),
        )

    overlay_row: VtbTableStageRow | None = None
    for st in reversed(stages):
        if st.overlay_depositary_date.strip():
            overlay_row = st
            break
    if overlay_row is None and stages:
        overlay_row = stages[-1]

    overlay_date = overlay_row.overlay_depositary_date.strip() if overlay_row else ""
    stage_nm = overlay_row.stage_name.strip() if overlay_row else ""

    def root_t(name: str) -> str:
        v = _text_direct_child(root, name)
        return v if v else ord_t(name)

    return VtbF752ParseResult(
        path=path.resolve(),
        order_number=root_t("OrderNumber"),
        order_date=root_t("OrderDate"),
        execution_date=root_t("ExecutionDate"),
        basis=root_t("Basis"),
        depository_name=root_t("DepositoryName"),
        dop_info=ord_t("DopInfo"),
        qty=(ord_t("Qty") or "1").strip() or "1",
        src_account=ord_t("SrcAccountCode"),
        src_section_name=ord_t("SrcSectionName"),
        src_sp_section_code=ord_t("SrcSPSectionCode"),
        dst_account=ord_t("DstAccountCode"),
        dst_section_name=ord_t("DstSectionName"),
        dst_sp_section_code=ord_t("DstSPSectionCode"),
        stage_overlay_date=overlay_date,
        stage_name=stage_nm,
        table_stages=stages,
    )


def list_ngri_from_vtb_zip(zip_path: Path) -> list[str]:
    """Все НГРИ из первого .xls внутри ZIP (данные со строки 8, колонка B).

    Каждое непустое значение — отдельная строка таблицы приложения; для СВОД на каждое строится своя строка.
    """
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except (OSError, zipfile.BadZipFile):
        return []
    try:
        names = [
            n
            for n in zf.namelist()
            if n.lower().endswith(".xls") and not n.endswith("/")
        ]
        if not names:
            return []
        raw = zf.read(names[0])
    finally:
        zf.close()

    try:
        import xlrd
    except ModuleNotFoundError:
        return []

    try:
        book = xlrd.open_workbook(file_contents=raw, formatting_info=False)
    except Exception:
        return []
    sh = book.sheet_by_index(0)
    start = VTB_APPENDIX_DATA_START_1BASED - 1
    col = VTB_APPENDIX_NGRI_COL_1BASED - 1
    out: list[str] = []
    for r in range(start, sh.nrows):
        if col >= sh.ncols:
            break
        cell = sh.cell(r, col)
        val = cell.value
        if val is None or val == "":
            continue
        if isinstance(val, float) and val == int(val):
            s = str(int(val))
        else:
            s = str(val).strip()
        if s:
            out.append(s)
    return out


def find_vtb_zip_for_xml(xml_path: Path, zip_dir: Path) -> Path | None:
    """Соответствие XML и архива по stem (без учёта регистра расширения .ZIP)."""
    stem = xml_path.stem
    for name in (f"{stem}.ZIP", f"{stem}.zip", f"{stem}.Zip"):
        p = zip_dir / name
        if p.is_file():
            return p
    return None
