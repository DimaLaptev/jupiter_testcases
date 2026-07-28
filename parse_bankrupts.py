#!/usr/bin/env python3
"""Парсер банкротства по ИНН через JSON API bankrot.fedresurs.ru."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from openpyxl.worksheet.worksheet import Worksheet

from excel_utils import ensure_column

BASE_URL = "https://bankrot.fedresurs.ru"
WARMUP_URL = f"{BASE_URL}/bankrupts"
PRSN_URL = f"{BASE_URL}/backend/prsnbankrupts"
CMP_URL = f"{BASE_URL}/backend/cmpbankrupts"

BANKRUPT_HEADER = "Банкрот"

REQUEST_TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": WARMUP_URL,
    "Origin": BASE_URL,
}

logger = logging.getLogger(__name__)


class FedresursError(Exception):
    """Ошибка запроса к API Федресурса (в т.ч. QRATOR)."""


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def warmup(session: requests.Session) -> None:
    """Прогрев: получить cookies QRATOR со страницы поиска."""
    logger.info("Банкрот: прогрев GET %s", WARMUP_URL)
    response = session.get(WARMUP_URL, timeout=REQUEST_TIMEOUT)
    if response.status_code in (403, 451):
        raise FedresursError(
            f"QRATOR блокирует доступ при прогреве (HTTP {response.status_code}). "
            "Попробуйте позже или с другой сети."
        )
    response.raise_for_status()
    logger.info("Банкрот: прогрев OK (HTTP %s)", response.status_code)


def fetch_endpoint(
    session: requests.Session,
    url: str,
    inn: str,
) -> list[dict[str, Any]]:
    params = {"searchString": inn, "limit": 15, "offset": 0}
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)

    if response.status_code in (403, 451):
        raise FedresursError(
            f"QRATOR блокирует API (HTTP {response.status_code}) для ИНН {inn}"
        )
    if response.status_code != 200:
        raise FedresursError(
            f"HTTP {response.status_code} для {url}: {response.text[:200]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise FedresursError(f"Ответ не JSON для ИНН {inn}") from exc

    page_data = payload.get("pageData") or []
    if not isinstance(page_data, list):
        return []
    return [item for item in page_data if isinstance(item, dict)]


def search_bankrupts(session: requests.Session, inn: str) -> list[dict[str, Any]]:
    """Выбрать endpoint(s) по длине ИНН и вернуть pageData."""
    length = len(inn)
    if length == 12:
        return fetch_endpoint(session, PRSN_URL, inn)
    if length == 10:
        return fetch_endpoint(session, CMP_URL, inn)

    results: list[dict[str, Any]] = []
    results.extend(fetch_endpoint(session, PRSN_URL, inn))
    results.extend(fetch_endpoint(session, CMP_URL, inn))
    return results


def format_record(item: dict[str, Any]) -> str:
    """Собрать одну строку сводки из записи API."""
    name = item.get("fio") or item.get("name") or ""
    inn = item.get("inn") or ""
    region = item.get("region") or ""

    case = item.get("lastLegalCase") or {}
    if not isinstance(case, dict):
        case = {}
    case_number = case.get("number") or ""
    status = case.get("status") or {}
    if not isinstance(status, dict):
        status = {}
    status_desc = status.get("description") or ""

    case_part = f"дело {case_number}" if case_number else "дело —"
    parts = [
        str(name).strip(),
        str(inn).strip(),
        case_part,
        str(status_desc).strip(),
        str(region).strip(),
    ]
    return " | ".join(p for p in parts if p)


def format_summary(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    return "; ".join(format_record(r) for r in records)


def ensure_bankrupt_column(ws: Worksheet, headers: dict[str, int]) -> int:
    return ensure_column(ws, BANKRUPT_HEADER, headers)


def process_rows(
    ws: Worksheet,
    rows: list[tuple[int, str]],
    bankrupt_col: int,
    delay: float,
) -> None:
    """Заполнить колонку Банкрот для списка строк."""
    if not rows:
        return

    session = create_session()
    warmup(session)

    total = len(rows)
    for index, (row, inn) in enumerate(rows, start=1):
        logger.info("Банкрот [%s/%s] ИНН %s (строка %s)", index, total, inn, row)
        try:
            records = search_bankrupts(session, inn)
            summary = format_summary(records)
            ws.cell(row, bankrupt_col).value = summary if summary else None
            if summary:
                logger.info("  найдено: %s", summary)
            else:
                logger.info("  ничего не найдено")
        except FedresursError as exc:
            logger.error("  ошибка: %s (ячейка Банкрот не изменена)", exc)
        except requests.RequestException as exc:
            logger.error("  сетевая ошибка: %s (ячейка Банкрот не изменена)", exc)

        if index < total and delay > 0:
            time.sleep(delay)
