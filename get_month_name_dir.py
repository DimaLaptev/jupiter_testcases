from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Set

from openpyxl import load_workbook

# Файл создаётся скриптом depo_validation/generate_russia_non_working_calendar_xlsx.py
_CALENDAR_PATH = (
    Path(__file__).resolve().parent / "depo_validation" / "russia_non_working_days_2026_2027.xlsx"
)

_NON_WORKING_CACHE: Optional[Set[date]] = None


def _parse_row_date(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return None


def _load_non_working_dates() -> Set[date]:
    global _NON_WORKING_CACHE
    if _NON_WORKING_CACHE is not None:
        return _NON_WORKING_CACHE

    if not _CALENDAR_PATH.is_file():
        raise FileNotFoundError(
            f"Нет файла календаря (calendar file): {_CALENDAR_PATH}. "
            "Сгенерируйте его: python dep_report/dep_report/depo_validation/"
            "generate_russia_non_working_calendar_xlsx.py"
        )

    wb = load_workbook(_CALENDAR_PATH, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        out: Set[date] = set()
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row:
                continue
            d = _parse_row_date(row[0])
            if d:
                out.add(d)
    finally:
        wb.close()

    if not out:
        raise ValueError(f"В {_CALENDAR_PATH} нет ни одной даты в столбце date.")

    _NON_WORKING_CACHE = out
    return _NON_WORKING_CACHE


def _is_non_working_day(d: date) -> bool:
    return d in _load_non_working_dates()


def _reference_date_for_reporting_month() -> date:
    yesterday = (datetime.now() - timedelta(days=1)).date()
    if not _is_non_working_day(yesterday):
        return yesterday
    d = yesterday - timedelta(days=1)
    steps = 0
    while _is_non_working_day(d):
        d -= timedelta(days=1)
        steps += 1
        if steps > 800:
            raise RuntimeError(
                f"Не удалось найти рабочий день: проверьте файл календаря {_CALENDAR_PATH}."
            )
    return d


def get_current_year_month() -> str:
    d = _reference_date_for_reporting_month()
    return f"{d.year}_{d.month:02d}"


def get_today_year_month() -> str:
    return get_current_year_month()


if __name__ == "__main__":
    print(get_current_year_month())
    print(get_today_year_month())
