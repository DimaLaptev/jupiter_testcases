# 1.7.3

import os
import shutil

from config_ews import REPORS_DEPO_DIRECTORY
from file_handler import move_file_to_dir
from get_month_name_dir import get_current_year_month


def move_files_to_dir_struct_2():
    month = get_current_year_month()
    root = REPORS_DEPO_DIRECTORY or ""
    dir_list = [os.path.normpath(os.path.join(root, month, "RSD", "EDO"))]
    distination_dir_list = [
        os.path.normpath(os.path.join(root, month, "RSD", "D")),
        os.path.normpath(os.path.join(root, month, "RSD", "I")),
        os.path.normpath(os.path.join(root, month, "RSD", "R")),
        os.path.normpath(os.path.join(root, month, "RSD", "REP")),
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
                    os.remove(os.path.join(directoria, filename))
                    print(f"Файл {filename} вне паттернов, удаляем")

            elif file_extension.lower() == "xlsx":
                if filename[:5] == "R-01_":
                    move_file_to_dir(filename, directoria, distination_dir_list[3])
            else:
                os.remove(os.path.join(directoria, filename))
                print(f"Файл {filename} вне паттернов, удаляем")


if __name__ == "__main__":
    move_files_to_dir_struct_2()
