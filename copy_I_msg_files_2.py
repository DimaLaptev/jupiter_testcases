# 1.7.2

import os
import shutil

from config_ews import EIS_DIR, REPORS_DEPO_DIRECTORY
from get_month_name_dir import get_current_year_month


def copy_I_msg_files_2(directories_list: list = None):

    distination_dir = EIS_DIR
    for directoria in directories_list:
        for filename in os.listdir(directoria):
            file_extension = filename[-4:]
            if file_extension.lower() == ".msg":
                if filename[:2] == "I_":
                    try:
                        shutil.copy(f"{directoria}/{filename}", distination_dir)
                        print(f"Файл {filename} успешно скопирован")
                    except Exception as e:
                        print(f"Ошибка при копировании файла {filename}: {e}")


def run_copy_I_msg_files_2_default() -> None:
    """Точка входа для планировщика (scheduler) — каталог RSD/EDO за текущий «месяц»."""
    directoria = os.path.normpath(
        os.path.join(
            REPORS_DEPO_DIRECTORY or "",
            get_current_year_month(),
            "RSD",
            "EDO",
        )
    )
    copy_I_msg_files_2([directoria])


if __name__ == "__main__":
    run_copy_I_msg_files_2_default()
