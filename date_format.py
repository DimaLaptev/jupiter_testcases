"""Форматирование дат для выходного свода."""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime

_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


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


def report_month_last_day(report_date: str | None) -> str:
    """Последний день месяца отчёта в формате ДД.ММ.ГГГГ."""
    if not report_date:
        return ""
    normalized = format_date_ddmmyyyy(report_date)
    if not normalized:
        return str(report_date).strip()
    m = _DATE_RE.match(normalized)
    if not m:
        return normalized
    _day, month, year = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    last_day = monthrange(year, month)[1]
    return date(year, month, last_day).strftime("%d.%m.%Y")
