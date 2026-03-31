"""Парсинг отчётов REGION об исполнении операции: IS*.xls / IS*.xlsx (лист как в scrins/REGION_IS_example_*.png)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from gpb_rep_xls import read_rep_sheet_rows


def _row_join(row: list[str]) -> str:
    return " ".join(x for x in row if x).strip()


def _norm_cell(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower().replace("ё", "е"))


def _find_value_after_keywords(row: list[str], must_contain: tuple[str, ...]) -> str:
    for ci, cell in enumerate(row):
        cl = _norm_cell(cell)
        if not cl:
            continue
        if not all(k in cl for k in must_contain):
            continue
        for cj in range(ci + 1, min(len(row), ci + 8)):
            t = row[cj].strip()
            if t:
                return t
    return ""


def _scan_field(rows: list[list[str]], max_r: int, must_contain: tuple[str, ...]) -> str:
    for row in rows[:max_r]:
        v = _find_value_after_keywords(row, must_contain)
        if v:
            return v
        for cell in row:
            cl = cell.strip()
            if not cl:
                continue
            cln = _norm_cell(cl)
            if not all(k in cln for k in must_contain):
                continue
            if ":" in cl or "：" in cl:
                parts = re.split(r"[:\uFF1A]", cl, maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    return parts[1].strip()
    return ""


def _parse_header_accounts(rows: list[list[str]], max_r: int = 220) -> tuple[str, str, str, str]:
    """
    Извлекает пары «Со счета депо» / «На счет депо» и следующие «Раздел счета депо».
    Упрощённый конечный автомат по строкам с меткой в col A и значением в col B.
    """
    from_acc = from_sec = to_acc = to_sec = ""
    pending: str | None = None

    for row in rows[:max_r]:
        if len(row) < 2:
            continue
        label_raw = row[0].strip()
        label = _norm_cell(label_raw)
        val = row[1].strip() if len(row) > 1 else ""
        if not label_raw:
            continue

        if "со счета депо" in label and "раздел" not in label:
            if val:
                from_acc = val
                pending = "from"
            continue

        if "на счет депо" in label and "раздел" not in label:
            if val:
                to_acc = val
                pending = "to"
            continue

        if "раздел счета депо" in label or "раздел счёта депо" in label:
            if val:
                if pending == "from":
                    from_sec = val
                elif pending == "to":
                    to_sec = val
                elif from_acc and not from_sec:
                    from_sec = val
                elif to_acc and not to_sec:
                    to_sec = val
            continue

    return from_acc, from_sec, to_acc, to_sec


def _region_ngri_col_map(row: list[str]) -> dict[str, int] | None:
    cmap: dict[str, int] = {}
    for i, cell in enumerate(row):
        t = _norm_cell(cell)
        if not t:
            continue
        if "нгри" in t or "игри" in t:
            cmap["ngri"] = i
            break
    if "ngri" not in cmap:
        return None
    for i, cell in enumerate(row):
        t = _norm_cell(cell)
        if "п/п" in t or t == "№" or t.startswith("№ "):
            cmap["seq"] = i
            break
    return cmap


def _find_mortgage_table(
    rows: list[list[str]],
) -> tuple[int, dict[str, int]] | None:
    title_ri = -1
    for ri, row in enumerate(rows):
        blob = _row_join(row).lower().replace("ё", "е")
        if "сведения о закладных" in blob:
            title_ri = ri
            break
    if title_ri < 0:
        for ri, row in enumerate(rows):
            cm = _region_ngri_col_map(row)
            if cm:
                return ri, cm
        return None

    for j in range(title_ri + 1, min(title_ri + 15, len(rows))):
        cm = _region_ngri_col_map(rows[j])
        if cm:
            return j, cm
    return None


def _is_footer_row(row: list[str]) -> bool:
    blob = _row_join(row).lower().replace("ё", "е")
    if "основание:" in blob or blob.startswith("основание"):
        return True
    if "рег.№ поручения" in blob.replace(" ", "") or "рег № поручения" in blob:
        return True
    if "рег. № поручения" in blob:
        return True
    return False


def _parse_footer(rows: list[list[str]], start_ri: int) -> tuple[str, str]:
    basis = ""
    reg = ""
    for row in rows[start_ri:]:
        if len(row) < 2:
            continue
        l0 = row[0].strip().lower().replace("ё", "е")
        v1 = row[1].strip() if len(row) > 1 else ""
        if "основание" in l0 and v1:
            basis = v1
        if ("поручения" in l0 or "поручен" in l0) and "рег" in l0 and v1:
            reg = v1
        joined = _row_join(row).lower()
        if "основание:" in joined and not basis:
            m = re.search(r"основание\s*:\s*(.+)", joined, re.IGNORECASE)
            if m:
                basis = m.group(1).strip()
        if "поручения" in joined and "рег" in joined and not reg:
            m = re.search(
                r"рег\.?\s*№?\s*поручения\s*:\s*(.+)",
                joined,
                re.IGNORECASE,
            )
            if m:
                reg = m.group(1).strip()
    return basis, reg


@dataclass
class RegionTableRow:
    ngri: str


@dataclass
class RegionParseResult:
    path: Path
    operation_type: str
    op_date: str
    from_acc: str
    from_sec: str
    to_acc: str
    to_sec: str
    basis: str
    reg_footer: str
    table_rows: list[RegionTableRow] = field(default_factory=list)


def parse_region_is_xls(path: Path) -> RegionParseResult | None:
    path = Path(path)
    stem = path.stem.upper()
    if not stem.startswith("IS"):
        return None

    rows = read_rep_sheet_rows(path)
    if not rows:
        return None

    op_type = _scan_field(rows, 120, ("тип операции",))
    op_date = _scan_field(rows, 120, ("дата проведения операции",))
    from_acc, from_sec, to_acc, to_sec = _parse_header_accounts(rows)

    tbl = _find_mortgage_table(rows)
    table_out: list[RegionTableRow] = []
    data_start = 0
    if tbl:
        hdr_ri, cmap = tbl
        data_start = hdr_ri + 1
        ic = cmap["ngri"]
        for rj in range(data_start, len(rows)):
            row = rows[rj]
            if _is_footer_row(row):
                break
            if not any(c.strip() for c in row):
                continue
            joined = _row_join(row).lower()
            if "сведения о закладных" in joined:
                continue
            if ic < len(row):
                ngri = row[ic].strip()
            else:
                ngri = ""
            hdr_check = _norm_cell(row[ic] if ic < len(row) else "")
            if hdr_check in ("нгри", "игри", "№ п/п", "№п/п"):
                continue
            if not ngri:
                seq_empty = True
                if "seq" in cmap:
                    si = cmap["seq"]
                    if si < len(row) and row[si].strip():
                        seq_empty = False
                if seq_empty:
                    break
                continue
            if "нгри" in ngri.lower() and len(ngri) < 12:
                continue
            table_out.append(RegionTableRow(ngri=ngri))

    footer_start = max(0, data_start)
    basis, reg_footer = _parse_footer(rows, footer_start)

    return RegionParseResult(
        path=path.resolve(),
        operation_type=op_type,
        op_date=op_date,
        from_acc=from_acc,
        from_sec=from_sec,
        to_acc=to_acc,
        to_sec=to_sec,
        basis=basis,
        reg_footer=reg_footer,
        table_rows=table_out,
    )
