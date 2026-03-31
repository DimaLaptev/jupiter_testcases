"""Лист «Количество поручений»: заголовки (headers) и агрегация (aggregation) из «СВОД_операций»."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

ORD_QUANTITY_SHEET = "Количество поручений"
SVOD_SHEET = "СВОД_операций"


@dataclass
class _GroupLayout:
    merge: str
    start_col: int
    width: int
    subheaders: list[str]
    placeholder: bool
    instruction_types: list[str]
    metrics: list[str]
    skip_por: bool


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_headers_layout(path: Path | None = None) -> dict[str, Any]:
    """Читает memory/Ord_Quantity_headers.json."""
    p = path or (_project_root() / "memory" / "Ord_Quantity_headers.json")
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def _build_group_layouts(data: dict[str, Any]) -> list[_GroupLayout]:
    col = 4
    out: list[_GroupLayout] = []
    for g in data["data_groups"]:
        subs = list(g["subheaders"])
        w = len(subs)
        if w == 1 and subs[0] == "":
            w = 1
        ph = bool(g.get("placeholder"))
        it = list(g.get("instruction_types") or [])
        met = list(g.get("metrics") or [])
        sk = bool(g.get("skip_por"))
        out.append(
            _GroupLayout(
                merge=str(g["merge"]),
                start_col=col,
                width=w,
                subheaders=subs,
                placeholder=ph,
                instruction_types=it,
                metrics=met,
                skip_por=sk,
            ),
        )
        col += w
    return out


def _instruction_to_bucket(
    inst_raw: str,
    op_type: str,
    type_to_bucket: dict[str, str],
) -> str | None:
    inst = (inst_raw or "").strip().upper()
    if not inst or inst == "-":
        return None
    if inst == "E":
        low = (op_type or "").lower()
        if "зачисление" in low and "списание" not in low:
            return "T"
        if "списание" in low and "зачисление" not in low:
            return "Y"
        return None
    return type_to_bucket.get(inst)


def _parse_svod_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s or s == "-":
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _in_month(d: datetime, year: int, month: int) -> bool:
    return d.year == year and d.month == month


def _parse_qty_mortgages(cell: str) -> int:
    s = (cell or "").strip()
    if not s or s == "-":
        return 1
    try:
        return max(1, int(float(s.replace(",", "."))))
    except ValueError:
        return 1


def _header_map(ws, row: int = 1) -> dict[str, int]:
    m: dict[str, int] = {}
    for c in range(1, (ws.max_column or 0) + 1):
        v = ws.cell(row=row, column=c).value
        if v is None:
            continue
        key = str(v).strip()
        if key:
            m[key] = c
    return m


def _read_svod_rows(
    ws,
    year: int,
    month: int,
) -> list[dict[str, Any]]:
    hdr = _header_map(ws, 1)
    need = [
        "Дата операции",
        "Депозитарий",
        "Тип операции",
        "Владелец",
        "Счет депо",
        "Количество закладных",
        "Тип поручения",
        "ОдноТипОперТипРазд",
    ]
    for k in need:
        if k not in hdr:
            raise ValueError(f"В листе «{SVOD_SHEET}» нет колонки «{k}»")

    rows_out: list[dict[str, Any]] = []
    for r in range(2, (ws.max_row or 1) + 1):
        def cell(name: str) -> str:
            v = ws.cell(row=r, column=hdr[name]).value
            if v is None:
                return ""
            return str(v).strip()

        d_raw = cell("Дата операции")
        dt = _parse_svod_date(d_raw)
        if dt is None or not _in_month(dt, year, month):
            continue

        acc = cell("Счет депо")
        if not acc or acc == "-":
            continue

        rows_out.append(
            {
                "Дата операции": d_raw,
                "Депозитарий": cell("Депозитарий"),
                "Тип операции": cell("Тип операции"),
                "Владелец": cell("Владелец"),
                "Счет депо": acc,
                "Количество закладных": cell("Количество закладных"),
                "Тип поручения": cell("Тип поручения"),
                "ОдноТипОперТипРазд": cell("ОдноТипОперТипРазд"),
            },
        )
    return rows_out


def _type_to_bucket_map(groups: list[_GroupLayout]) -> dict[str, str]:
    m: dict[str, str] = {}
    for g in groups:
        if g.placeholder:
            continue
        for t in g.instruction_types:
            m[t.strip().upper()] = g.merge
    return m


@dataclass
class _BucketAcc:
    por_keys: set[str] = field(default_factory=set)
    zakl_sum: int = 0
    list_rows: int = 0


def aggregate_svod_to_matrix(
    svod_rows: list[dict[str, Any]],
    layout: dict[str, Any] | None = None,
) -> tuple[dict[tuple[str, str, str], dict[str, _BucketAcc]], list[_GroupLayout]]:
    data = layout or load_headers_layout()
    groups = _build_group_layouts(data)
    tmap = _type_to_bucket_map(groups)

    matrix: dict[tuple[str, str, str], dict[str, _BucketAcc]] = defaultdict(
        lambda: defaultdict(_BucketAcc),
    )

    for row in svod_rows:
        dep = (row["Депозитарий"] or "").strip() or "-"
        owner = (row["Владелец"] or "").strip() or "-"
        acc = row["Счет депо"].strip()
        inst = row["Тип поручения"]
        op_type = row["Тип операции"]
        tech = (row["ОдноТипОперТипРазд"] or "").strip()
        if not tech:
            tech = f"{acc}_{inst}_{row['Дата операции']}"

        bucket = _instruction_to_bucket(inst, op_type, tmap)
        if bucket is None:
            continue

        qty = _parse_qty_mortgages(row["Количество закладных"])
        cell_key = (dep, owner, acc)
        accm = matrix[cell_key][bucket]
        accm.zakl_sum += qty
        if bucket == "Q":
            accm.list_rows += 1
        else:
            accm.por_keys.add(tech)

    return matrix, groups


def _unmerge_all(ws) -> None:
    for rng in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(rng))


def ensure_ord_quantity_sheet(wb, layout: dict[str, Any] | None = None) -> Any:
    data = layout or load_headers_layout()
    name = data.get("sheet_name", ORD_QUANTITY_SHEET)
    if name not in wb.sheetnames:
        wb.create_sheet(name)
    ws = wb[name]
    groups = _build_group_layouts(data)
    _unmerge_all(ws)

    last_col = max(3, groups[-1].start_col + groups[-1].width - 1)
    for r in range(1, 3):
        for c in range(1, last_col + 1):
            ws.cell(row=r, column=c, value=None)

    for i, idc in enumerate(data["id_columns"], start=1):
        ws.cell(row=1, column=i, value=idc["header"])
        ws.merge_cells(
            start_row=1,
            start_column=i,
            end_row=2,
            end_column=i,
        )

    for g in groups:
        c0 = g.start_col
        c1 = c0 + g.width - 1
        letter_s = get_column_letter(c0)
        letter_e = get_column_letter(c1)
        ws.merge_cells(f"{letter_s}1:{letter_e}1")
        ws.cell(row=1, column=c0, value=g.merge)
        for j, sub in enumerate(g.subheaders):
            ws.cell(row=2, column=c0 + j, value=sub if sub else None)

    return ws


def write_ord_quantity_matrix(
    path: Path,
    matrix: dict[tuple[str, str, str], dict[str, _BucketAcc]],
    groups: list[_GroupLayout],
    layout: dict[str, Any] | None = None,
) -> None:
    data = layout or load_headers_layout()
    wb = load_workbook(path)
    ensure_ord_quantity_sheet(wb, data)
    ws = wb[data.get("sheet_name", ORD_QUANTITY_SHEET)]

    max_r = ws.max_row or 2
    if max_r > 2:
        for r in range(3, max_r + 1):
            for c in range(1, groups[-1].start_col + groups[-1].width + 1):
                ws.cell(row=r, column=c, value=None)

    sorted_keys = sorted(matrix.keys(), key=lambda x: (x[0], x[1], x[2]))
    row_idx = 3
    for dep, owner, acc in sorted_keys:
        ws.cell(row=row_idx, column=1, value=dep if dep != "-" else None)
        ws.cell(row=row_idx, column=2, value=owner if owner != "-" else None)
        ws.cell(row=row_idx, column=3, value=acc)
        buckets = matrix[(dep, owner, acc)]

        for g in groups:
            if g.placeholder:
                for j in range(g.width):
                    ws.cell(row=row_idx, column=g.start_col + j, value=0)
                continue

            accm = buckets.get(g.merge)
            if accm is None:
                for j in range(g.width):
                    ws.cell(row=row_idx, column=g.start_col + j, value=0)
                continue

            if g.merge == "Q":
                ws.cell(row=row_idx, column=g.start_col, value=accm.zakl_sum)
                ws.cell(row=row_idx, column=g.start_col + 1, value=accm.list_rows)
            else:
                ws.cell(row=row_idx, column=g.start_col, value=len(accm.por_keys))
                ws.cell(row=row_idx, column=g.start_col + 1, value=accm.zakl_sum)

        row_idx += 1

    wb.save(path)


def fill_ord_quantity_from_workbook(
    workbook_path: Path,
    year: int,
    month: int,
    layout_path: Path | None = None,
) -> int:
    layout = (
        json.load(layout_path.open(encoding="utf-8"))
        if layout_path
        else load_headers_layout()
    )
    wb = load_workbook(workbook_path)
    if SVOD_SHEET not in wb.sheetnames:
        raise ValueError(f"В книге нет листа «{SVOD_SHEET}»")

    svod_rows = _read_svod_rows(wb[SVOD_SHEET], year, month)
    matrix, groups = aggregate_svod_to_matrix(svod_rows, layout)
    write_ord_quantity_matrix(workbook_path, matrix, groups, layout)
    return len(matrix)


def create_workbook_with_ord_quantity_template(out: Path, layout: dict[str, Any] | None = None) -> None:
    """Создаёт xlsx с листом «Количество поручений» (только шапка)."""
    data = layout or load_headers_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = data.get("sheet_name", ORD_QUANTITY_SHEET)
    ensure_ord_quantity_sheet(wb, data)
    wb.save(out)


def create_workbook_svod_and_ord_templates(out: Path, layout: dict[str, Any] | None = None) -> None:
    """Книга с шапками «СВОД_операций» и «Количество поручений» (для 2026_01_Ord_Quantity.xlsx)."""
    from svod_excel import SVOD_HEADERS

    data = layout or load_headers_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = data.get("sheet_name", ORD_QUANTITY_SHEET)
    ensure_ord_quantity_sheet(wb, data)

    ws_svod = wb.create_sheet(SVOD_SHEET)
    for col, title in enumerate(SVOD_HEADERS, start=1):
        ws_svod.cell(row=1, column=col, value=title)

    wb.save(out)
