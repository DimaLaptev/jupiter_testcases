# 1.7.1

import os
import zipfile

from config_ews import REPORS_DEPO_DIRECTORY
from get_month_name_dir import get_current_year_month

directoria = os.path.normpath(
    os.path.join(
        REPORS_DEPO_DIRECTORY or "",
        get_current_year_month(),
        "RSD",
        "EDO",
    )
)


def unpack_zip(filename: str = None, directoria: str = None):
    # Каталог, куда хотим распаковать файлы
    archive_name = os.path.join(directoria, filename)
    print(archive_name)
    # Открытие и распаковка архива
    try:
        with zipfile.ZipFile(archive_name, "r") as archive:
            archive.extractall(directoria)
        print(f"Архив {archive_name} успешно распакован в {directoria}.")
    except Exception as e:
        print(f"Ошибка при распаковке архива {archive_name} в {directoria}!")
        print(e)


def run_unpack_zip_jobs() -> None:
    """Точка входа для планировщика (scheduler) и __main__ — README 1.7.1."""
    # Ищем zip-файл
    for filename in os.listdir(directoria):
        file_extension = filename[-4:]
        if file_extension.lower() == ".zip":
            unpack_zip(filename, directoria)
    for filename in os.listdir(directoria):
        file_extension = filename[-4:]
        if file_extension.lower() == ".zip" and filename[:4] == "R-01":
            unpack_zip(filename, directoria)


if __name__ == "__main__":
    run_unpack_zip_jobs()
