"""
Удаление из REGION/EDO файлов, которые file_handler_4.py не переносит (ни в REP, ни в SPR).

Сохраняются те же имена, что не трогает/переносит логика file_handler_4: паттерны (patterns) SPR,
IS*.xls без суффикса дубля по региону (duplicate, как в region_edo_download). IS*.xls с _YYYYMMDD_HHMMSS
удаляются как вторичные копии.
"""

from __future__ import annotations

import logging
import os

from file_handler_4 import region_edo_directory, should_preserve_in_region_edo

logger = logging.getLogger(__name__)


def run_region_file_cleaner() -> None:
    edo = region_edo_directory()
    if not os.path.isdir(edo):
        logger.info("REGION/EDO нет (%s), пропуск.", edo)
        return

    removed = 0
    for name in os.listdir(edo):
        path = os.path.join(edo, name)
        if not os.path.isfile(path):
            continue
        if should_preserve_in_region_edo(name):
            continue
        try:
            os.remove(path)
            removed += 1
            logger.info("Удалён: %s", path)
        except OSError:
            logger.exception("Не удалось удалить %s", path)

    logger.info("region_file_cleaner: каталог %s, удалено файлов: %d", edo, removed)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_region_file_cleaner()
