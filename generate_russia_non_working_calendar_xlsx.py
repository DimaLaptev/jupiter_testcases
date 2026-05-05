"""
Генератор Excel (Excel) со списком нерабочих дней РФ: государственные праздники и переносы
(Government Resolution), субботы и воскресенья в диапазоне календаря.

Запуск (run): из любой директории (directory)
  python path/to/generate_russia_non_working_calendar_xlsx.py

Файл (output): рядом со скриптом — russia_non_working_days_2026_2027.xlsx
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Set, Tuple

from openpyxl import Workbook

# Границы выгрузки: с запасом на стык новогодних каникул.
_DATE_FIRST = date(2025, 12, 31)
_DATE_LAST = date(2027, 12, 31)

# Нерабочие праздничные периоды (по производственному календарю, переносы учтены в интервалах).
# Предпраздничные сокращённые дни не входят — это рабочие дни.
_PUBLIC_HOLIDAY_PERIODS: Tuple[Tuple[date, date], ...] = (
    (date(2025, 12, 31), date(2025, 12, 31)),
    (date(2026, 1, 1), date(2026, 1, 11)),
    (date(2026, 2, 21), date(2026, 2, 23)),
    (date(2026, 3, 7), date(2026, 3, 9)),
    (date(2026, 5, 1), date(2026, 5, 3)),
    (date(2026, 5, 9), date(2026, 5, 11)),
    (date(2026, 6, 12), date(2026, 6, 14)),
    (date(2026, 11, 4), date(2026, 11, 4)),
    (date(2026, 12, 31), date(2027, 1, 10)),
    (date(2027, 2, 21), date(2027, 2, 23)),
    (date(2027, 3, 6), date(2027, 3, 8)),
    (date(2027, 5, 1), date(2027, 5, 3)),
    (date(2027, 5, 8), date(2027, 5, 10)),
    (date(2027, 6, 12), date(2027, 6, 14)),
    (date(2027, 11, 4), date(2027, 11, 7)),
    (date(2027, 12, 31), date(2027, 12, 31)),
)

OUTPUT_NAME = "russia_non_working_days_2026_2027.xlsx"


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _period_days() -> Set[date]:
    s: Set[date] = set()
    for a, b in _PUBLIC_HOLIDAY_PERIODS:
        for d in _daterange(a, b):
            s.add(d)
    return s


def build_non_working_set() -> Set[date]:
    days = _period_days()
    for d in _daterange(_DATE_FIRST, _DATE_LAST):
        if d.weekday() >= 5:
            days.add(d)
    return days


def write_xlsx(path: Optional[Path] = None) -> Tuple[Path, int]:
    path = path or Path(__file__).resolve().parent / OUTPUT_NAME
    period_days = _period_days()
    all_days = build_non_working_set()
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "days"
    ws.append(["date", "kind"])
    for d in sorted(all_days):
        kind = "public_holiday_or_transfer" if d in period_days else "weekend"
        ws.append([d, kind])
    wb.save(path)
    return path, len(all_days)


if __name__ == "__main__":
    out, n = write_xlsx()
    print(f"Записано (written): {out}, строк данных (data rows): {n}")
