#!/usr/bin/env python3
"""Точка входа: проверка ИНН в Федресурс (банкротство) и/или ЕГРЮЛ/ЕГРИП."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from openpyxl import load_workbook

import parse_bankrupts
import parse_egrul
from excel_utils import collect_inn_rows, require_inn_column
from parse_bankrupts import FedresursError
from parse_egrul import EgrulError

DEFAULT_INPUT = Path("source/data.xlsx")
DEFAULT_DELAY = 1.5
MODE_BOTH = "both"
MODE_BANKRUPT = "bankrupt"
MODE_EGRUL = "egrul"
MODES = (MODE_BOTH, MODE_BANKRUPT, MODE_EGRUL)

logger = logging.getLogger(__name__)


def process_workbook(
    input_path: Path,
    output_path: Path,
    delay: float,
    mode: str,
    *,
    captcha_retries: int = parse_egrul.DEFAULT_CAPTCHA_RETRIES,
    captcha_backoff: float = parse_egrul.DEFAULT_CAPTCHA_BACKOFF,
) -> None:
    if not input_path.is_file():
        raise FileNotFoundError(
            f"Файл не найден: {input_path}. "
            "Положите Excel в source/data.xlsx (колонки: id, Статус ДА, КА, ИНН)."
        )

    wb = load_workbook(input_path)
    ws = wb.active
    inn_col, headers = require_inn_column(ws)

    run_bankrupt = mode in (MODE_BOTH, MODE_BANKRUPT)
    run_egrul = mode in (MODE_BOTH, MODE_EGRUL)

    bankrupt_col = None
    egrul_col = None
    liq_col = None
    if run_bankrupt:
        bankrupt_col = parse_bankrupts.ensure_bankrupt_column(ws, headers)
    if run_egrul:
        egrul_col, liq_col = parse_egrul.ensure_egrul_columns(ws, headers)

    rows = collect_inn_rows(ws, inn_col)
    skipped = max(0, ws.max_row - 1 - len(rows))
    if skipped:
        logger.info("Пропущено строк с пустым ИНН: %s", skipped)

    if not rows:
        logger.warning("Нет строк с ИНН для обработки")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        return

    logger.info("Режим: %s | строк с ИНН: %s", mode, len(rows))

    if run_bankrupt and bankrupt_col is not None:
        parse_bankrupts.process_rows(ws, rows, bankrupt_col, delay)

    if run_egrul and egrul_col is not None and liq_col is not None:
        parse_egrul.process_rows(
            ws,
            rows,
            egrul_col,
            liq_col,
            delay,
            captcha_retries=captcha_retries,
            captcha_backoff=captcha_backoff,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    logger.info("Сохранено: %s", output_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Проверка ИНН: банкротство (bankrot.fedresurs.ru) "
            "и/или ЕГРЮЛ/ЕГРИП (egrul.nalog.ru)"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default=MODE_BOTH,
        help=(
            "Что запускать: bankrupt | egrul | both "
            f"(по умолчанию {MODE_BOTH})"
        ),
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
    parser.add_argument(
        "--captcha-retries",
        type=int,
        default=parse_egrul.DEFAULT_CAPTCHA_RETRIES,
        help=(
            "Число попыток одного ИНН при captcha ЕГРЮЛ "
            f"(по умолчанию {parse_egrul.DEFAULT_CAPTCHA_RETRIES})"
        ),
    )
    parser.add_argument(
        "--captcha-backoff",
        type=float,
        default=parse_egrul.DEFAULT_CAPTCHA_BACKOFF,
        help=(
            "Начальная пауза (сек) перед повтором при captcha; "
            "далее x2 до 180 с "
            f"(по умолчанию {parse_egrul.DEFAULT_CAPTCHA_BACKOFF})"
        ),
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
        process_workbook(
            args.input,
            output,
            args.delay,
            args.mode,
            captcha_retries=args.captcha_retries,
            captcha_backoff=args.captcha_backoff,
        )
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except (FedresursError, EgrulError) as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
