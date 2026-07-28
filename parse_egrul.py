"""Поиск по ЕГРЮЛ/ЕГРИП (egrul.nalog.ru) по ИНН."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from openpyxl.worksheet.worksheet import Worksheet

from excel_utils import ensure_column

BASE_URL = "https://egrul.nalog.ru"
INDEX_URL = f"{BASE_URL}/index.html"
SEARCH_URL = f"{BASE_URL}/"
RESULT_URL = f"{BASE_URL}/search-result"

EGRUL_HEADER = "ЕГРЮЛ"
LIQUIDATION_HEADER = "Дата ликвидации"

REQUEST_TIMEOUT = 30
POLL_INTERVAL = 1.0
POLL_MAX_ATTEMPTS = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": INDEX_URL,
    "Origin": BASE_URL,
}

logger = logging.getLogger(__name__)


class EgrulError(Exception):
    """Ошибка запроса к egrul.nalog.ru."""


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def warmup(session: requests.Session) -> None:
    logger.info("ЕГРЮЛ: прогрев GET %s", INDEX_URL)
    response = session.get(INDEX_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    logger.info("ЕГРЮЛ: прогрев OK (HTTP %s)", response.status_code)


def _is_real_row(item: dict[str, Any]) -> bool:
    """Отбросить служебные строки справки «данных не найдено»."""
    kind = str(item.get("k") or "")
    if kind.startswith("sprav"):
        return False
    cnt = item.get("cnt")
    if cnt is not None and str(cnt) == "0":
        return False
    return True


def poll_search_result(session: requests.Session, token: str) -> list[dict[str, Any]]:
    url = f"{RESULT_URL}/{token}"
    for _ in range(POLL_MAX_ATTEMPTS):
        response = session.get(
            url,
            params={"r": int(time.time() * 1000)},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise EgrulError(f"HTTP {response.status_code} search-result: {response.text[:200]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise EgrulError("Ответ search-result не JSON") from exc

        if payload.get("status") == "wait":
            time.sleep(POLL_INTERVAL)
            continue

        rows = payload.get("rows") or []
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict) and _is_real_row(r)]

    raise EgrulError(f"Таймаут ожидания результата поиска (token={token[:16]}…)")


def search_egrul(session: requests.Session, inn: str) -> list[dict[str, Any]]:
    """POST поиск + poll результата. Пустой список = «данных не найдено»."""
    response = session.post(
        SEARCH_URL,
        data={
            "query": inn,
            "vyp3CaptchaToken": "",
            "page": "",
            "region": "",
            "PreventChromeAutocomplete": "",
        },
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise EgrulError(f"HTTP {response.status_code} POST /: {response.text[:200]}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise EgrulError(f"Ответ POST не JSON для ИНН {inn}") from exc

    if payload.get("ERRORS"):
        raise EgrulError(f"Ошибки API для ИНН {inn}: {payload['ERRORS']}")
    if payload.get("captchaRequired"):
        raise EgrulError(
            f"Требуется captcha для ИНН {inn}. Повторите позже или решите captcha вручную."
        )

    token = payload.get("t")
    if not token:
        raise EgrulError(f"Нет токена поиска t для ИНН {inn}: {payload}")

    return poll_search_result(session, str(token))


def format_record(item: dict[str, Any]) -> str:
    """Одна строка сводки из записи поиска ЕГРЮЛ/ЕГРИП."""
    name = item.get("n") or item.get("c") or ""
    short = item.get("c") or ""
    inn = item.get("i") or ""
    ogrn = item.get("o") or ""
    reg_date = item.get("r") or ""
    end_date = item.get("e") or ""
    region = item.get("rn") or ""
    chief = item.get("g") or ""

    parts = [
        str(name).strip(),
        f"ИНН {inn}" if inn else "",
        f"ОГРН {ogrn}" if ogrn else "",
        f"рег. {reg_date}" if reg_date else "",
        f"прекращение {end_date}" if end_date else "",
        str(region).strip(),
        str(chief).strip(),
    ]
    # если полное и краткое имя различаются — краткое уже в n/c; не дублируем без нужды
    if short and short != name and short not in parts[0]:
        parts.insert(1, str(short).strip())
    return " | ".join(p for p in parts if p)


def format_summary(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    return "; ".join(format_record(r) for r in records)


def extract_liquidation_date(records: list[dict[str, Any]]) -> str:
    """Дата прекращения деятельности (поле e) — аналог «Дата ликвидации»."""
    dates: list[str] = []
    for item in records:
        end_date = item.get("e")
        if end_date:
            text = str(end_date).strip()
            if text and text not in dates:
                dates.append(text)
    return "; ".join(dates)


def ensure_egrul_columns(ws: Worksheet, headers: dict[str, int]) -> tuple[int, int]:
    egrul_col = ensure_column(ws, EGRUL_HEADER, headers)
    liq_col = ensure_column(ws, LIQUIDATION_HEADER, headers)
    return egrul_col, liq_col


def process_rows(
    ws: Worksheet,
    rows: list[tuple[int, str]],
    egrul_col: int,
    liq_col: int,
    delay: float,
) -> None:
    """Заполнить колонки ЕГРЮЛ и Дата ликвидации для списка строк."""
    if not rows:
        return

    session = create_session()
    warmup(session)

    total = len(rows)
    for index, (row, inn) in enumerate(rows, start=1):
        logger.info("ЕГРЮЛ [%s/%s] ИНН %s (строка %s)", index, total, inn, row)
        try:
            records = search_egrul(session, inn)
            summary = format_summary(records)
            liq_date = extract_liquidation_date(records)
            ws.cell(row, egrul_col).value = summary if summary else None
            ws.cell(row, liq_col).value = liq_date if liq_date else None
            if summary:
                logger.info("  найдено: %s", summary)
                if liq_date:
                    logger.info("  дата ликвидации: %s", liq_date)
            else:
                logger.info("  данных не найдено")
        except EgrulError as exc:
            logger.error("  ошибка: %s (ячейки ЕГРЮЛ не изменены)", exc)
        except requests.RequestException as exc:
            logger.error("  сетевая ошибка: %s (ячейки ЕГРЮЛ не изменены)", exc)

        if index < total and delay > 0:
            time.sleep(delay)
