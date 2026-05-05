from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Set

from openpyxl import load_workbook

from config_ews import REPORS_DEPO_DIRECTORY


def _depo_validation_dir() -> Path:
    """Каталог depo_validation лежит внутри REPORS_DEPO_DIRECTORY (см. config_ews)."""
    if not REPORS_DEPO_DIRECTORY:
        raise ValueError(
            "REPORS_DEPO_DIRECTORY не задан в окружении – укажите путь к корню отчётов в .env"
        )
    return Path(REPORS_DEPO_DIRECTORY) / "depo_validation"


def _calendar_path() -> Path:
    return _depo_validation_dir() / "russia_non_working_days_2026_2027.xlsx"


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

    cal = _calendar_path()

    if not cal.is_file():
        raise FileNotFoundError(
            f"Нет файла календаря (calendar file): {cal}. "
            "Сгенерируйте Excel (Excel) скриптом generate_russia_non_working_calendar_xlsx.py "
            "и поместите файл в каталог depo_validation внутри REPORS_DEPO_DIRECTORY."
        )

    wb = load_workbook(cal, read_only=True, data_only=True)
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
        raise ValueError(f"В {cal} нет ни одной даты в столбце date.")

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
                f"Не удалось найти рабочий день: проверьте файл календаря {_calendar_path()}."
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
