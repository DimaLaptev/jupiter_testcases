"""Форматирование дат для Day_Quantity."""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime

_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")

_RU_MONTHS = (
    "",
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def format_date_ddmmyyyy(value: object | None) -> str | None:
    """Привести значение к строке ДД.ММ.ГГГГ или None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    s = str(value).strip()
    if not s:
        return None
    m = _DATE_RE.match(s)
    if m:
        d, mo, y = m.groups()
        return f"{int(d):02d}.{int(mo):02d}.{y}"
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19], fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue
    try:
        serial = float(s)
        if 1 <= serial <= 60000:
            from datetime import timedelta

            base = date(1899, 12, 30)
            return (base + timedelta(days=int(serial))).strftime("%d.%m.%Y")
    except (ValueError, OverflowError):
        pass
    return s


def parse_date(value: object | None) -> date | None:
    """Разобрать дату из строки ДД.ММ.ГГГГ / datetime / Excel serial."""
    normalized = format_date_ddmmyyyy(value)
    if not normalized:
        return None
    m = _DATE_RE.match(normalized)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def report_month_bounds(report_date: str | None) -> tuple[date, date]:
    """Первый и последний день месяца отчёта."""
    normalized = format_date_ddmmyyyy(report_date) if report_date else None
    if not normalized:
        today = date.today()
        last = monthrange(today.year, today.month)[1]
        return date(today.year, today.month, 1), date(today.year, today.month, last)
    m = _DATE_RE.match(normalized)
    if not m:
        today = date.today()
        last = monthrange(today.year, today.month)[1]
        return date(today.year, today.month, 1), date(today.year, today.month, last)
    _day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def report_month_last_day(report_date: str | None) -> str:
    """Последний день месяца отчёта в формате ДД.ММ.ГГГГ."""
    _start, end = report_month_bounds(report_date)
    return end.strftime("%d.%m.%Y")


def report_month_first_day(report_date: str | None) -> str:
    """Первый день месяца отчёта в формате ДД.ММ.ГГГГ."""
    start, _end = report_month_bounds(report_date)
    return start.strftime("%d.%m.%Y")


def russian_month_name(report_date: str | None) -> str:
    """Русское название месяца отчёта (именительный падеж, с заглавной)."""
    start, _ = report_month_bounds(report_date)
    name = _RU_MONTHS[start.month]
    return name[:1].upper() + name[1:] if name else ""


def days_in_month(report_date: str | None) -> int:
    start, end = report_month_bounds(report_date)
    return (end - start).days + 1
