"""Слияние тихой строки с поручением E для ДЕПО=РЕГИОН."""

from __future__ import annotations

from assemble.storage_days import days_exclusive_end
from date_format import parse_date, report_month_bounds
from models import ABSENT, DayQuantityRow

REGION_DEPO = "РЕГИОН"
MERGE_COMMENT = "есть на начало, нет на конец, есть списание (тип поручения E)"


def _ngri_key(value: str | None) -> str:
    return (value or "").strip().casefold()


def _is_absent(value: str | None) -> bool:
    if value is None:
        return True
    s = str(value).strip()
    return not s or s.casefold() == ABSENT.casefold()


def _is_quiet_start_no_end(row: DayQuantityRow) -> bool:
    """Тихая: есть на начало, нет на конец, нет типа поручения."""
    if row.instruction_type and str(row.instruction_type).strip():
        return False
    has_start = not _is_absent(row.start_ngri)
    has_end = not _is_absent(row.end_ngri)
    return has_start and not has_end


def _is_e_row(row: DayQuantityRow) -> bool:
    return (row.instruction_type or "").strip().upper() == "E"


def _merge_one(
    quiet: DayQuantityRow,
    e_row: DayQuantityRow,
    *,
    period_start,
) -> DayQuantityRow:
    op_date = parse_date(e_row.instruction_date)
    days = days_exclusive_end(period_start, op_date) if op_date is not None else None

    return DayQuantityRow(
        depo=quiet.depo or e_row.depo or REGION_DEPO,
        ngri=quiet.ngri or e_row.ngri,
        n_zakladnoy=quiet.n_zakladnoy or e_row.n_zakladnoy,
        enc=quiet.enc or e_row.enc,
        schet_depo=quiet.schet_depo or e_row.schet_depo,
        razdel_scheta=quiet.razdel_scheta or e_row.razdel_scheta,
        start_ngri=quiet.start_ngri,
        start_schet=quiet.start_schet,
        start_razdel=quiet.start_razdel,
        end_ngri=ABSENT,
        end_schet=ABSENT,
        end_razdel=ABSENT,
        instruction_type="E",
        instruction_date=e_row.instruction_date,
        storage_days=days,
        comment=MERGE_COMMENT,
    )


def merge_region_quiet_with_e(
    rows: list[DayQuantityRow],
    report_date: str,
) -> list[DayQuantityRow]:
    """
    Для ДЕПО=РЕГИОН: тихая (есть начало, нет конца) + строки E →
    одна строка на каждое E с общим контекстом start; тихую убрать.
    """
    period_start, _period_end = report_month_bounds(report_date)

    quiet_by_ngri: dict[str, list[int]] = {}
    e_by_ngri: dict[str, list[int]] = {}

    for i, row in enumerate(rows):
        if (row.depo or "").strip() != REGION_DEPO:
            continue
        key = _ngri_key(row.ngri)
        if not key:
            continue
        if _is_quiet_start_no_end(row):
            quiet_by_ngri.setdefault(key, []).append(i)
        elif _is_e_row(row):
            e_by_ngri.setdefault(key, []).append(i)

    drop: set[int] = set()
    merged_at: dict[int, list[DayQuantityRow]] = {}

    for key, quiet_idxs in quiet_by_ngri.items():
        e_idxs = e_by_ngri.get(key) or []
        if not e_idxs:
            continue
        quiet = rows[quiet_idxs[0]]
        anchor = quiet_idxs[0]
        for qi in quiet_idxs:
            drop.add(qi)
        merged_list: list[DayQuantityRow] = []
        for ei in e_idxs:
            drop.add(ei)
            merged_list.append(_merge_one(quiet, rows[ei], period_start=period_start))
        merged_at[anchor] = merged_list

    if not drop:
        return rows

    out: list[DayQuantityRow] = []
    for i, row in enumerate(rows):
        if i in drop:
            if i in merged_at:
                out.extend(merged_at[i])
            continue
        out.append(row)

    return out
