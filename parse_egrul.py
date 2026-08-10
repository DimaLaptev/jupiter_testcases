"""Поиск по ЕГРЮЛ/ЕГРИП (egrul.nalog.ru) по ИНН."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

BASE_URL = "https://egrul.nalog.ru"
INDEX_URL = f"{BASE_URL}/index.html"
SEARCH_URL = f"{BASE_URL}/"
RESULT_URL = f"{BASE_URL}/search-result"

REQUEST_TIMEOUT = 30
POLL_INTERVAL = 1.0
POLL_MAX_ATTEMPTS = 30

# Retry + backoff при captcha (вариант 1)
DEFAULT_CAPTCHA_RETRIES = 5
DEFAULT_CAPTCHA_BACKOFF = 30.0
CAPTCHA_BACKOFF_FACTOR = 2.0
CAPTCHA_BACKOFF_MAX = 180.0

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


class CaptchaRequiredError(EgrulError):
    """Сервер требует captcha (captchaSearch / captchaRequired)."""


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


def _payload_requires_captcha(payload: dict[str, Any]) -> bool:
    if payload.get("captchaRequired"):
        return True
    errors = payload.get("ERRORS")
    if isinstance(errors, dict) and "captchaSearch" in errors:
        return True
    return False


def _parse_post_payload(response: requests.Response, inn: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise EgrulError(
            f"Ответ POST не JSON для ИНН {inn} (HTTP {response.status_code})"
        ) from exc
    if not isinstance(payload, dict):
        raise EgrulError(f"Неожиданный JSON POST для ИНН {inn}: {payload!r}")
    return payload


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
        try:
            payload = _parse_post_payload(response, inn)
        except EgrulError:
            raise EgrulError(
                f"HTTP {response.status_code} POST /: {response.text[:200]}"
            ) from None
        if _payload_requires_captcha(payload):
            raise CaptchaRequiredError(
                f"Требуется captcha для ИНН {inn}: {payload.get('ERRORS') or payload}"
            )
        raise EgrulError(
            f"HTTP {response.status_code} POST /: {response.text[:200]}"
        )

    payload = _parse_post_payload(response, inn)

    if _payload_requires_captcha(payload):
        raise CaptchaRequiredError(
            f"Требуется captcha для ИНН {inn}: {payload.get('ERRORS') or payload}"
        )
    if payload.get("ERRORS"):
        raise EgrulError(f"Ошибки API для ИНН {inn}: {payload['ERRORS']}")

    token = payload.get("t")
    if not token:
        raise EgrulError(f"Нет токена поиска t для ИНН {inn}: {payload}")

    return poll_search_result(session, str(token))


def _captcha_wait_seconds(attempt: int, backoff_base: float) -> float:
    """Экспоненциальный backoff: base, base*2, … до CAPTCHA_BACKOFF_MAX."""
    wait = backoff_base * (CAPTCHA_BACKOFF_FACTOR ** max(0, attempt - 1))
    return min(wait, CAPTCHA_BACKOFF_MAX)


def search_egrul_with_retry(
    session: requests.Session,
    inn: str,
    *,
    captcha_retries: int = DEFAULT_CAPTCHA_RETRIES,
    captcha_backoff: float = DEFAULT_CAPTCHA_BACKOFF,
) -> tuple[list[dict[str, Any]], requests.Session]:
    """
    Поиск с повтором того же ИНН при captcha.

    При CaptchaRequiredError ждём backoff, обновляем session (новый JSESSIONID)
    и пробуем снова. Возвращает (records, актуальная session).
    """
    attempts = max(1, captcha_retries)
    last_error: CaptchaRequiredError | None = None

    for attempt in range(1, attempts + 1):
        try:
            return search_egrul(session, inn), session
        except CaptchaRequiredError as exc:
            last_error = exc
            if attempt >= attempts:
                break
            wait = _captcha_wait_seconds(attempt, captcha_backoff)
            logger.warning(
                "  captcha (попытка %s/%s): ждём %.0f с и обновляем сессию… (%s)",
                attempt,
                attempts,
                wait,
                exc,
            )
            time.sleep(wait)
            session = create_session()
            warmup(session)

    assert last_error is not None
    raise last_error


def has_liquidation_date(records: list[dict[str, Any]]) -> bool:
    """True, если в выдаче есть дата прекращения деятельности (поле e)."""
    for item in records:
        end_date = item.get("e")
        if end_date and str(end_date).strip():
            return True
    return False
