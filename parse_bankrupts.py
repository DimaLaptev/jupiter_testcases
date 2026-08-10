#!/usr/bin/env python3
"""Парсер банкротства по ИНН через JSON API bankrot.fedresurs.ru."""

from __future__ import annotations

import logging
from typing import Any

import requests

BASE_URL = "https://bankrot.fedresurs.ru"
WARMUP_URL = f"{BASE_URL}/bankrupts"
PRSN_URL = f"{BASE_URL}/backend/prsnbankrupts"
CMP_URL = f"{BASE_URL}/backend/cmpbankrupts"

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


def is_bankrupt(session: requests.Session, inn: str) -> bool:
    """True, если по ИНН есть записи о банкротстве."""
    return bool(search_bankrupts(session, inn))
