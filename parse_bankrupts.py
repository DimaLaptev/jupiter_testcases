#!/usr/bin/env python3
"""Парсер банкротства по ИНН через JSON API bankrot.fedresurs.ru."""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

BASE_URL = "https://bankrot.fedresurs.ru"
WARMUP_URL = f"{BASE_URL}/bankrupts"
PRSN_URL = f"{BASE_URL}/backend/prsnbankrupts"
CMP_URL = f"{BASE_URL}/backend/cmpbankrupts"

INN_HEADER = "ИНН"
BANKRUPT_HEADER = "Банкрот"

DEFAULT_INPUT = Path("source/data.xlsx")
DEFAULT_DELAY = 1.5
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


def normalize_inn(value: Any) -> str:
    """Нормализовать ИНН: только цифры."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return re.sub(r"\D", "", text)


def find_header_columns(ws: Worksheet) -> tuple[int, int]:
    """Найти индекс колонки ИНН и Банкрот (1-based). Создать Банкрот при отсутствии."""
    headers: dict[str, int] = {}
    for col in range(1, ws.max_column + 1):
        cell_value = ws.cell(1, col).value
        if cell_value is None:
            continue
        headers[str(cell_value).strip()] = col

    if INN_HEADER not in headers:
        raise ValueError(
            f"В первой строке нет колонки «{INN_HEADER}». "
            f"Найдены: {', '.join(headers) or '(пусто)'}"
        )

    inn_col = headers[INN_HEADER]
    if BANKRUPT_HEADER in headers:
        bankrupt_col = headers[BANKRUPT_HEADER]
    else:
        bankrupt_col = ws.max_column + 1
        ws.cell(1, bankrupt_col).value = BANKRUPT_HEADER

    return inn_col, bankrupt_col


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def warmup(session: requests.Session) -> None:
    """Прогрев: получить cookies QRATOR со страницы поиска."""
    logger.info("Прогрев сессии: GET %s", WARMUP_URL)
    response = session.get(WARMUP_URL, timeout=REQUEST_TIMEOUT)
    if response.status_code in (403, 451):
        raise FedresursError(
            f"QRATOR блокирует доступ при прогреве (HTTP {response.status_code}). "
            "Попробуйте позже или с другой сети."
        )
    response.raise_for_status()
    logger.info("Прогрев OK (HTTP %s)", response.status_code)


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

    # Неоднозначная длина — оба endpoint
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


def process_workbook(
    input_path: Path,
    output_path: Path,
    delay: float,
) -> None:
    if not input_path.is_file():
        raise FileNotFoundError(
            f"Файл не найден: {input_path}. "
            "Положите Excel в source/data.xlsx (колонки: id, Статус ДА, КА, ИНН)."
        )

    wb = load_workbook(input_path)
    ws = wb.active
    inn_col, bankrupt_col = find_header_columns(ws)

    rows: list[tuple[int, str]] = []
    for row in range(2, ws.max_row + 1):
        raw = ws.cell(row, inn_col).value
        inn = normalize_inn(raw)
        if not inn:
            logger.info("Строка %s: пустой ИНН — пропуск", row)
            continue
        rows.append((row, inn))

    total = len(rows)
    if total == 0:
        logger.warning("Нет строк с ИНН для обработки")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        return

    session = create_session()
    warmup(session)

    for index, (row, inn) in enumerate(rows, start=1):
        logger.info("[%s/%s] ИНН %s (строка %s)", index, total, inn, row)
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    logger.info("Сохранено: %s", output_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Проверка ИНН на банкротство через bankrot.fedresurs.ru",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Путь к Excel (по умолчанию {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Куда сохранить результат (по умолчанию = --input)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Пауза между запросами в секундах (по умолчанию {DEFAULT_DELAY})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args(argv)
    output = args.output if args.output is not None else args.input

    try:
        process_workbook(args.input, output, args.delay)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except FedresursError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
