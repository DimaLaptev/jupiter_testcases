# 1.5

import os
import shutil

from config_ews import DOMRF_OPEN_DIR, REPORTS_DIR


def copy_REP_xls_files():
    dir_DOMRF = DOMRF_OPEN_DIR
    distination_dir = REPORTS_DIR
    for filename in os.listdir(dir_DOMRF):
        file_extension = filename[-4:]
        # print(f'{file_extension.lower()=}')
        if file_extension.lower() == ".xls":
            if filename[:9] in ["REP_33563", "REP_33597"]:
                try:
                    shutil.copy(f"{dir_DOMRF}/{filename}", distination_dir)
                    print(f"Файл {filename} успешно скопирован")
                except Exception as e:
                    print(f"Ошибка при копировании файла {filename}: {e}")


if __name__ == "__main__":
    copy_REP_xls_files()
