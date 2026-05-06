# 2.2

import os
import re

from config_ews import REPORS_DEPO_DIRECTORY
from file_handler import move_file_to_dir
from get_month_name_dir import get_current_year_month


def _region_month_paths(subdir_after_region: str) -> str:
    month = get_current_year_month()
    base = REPORS_DEPO_DIRECTORY or ""
    return os.path.normpath(os.path.join(base, month, "REGION", subdir_after_region))


def region_edo_directory() -> str:
    """Абсолютный путь к REPORS_DEPO_DIRECTORY/<месяц>/REGION/EDO."""
    return _region_month_paths("EDO")


# Как при сохранении дубля в region_edo_download: f"{name_part}_{ts}{ext}", ts = %Y%m%d_%H%M%S
_IS_XLS_DUP_TS_SUFFIX = re.compile(r"_\d{8}_\d{6}$")


def _is_is_xls_duplicate_suffixed(filename: str) -> bool:
    """True, если имя уже с суффиксом даты/времени дубля (не переносим из EDO)."""
    stem, _ = os.path.splitext(filename)
    return bool(_IS_XLS_DUP_TS_SUFFIX.search(stem))


def move_IS_xls_files() -> None:
    dir_region = _region_month_paths("EDO")
    destination_dir = _region_month_paths("REP")

    if not os.path.isdir(dir_region):
        print(f"Каталог {dir_region} не существует, пропуск.")
        return

    os.makedirs(destination_dir, exist_ok=True)

    for filename in os.listdir(dir_region):
        if len(filename) < 4:
            continue
        file_extension = filename[-4:]
        if file_extension.lower() == ".xls":
            if filename[:2] == "IS":
                if _is_is_xls_duplicate_suffixed(filename):
                    continue
                try:
                    move_file_to_dir(filename, dir_region, destination_dir)
                except Exception as e:
                    print(f"Ошибка при перемещении файла {filename}: {e}")


def _matches_spr_patterns(filename: str) -> bool:
    """Подходит ли имя файла под выгрузку в REGION/SPR (паттерны по ТЗ)."""
    lower = filename.lower()
    if not (lower.endswith(".pdf") or lower.endswith(".zip")):
        return False

    is_pdf = lower.endswith(".pdf")

    if is_pdf:
        if filename[:2] == "IS":
            return True
        if filename.startswith("S_"):
            return True
        if "назначение" in lower:
            return True
        if "открытие счета" in lower:
            return True
        return False

    # .zip
    if filename.startswith("S_"):
        return True
    if "назначение" in lower:
        return True
    if "открытие счета" in lower:
        return True
    if "дом" in lower:
        return True
    if "иа" in lower:
        return True
    if "тфб" in lower:
        return True
    if "интех" in lower:
        return True
    return False


def should_preserve_in_region_edo(filename: str) -> bool:
    """Не удалять cleanером: материал для SPR или IS*.xls без суффикса дубля (ждут переноса в REP)."""
    if _matches_spr_patterns(filename):
        return True
    if len(filename) < 4:
        return False
    if filename[-4:].lower() == ".xls" and filename[:2] == "IS":
        return not _is_is_xls_duplicate_suffixed(filename)
    return False


def move_pdf_zip_files() -> None:
    """Перемещение PDF/ZIP из REGION/EDO в REGION/SPR по заданным шаблонам."""
    dir_edo = _region_month_paths("EDO")
    destination_spr = _region_month_paths("SPR")

    if not os.path.isdir(dir_edo):
        print(f"Каталог {dir_edo} не существует, пропуск.")
        return

    os.makedirs(destination_spr, exist_ok=True)

    for filename in os.listdir(dir_edo):
        if not _matches_spr_patterns(filename):
            continue
        try:
            move_file_to_dir(filename, dir_edo, destination_spr)
        except Exception as e:
            print(f"Ошибка при перемещении файла {filename}: {e}")


if __name__ == "__main__":
    move_IS_xls_files()
    move_pdf_zip_files()
