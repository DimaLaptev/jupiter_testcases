"""Сборка строк Day_Quantity по пути закладной."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from assemble.storage_days import (
    compute_op_storage_days,
    validate_ops_path,
    validate_quiet_path,
)
from date_format import days_in_month, report_month_bounds
from models import ABSENT, DayQuantityRow, FlowDirection, OrdOpRow, SvodDepoRow


def _index_svod(rows: list[SvodDepoRow]) -> dict[tuple[str, str, str], SvodDepoRow]:
    """Первая строка по ключу пути."""
    out: dict[tuple[str, str, str], SvodDepoRow] = {}
    for row in rows:
        key = row.path_key()
        if key[0] and key not in out:
            out[key] = row
    return out


def _group_ops(ops: list[OrdOpRow]) -> dict[tuple[str, str, str], list[OrdOpRow]]:
    grouped: dict[tuple[str, str, str], list[OrdOpRow]] = defaultdict(list)
    for op in ops:
        key = op.path_key()
        if key[0]:
            grouped[key].append(op)
    for key in grouped:
        grouped[key].sort(
            key=lambda o: (
                o.op_date or date.min,
                0 if o.direction == FlowDirection.CREDIT else 1,
                o.instruction_type,
            ),
        )
    return grouped


def _or_absent(value: str | None) -> str:
    """Пустое значение в блоках начало/конец месяца → «отсутствует»."""
    if value is None:
        return ABSENT
    s = str(value).strip()
    return s if s else ABSENT


def _fill_start(row: DayQuantityRow, start: SvodDepoRow | None) -> None:
    if start is None:
        row.start_ngri = ABSENT
        row.start_schet = ABSENT
        row.start_razdel = ABSENT
        return
    row.start_ngri = _or_absent(start.ngri)
    row.start_schet = _or_absent(start.schet_depo)
    row.start_razdel = _or_absent(start.razdel_scheta)


def _fill_end(row: DayQuantityRow, end: SvodDepoRow | None, *, show: bool) -> None:
    if not show or end is None:
        row.end_ngri = ABSENT
        row.end_schet = ABSENT
        row.end_razdel = ABSENT
        return
    row.end_ngri = _or_absent(end.ngri)
    row.end_schet = _or_absent(end.schet_depo)
    row.end_razdel = _or_absent(end.razdel_scheta)


def _identity_from_svod(svod: SvodDepoRow) -> DayQuantityRow:
    return DayQuantityRow(
        ngri=svod.ngri,
        n_zakladnoy=svod.n_zakladnoy,
        enc=svod.enc,
        schet_depo=svod.schet_depo,
        razdel_scheta=svod.razdel_scheta,
    )


def _identity_from_op(op: OrdOpRow, start: SvodDepoRow | None) -> DayQuantityRow:
    return DayQuantityRow(
        ngri=op.ngri,
        n_zakladnoy=start.n_zakladnoy if start else None,
        enc=start.enc if start else None,
        schet_depo=op.schet_depo,
        razdel_scheta=op.razdel_scheta,
    )


def _merge_comments(*parts: str | None) -> str | None:
    cleaned = [p.strip() for p in parts if p and p.strip()]
    return "; ".join(cleaned) if cleaned else None


def build_day_rows(
    prev_rows: list[SvodDepoRow],
    curr_rows: list[SvodDepoRow],
    ord_ops: list[OrdOpRow],
    report_date: str,
) -> list[DayQuantityRow]:
    """
    Собрать строки Day_Quantity.

    Поручения не схлопываются (одна строка на поручение).
    Тихий путь start→end без операций — одна строка.
    """
    period_start, period_end = report_month_bounds(report_date)
    month_days = days_in_month(report_date)

    start_idx = _index_svod(prev_rows)
    end_idx = _index_svod(curr_rows)
    ops_by_key = _group_ops(ord_ops)

    all_keys = set(start_idx) | set(end_idx) | set(ops_by_key)
    # Стабильный порядок: сначала ключи из прошлого СВОД, затем Ord, затем только конец
    ordered_keys: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in prev_rows:
        k = row.path_key()
        if k[0] and k not in seen and k in all_keys:
            ordered_keys.append(k)
            seen.add(k)
    for op in ord_ops:
        k = op.path_key()
        if k[0] and k not in seen and k in all_keys:
            ordered_keys.append(k)
            seen.add(k)
    for row in curr_rows:
        k = row.path_key()
        if k[0] and k not in seen and k in all_keys:
            ordered_keys.append(k)
            seen.add(k)
    for k in sorted(all_keys - seen):
        ordered_keys.append(k)

    out: list[DayQuantityRow] = []

    for key in ordered_keys:
        start = start_idx.get(key)
        end = end_idx.get(key)
        ops = ops_by_key.get(key, [])
        has_start = start is not None
        has_end = end is not None

        if not ops:
            identity_src = start or end
            if identity_src is None:
                continue
            base = _identity_from_svod(identity_src)
            _fill_start(base, start)
            _fill_end(base, end, show=True)
            if has_start and has_end:
                base.storage_days = month_days
            base.comment = validate_quiet_path(has_start=has_start, has_end=has_end)
            out.append(base)
            continue

        path_comment = validate_ops_path(ops, has_start=has_start, has_end=has_end)
        days_list = compute_op_storage_days(
            ops,
            has_start=has_start,
            has_end=has_end,
            period_start=period_start,
            period_end=period_end,
        )
        # Если ключ есть в текущем СВОД — всегда заполняем «на конец»
        # (не затираем из‑за последнего списания / debit).

        for op, (days, day_comment) in zip(ops, days_list):
            row = _identity_from_op(op, start)
            _fill_start(row, start)
            _fill_end(row, end, show=True)
            row.instruction_type = op.instruction_type
            row.instruction_date = op.op_date_raw
            row.storage_days = days
            row.comment = _merge_comments(path_comment, day_comment)
            out.append(row)

    return out
