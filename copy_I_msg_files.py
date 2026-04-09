# 1.4

import os
import shutil

from config_ews import DOMRF_OPEN_DIR, DOMRFIA_OPEN_DIR, EIS_DIR

dir_list = [DOMRF_OPEN_DIR, DOMRFIA_OPEN_DIR]


def copy_I_msg_files(directories_list: list = None):

    distination_dir = EIS_DIR
    for directoria in dir_list:
        for filename in os.listdir(directoria):
            file_extension = filename[-4:]
            if file_extension.lower() == ".msg":
                if filename[:2] == "I_":
                    try:
                        shutil.copy(f"{directoria}/{filename}", distination_dir)
                        print(f"Файл {filename} успешно скопирован")
                    except Exception as e:
                        print(f"Ошибка при копировании файла {filename}: {e}")


if __name__ == "__main__":
    copy_I_msg_files(dir_list)
