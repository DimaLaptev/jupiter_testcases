# 1.6

import shutil
import os

from file_handler import move_file_to_dir
from get_month_name_dir import get_current_year_month
from config_ews import DOMRF_OPEN_DIR, DOMRFIA_OPEN_DIR, GPB_BASE_DIR


def move_files_to_dir_struct() -> None:
    month = get_current_year_month()

    dir_DOMRF = DOMRF_OPEN_DIR
    dir_DOMRFIA = DOMRFIA_OPEN_DIR
    dir_list = [dir_DOMRF, dir_DOMRFIA]

    distination_dir_list = [
        f"{GPB_BASE_DIR}{month}/GPB/D",
        f"{GPB_BASE_DIR}{month}/GPB/I",
        f"{GPB_BASE_DIR}{month}/GPB/R",
        f"{GPB_BASE_DIR}{month}/GPB/REP",
        f"{GPB_BASE_DIR}{month}/GPB/SPR",
    ]

    for directoria in dir_list:
        for filename in os.listdir(directoria):
            file_extension = filename[-4:]
            # print(f'{file_extension.lower()=}')

            if file_extension.lower() == ".msg":
                if filename[:2] == "D_":
                    move_file_to_dir(filename, directoria, distination_dir_list[0])
                elif filename[:2] == "I_":
                    move_file_to_dir(filename, directoria, distination_dir_list[1])
                elif filename[:2] == "R_":
                    move_file_to_dir(filename, directoria, distination_dir_list[2])
                else:
                    print(f"Файл {filename} вне паттернов, оставляем")

            elif file_extension.lower() == ".xls":
                if filename[:4] == "SPR_" or filename[:1] == "O":
                    move_file_to_dir(filename, directoria, distination_dir_list[3])

            elif file_extension.lower() == ".pdf" and filename[:1] == "Q":
                move_file_to_dir(filename, directoria, distination_dir_list[3])

            elif file_extension.lower() == ".zip" and filename[:4] == "SPR_":
                move_file_to_dir(filename, directoria, distination_dir_list[3])

            elif file_extension.lower() == ".txt" and filename[:9] == "S01MD103_":
                move_file_to_dir(filename, directoria, distination_dir_list[3])

            else:
                print(f"Файл {filename} вне паттернов, оставляем")


if __name__ == "__main__":
    move_files_to_dir_struct()

