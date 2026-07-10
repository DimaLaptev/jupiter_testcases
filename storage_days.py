"""Расчёт количества дней хранения и комментарии валидации."""

from __future__ import annotations

from datetime import date

from models import FlowDirection, OrdOpRow


def days_exclusive_end(start: date, end_exclusive: date) -> int | None:
    """Дни [start, end_exclusive) — день end не входит (списание)."""
    n = (end_exclusive - start).days
    return n if n >= 0 else None


def days_inclusive(start: date, end: date) -> int | None:
    """Дни [start, end] включительно."""
    n = (end - start).days + 1
    return n if n >= 0 else None


def compute_op_storage_days(
    ops: list[OrdOpRow],
    *,
    has_start: bool,
    has_end: bool,
    period_start: date,
    period_end: date,
) -> list[tuple[int | None, str | None]]:
    """
    Для каждой строки поручения — дни сегмента и опциональный комментарий.

    Дни сегмента, закрытого списанием, пишутся на строку debit.
    Открытый credit до конца месяца — на строку credit.
    """
    n = len(ops)
    results: list[tuple[int | None, str | None]] = [(None, None)] * n
    if not ops:
        return results

    credit_count = sum(1 for o in ops if o.direction == FlowDirection.CREDIT)
    debit_count = sum(1 for o in ops if o.direction == FlowDirection.DEBIT)
    ambiguous = credit_count > 1 or debit_count > 1
    base_comment = (
        f"спорный путь: {credit_count} credit / {debit_count} debit" if ambiguous else None
    )

    held_since: date | None = period_start if has_start else None

    for i, op in enumerate(ops):
        comments: list[str] = []
        if base_comment:
            comments.append(base_comment)

        if op.direction == FlowDirection.CREDIT:
            if op.op_date is None:
                comments.append("нет даты зачисления")
                results[i] = (None, "; ".join(comments) if comments else None)
                continue
            held_since = op.op_date
            later_debit = any(
                ops[j].direction == FlowDirection.DEBIT for j in range(i + 1, n)
            )
            if later_debit:
                results[i] = (None, "; ".join(comments) if comments else None)
            elif has_end:
                days = days_inclusive(op.op_date, period_end)
                results[i] = (days, "; ".join(comments) if comments else None)
            else:
                comments.append("зачисление без остатка на конец и без списания")
                results[i] = (None, "; ".join(comments))
            continue

        if op.direction == FlowDirection.DEBIT:
            if op.op_date is None:
                comments.append("нет даты списания")
                results[i] = (None, "; ".join(comments) if comments else None)
                held_since = None
                continue
            if held_since is None:
                comments.append("списание без периода хранения")
                results[i] = (None, "; ".join(comments))
            else:
                days = days_exclusive_end(held_since, op.op_date)
                if days is None:
                    comments.append("отрицательный интервал")
                    results[i] = (None, "; ".join(comments))
                else:
                    results[i] = (days, "; ".join(comments) if comments else None)
            held_since = None
            continue

        comments.append("неизвестное направление поручения")
        results[i] = (None, "; ".join(comments))

    return results


def validate_quiet_path(
    *,
    has_start: bool,
    has_end: bool,
) -> str | None:
    """Комментарий для ключа без поручений."""
    if has_start and has_end:
        return None
    if has_start and not has_end:
        return "есть на начало, нет операций, нет на конец"
    if not has_start and has_end:
        return "нет на начало, нет операций, есть на конец"
    return None


def validate_ops_path(
    ops: list[OrdOpRow],
    *,
    has_start: bool,
    has_end: bool,
) -> str | None:
    """Доп. проверка согласованности пути с поручениями (скрин 4)."""
    if not ops:
        return validate_quiet_path(has_start=has_start, has_end=has_end)

    has_credit = any(o.direction == FlowDirection.CREDIT for o in ops)
    has_debit = any(o.direction == FlowDirection.DEBIT for o in ops)
    last = ops[-1]
    notes: list[str] = []

    # Закладная1: start + no ops + end — quiet
    # Закладная2: no start + credit + no debit + end — OK
    if not has_start and has_credit and not has_debit and has_end:
        pass
    # Закладная3: start + no credit + debit + no end — OK
    elif has_start and not has_credit and has_debit and not has_end:
        pass
    # Закладная4: start + credit + debit + end — OK если debit до credit (редко) / иначе спорно
    elif has_start and has_credit and has_debit and has_end:
        # по таблице: корректно ЕСЛИ дата списания раньше зачисления
        first_credit = next(o for o in ops if o.direction == FlowDirection.CREDIT)
        first_debit = next(o for o in ops if o.direction == FlowDirection.DEBIT)
        if (
            first_credit.op_date
            and first_debit.op_date
            and first_debit.op_date < first_credit.op_date
        ):
            pass
        else:
            notes.append("start+credit+debit+end: проверьте порядок дат")
    # Закладная5: no start + credit + debit + no end — OK если credit до debit
    elif not has_start and has_credit and has_debit and not has_end:
        first_credit = next(o for o in ops if o.direction == FlowDirection.CREDIT)
        first_debit = next(o for o in ops if o.direction == FlowDirection.DEBIT)
        if (
            first_credit.op_date
            and first_debit.op_date
            and first_credit.op_date < first_debit.op_date
        ):
            pass
        else:
            notes.append("credit+debit: дата зачисления должна быть раньше списания")
    else:
        # прочие комбинации — мягкая проверка
        if has_start and not has_credit and not has_debit and not has_end:
            notes.append("есть на начало, нет операций, нет на конец")
        if not has_start and not has_credit and has_end:
            notes.append("нет на начало и нет зачисления, но есть на конец")
        if last.direction == FlowDirection.DEBIT and has_end:
            notes.append("последнее списание, но есть на конец месяца")
        if last.direction == FlowDirection.CREDIT and not has_end:
            notes.append("последнее зачисление, но нет на конец месяца")

    return "; ".join(notes) if notes else None
