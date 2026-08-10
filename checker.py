"""Оркестрация: проверка банкротства и даты ликвидации по ИНН."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable, Sequence
from typing import Any

import requests

import parse_bankrupts
import parse_egrul
from parse_bankrupts import FedresursError
from parse_egrul import CaptchaRequiredError, EgrulError

DEFAULT_DELAY = 1.5

YES = "да"
NO = "нет"

IDX_BANKRUPT = 0
IDX_LIQUIDATION = 1

logger = logging.getLogger(__name__)


def normalize_inn(value: Any) -> str:
    """Нормализовать ИНН: только цифры."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return re.sub(r"\D", "", text)


def check_inns(
    inns: Sequence[str] | Iterable[str],
    *,
    delay: float = DEFAULT_DELAY,
    captcha_retries: int = parse_egrul.DEFAULT_CAPTCHA_RETRIES,
    captcha_backoff: float = parse_egrul.DEFAULT_CAPTCHA_BACKOFF,
) -> dict[str, list[str]]:
    """
    Единая точка входа: проверка банкротства и даты ликвидации по списку ИНН.

    Для каждого ИНН запрашиваются Федресурс (банкрот) и ЕГРЮЛ (дата ликвидации).

    Args:
        inns: iterable ИНН.
        delay: пауза между ИНН (сек).
        captcha_retries: попыток при captcha ЕГРЮЛ.
        captcha_backoff: начальная пауза backoff при captcha (сек).

    Returns:
        dict: ключ — ИНН, значение — список из двух строк:
            [0] банкрот: «да» / «нет»
            [1] дата ликвидации: «да» / «нет»
    """
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in inns:
        inn = normalize_inn(raw)
        if not inn or inn in seen:
            continue
        seen.add(inn)
        normalized.append(inn)

    result: dict[str, list[str]] = {}
    if not normalized:
        logger.warning("Нет ИНН для обработки")
        return result

    logger.info("Проверка банкротства + ликвидации | ИНН: %s", len(normalized))

    bankrupt_session = parse_bankrupts.create_session()
    parse_bankrupts.warmup(bankrupt_session)
    egrul_session = parse_egrul.create_session()
    parse_egrul.warmup(egrul_session)

    total = len(normalized)
    for index, inn in enumerate(normalized, start=1):
        logger.info("[%s/%s] ИНН %s", index, total, inn)
        bankrupt_flag = NO
        liquidation_flag = NO

        try:
            found = parse_bankrupts.is_bankrupt(bankrupt_session, inn)
            bankrupt_flag = YES if found else NO
            logger.info("  банкрот: %s", bankrupt_flag)
        except FedresursError as exc:
            logger.error("  банкрот ошибка: %s → %s", exc, NO)
        except requests.RequestException as exc:
            logger.error("  банкрот сеть: %s → %s", exc, NO)

        try:
            records, egrul_session = parse_egrul.search_egrul_with_retry(
                egrul_session,
                inn,
                captcha_retries=captcha_retries,
                captcha_backoff=captcha_backoff,
            )
            liquidation_flag = (
                YES if parse_egrul.has_liquidation_date(records) else NO
            )
            logger.info("  дата ликвидации: %s", liquidation_flag)
        except CaptchaRequiredError as exc:
            logger.error(
                "  егрюл captcha после %s попыток: %s → %s",
                captcha_retries,
                exc,
                NO,
            )
        except EgrulError as exc:
            logger.error("  егрюл ошибка: %s → %s", exc, NO)
        except requests.RequestException as exc:
            logger.error("  егрюл сеть: %s → %s", exc, NO)

        result[inn] = [bankrupt_flag, liquidation_flag]

        # TODO: логировать ключ-значение по ИНН, у которых проставилось хоть одно «да»,
        # по мере заполнения словаря result (например: logger.info("%s -> %s", inn, result[inn])).

        if index < total and delay > 0:
            time.sleep(delay)

    return result
