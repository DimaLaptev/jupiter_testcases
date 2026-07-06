# 1.7.1

import logging
import os
import zipfile

from config_ews import REPORS_DEPO_DIRECTORY
from get_month_name_dir import get_current_year_month

logger = logging.getLogger(__name__)


def _rsd_edo_directory() -> str:
    """Каталог RSD/EDO за текущий отчётный месяц — вычисляется при каждом запуске."""
    month = get_current_year_month()
    path = os.path.normpath(
        os.path.join(
            REPORS_DEPO_DIRECTORY or "",
            month,
            "RSD",
            "EDO",
        )
    )
    logger.info(
        "Путь к каталогу: REPORS_DEPO_DIRECTORY=%r, month=%s -> %s",
        REPORS_DEPO_DIRECTORY,
        month,
        path,
    )
    return path


def _find_zip_files(root_dir: str) -> list[str]:
    """Рекурсивный поиск .zip в каталоге и подкаталогах."""
    found: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for name in filenames:
            if name.lower().endswith(".zip"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def unpack_zip(filename: str | None = None, directoria: str | None = None) -> bool:
    """Распаковка одного архива. directoria — каталог, где лежит архив (и куда распаковать)."""
    if not filename or not directoria:
        logger.error("unpack_zip: не переданы filename=%r или directoria=%r", filename, directoria)
        return False

    archive_name = os.path.join(directoria, filename)
    logger.info("Распаковка: %s -> %s", archive_name, directoria)

    if not os.path.isfile(archive_name):
        logger.error("Архив не найден или не является файлом: %s", archive_name)
        return False

    try:
        with zipfile.ZipFile(archive_name, "r") as archive:
            members = archive.namelist()
            logger.info("Архив %s: файлов внутри — %d", filename, len(members))
            archive.extractall(directoria)
        logger.info("Архив %s успешно распакован в %s", archive_name, directoria)
        return True
    except Exception:
        logger.exception(
            "Ошибка при распаковке архива %s в %s",
            archive_name,
            directoria,
        )
        return False


def _unpack_zip_at_path(archive_path: str) -> bool:
    """Распаковка архива по полному пути."""
    directoria = os.path.dirname(archive_path)
    filename = os.path.basename(archive_path)
    return unpack_zip(filename, directoria)


def run_unpack_zip_jobs() -> None:
    """Точка входа для планировщика (scheduler) и __main__ — README 1.7.1."""
    logger.info("=== unpack_zip: старт задачи 1.7.1 ===")
    logger.info("Текущий рабочий каталог (cwd): %s", os.getcwd())

    directoria = _rsd_edo_directory()

    if not REPORS_DEPO_DIRECTORY:
        logger.warning(
            "REPORS_DEPO_DIRECTORY не задан в окружении — путь может быть относительным к cwd"
        )

    if not os.path.isdir(directoria):
        logger.error("Каталог для распаковки не существует: %s", directoria)
        logger.info("=== unpack_zip: завершено (каталог отсутствует) ===")
        return

    try:
        entries = os.listdir(directoria)
    except OSError:
        logger.exception("Не удалось прочитать содержимое каталога: %s", directoria)
        logger.info("=== unpack_zip: завершено с ошибкой ===")
        return

    logger.info("Каталог %s существует, элементов в корне: %d", directoria, len(entries))
    if entries:
        logger.info("Содержимое корня (первые 50): %s", entries[:50])

    total_ok = 0
    total_fail = 0
    pass_num = 0
    max_passes = 50

    while pass_num < max_passes:
        pass_num += 1
        zip_paths = _find_zip_files(directoria)
        if not zip_paths:
            logger.info("Проход %d: архивов .zip не найдено — распаковка завершена", pass_num)
            break

        logger.info(
            "Проход %d: найдено архивов .zip — %d: %s",
            pass_num,
            len(zip_paths),
            zip_paths,
        )

        pass_ok = 0
        pass_fail = 0
        for archive_path in zip_paths:
            if _unpack_zip_at_path(archive_path):
                pass_ok += 1
            else:
                pass_fail += 1

        total_ok += pass_ok
        total_fail += pass_fail
        logger.info(
            "Проход %d завершён: успешно=%d, ошибок=%d",
            pass_num,
            pass_ok,
            pass_fail,
        )

        if pass_fail > 0 and pass_ok == 0:
            logger.error(
                "Проход %d: ни один архив не распакован — останавливаем цикл",
                pass_num,
            )
            break
    else:
        logger.warning(
            "Достигнут лимит проходов (%d) — возможны вложенные архивы, требующие ещё итераций",
            max_passes,
        )

    logger.info(
        "=== unpack_zip: итог — проходов=%d, успешно=%d, ошибок=%d ===",
        pass_num,
        total_ok,
        total_fail,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_unpack_zip_jobs()
