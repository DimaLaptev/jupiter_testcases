
# 1.3

import os
import shutil
from typing import Optional

from file_handler_config_loader import load_file_handler_config


config = load_file_handler_config()

# Исходная директория, где будет выполняться поиск файлов
SOURCE_DIR = config["SOURCE_DIR"]

# Директории назначения для перемещения найденных файлов
DIR_DOMRF = config["DIR_DOMRF"]
DIR_DOMRFIA = config["DIR_DOMRFIA"]

# паттерн для папки DOMRF
pattern_DOMRF_MSG = config["pattern_DOMRF_MSG"]
pattern_DOMRF_MSG_code = config["pattern_DOMRF_MSG_code"]

pattern_DOMRF_any = config["pattern_DOMRF_any"]
pattern_DOMRF_any_code = config["pattern_DOMRF_any_code"]

pattern_DOMRF_TXT = config["pattern_DOMRF_TXT"]
pattern_DOMRF_TXT_code = config["pattern_DOMRF_TXT_code"]

# паттерны для папки DOMRFIA
pattern_DOMRFIA_MSG = config["pattern_DOMRFIA_MSG"]
pattern_DOMRFIA_MSG_code = config["pattern_DOMRFIA_MSG_code"]

pattern_DOMRFIA_any = config["pattern_DOMRFIA_any"]
pattern_DOMRFIA_any_code = config["pattern_DOMRFIA_any_code"]

# inactive
# def touch_test_files_MSG(search_str: str):
#     with open(file_name, "w") as f:
#         pass
#     return print(f"Создан файл {file_name}")


# for point 1.3
def touch_test_files() -> None:
    from datetime import datetime

    name_prefixes_xls = ["REP_", "0123_", "SPR_"]
    name_prefixes_pdf = ["0123_"]
    name_prefixes_zip = ["SPR_"]
    name_prefixes_txt = ["S01MD103_"]
    file_name_dir = "./0_DECODE/"

    # создаем .MSG файлы
    # dir DOMRF
    for postfix in pattern_DOMRF_MSG_code:
        file_name = (
            file_name_dir
            + f"{datetime.now().date()}"
            + "_"
            + postfix
            + pattern_DOMRF_MSG[0]
        )
        create_file(file_name)

    # dir DOMRFIA
    for postfix in pattern_DOMRFIA_MSG_code:
        file_name = (
            file_name_dir
            + f"{datetime.now().date()}"
            + "_"
            + postfix
            + pattern_DOMRFIA_MSG[0]
        )
        create_file(file_name)

    # создаем .xls файлы
    for prefix in name_prefixes_xls:
        # dir DOMRF
        for code in pattern_DOMRF_any_code:
            file_name = (
                file_name_dir
                + prefix
                + code
                + "_"
                + pattern_DOMRF_any[0]
            )
            create_file(file_name)

        # dir DOMRFIA
        for code in pattern_DOMRFIA_any_code:
            file_name = (
                file_name_dir
                + prefix
                + code
                + "_"
                + pattern_DOMRF_any[0]
            )
            create_file(file_name)

    # создаем .pdf файлы
    for prefix in name_prefixes_pdf:
        # dir DOMRF
        for code in pattern_DOMRF_any_code:
            file_name = (
                file_name_dir
                + prefix
                + code
                + "_"
                + pattern_DOMRF_any[1]
            )
            create_file(file_name)

        # dir DOMRFIA
        for code in pattern_DOMRFIA_any_code:
            file_name = (
                file_name_dir
                + prefix
                + code
                + "_"
                + pattern_DOMRF_any[1]
            )
            create_file(file_name)

    # создаем .zip файлы
    # dir DOMRF
    for code in pattern_DOMRF_any_code:
        file_name = (
            file_name_dir
            + name_prefixes_zip[0]
            + code
            + "_"
            + pattern_DOMRF_any[2]
        )
        create_file(file_name)

    # dir DOMRFIA
    for code in pattern_DOMRFIA_any_code:
        file_name = (
            file_name_dir
            + name_prefixes_zip[0]
            + code
            + "_"
            + pattern_DOMRF_any[2]
        )
        create_file(file_name)

    # создаем .txt файлы
    for code in pattern_DOMRF_TXT_code:
        file_name = (
            file_name_dir
            + name_prefixes_txt[0]
            + code
            + "_"
            + pattern_DOMRF_TXT[0]
        )
        create_file(file_name)

    return


def create_file(file_name: str) -> None:
    with open(file_name, "w") as f:
        pass
    print(f"создан файл {file_name}")
    return


# point 1.3 ловим файлы и раскидываем по папкам DOMRF и DOMRFIA
def sort_files_DOMRF_DOMRFIA(source_dir: str = "./0_DECODE/") -> None:
    name_prefixes_xls = ["REP_", "0123_", "SPR_"]
    name_prefixes_pdf = ["0123_"]
    name_prefixes_zip = ["SPR_"]
    name_prefixes_txt = ["S01MD103_"]
    destination_DOMRF = "./DOMRF/secret"
    destination_DOMRFIA = "./DOMRFIA/secret"

    # перебираем все файлы директории
    for filename in os.listdir(source_dir):
        file_extension = filename[-4:]
        print(f"{file_extension}")

        # ловим .txt файлы
        if file_extension == pattern_DOMRF_TXT[0]:
            # move to dir DOMRF
            for code in pattern_DOMRF_TXT_code:
                code = "_" + code + "_"
                if code in filename:
                    if move_file_to_dir(filename, source_dir, destination_DOMRF):
                        continue

        # ловим .MSG файлы
        elif file_extension == pattern_DOMRF_MSG[0]:
            # search code for dir DOMRF
            code = filename[-9:-4]
            print(f"{code=}")
            if code in pattern_DOMRF_MSG_code:
                if move_file_to_dir(filename, source_dir, destination_DOMRF):
                    continue
            elif code in pattern_DOMRFIA_MSG_code:
                if move_file_to_dir(filename, source_dir, destination_DOMRFIA):
                    continue
            else:
                print(f"Файл {filename} не найден в паттернах для перемещения!")

        # ловим .xls файлы
        elif file_extension == pattern_DOMRF_any[0]:
            # move to dir DOMRF
            for code in pattern_DOMRF_any_code:
                code = "_" + code + "_"
                if code in filename:
                    if move_file_to_dir(filename, source_dir, destination_DOMRF):
                        continue

            # move to dir DOMRFIA
            for code in pattern_DOMRFIA_any_code:
                code = "_" + code + "_"
                if code in filename:
                    if move_file_to_dir(filename, source_dir, destination_DOMRFIA):
                        continue

        # ловим .pdf файлы
        elif file_extension == pattern_DOMRF_any[1]:
            # move to dir DOMRF
            for code in pattern_DOMRF_any_code:
                code = "_" + code + "_"
                if code in filename:
                    if move_file_to_dir(filename, source_dir, destination_DOMRF):
                        continue

            # move to dir DOMRFIA
            for code in pattern_DOMRFIA_any_code:
                code = "_" + code + "_"
                if code in filename:
                    if move_file_to_dir(filename, source_dir, destination_DOMRFIA):
                        continue

        # ловим .zip файлы
        elif file_extension == pattern_DOMRF_any[2]:
            # move to dir DOMRF
            for code in pattern_DOMRF_any_code:
                code = "_" + code + "_"
                if code in filename:
                    if move_file_to_dir(filename, source_dir, destination_DOMRF):
                        continue

            # move to dir DOMRFIA
            for code in pattern_DOMRFIA_any_code:
                code = "_" + code + "_"
                if code in filename:
                    if move_file_to_dir(filename, source_dir, destination_DOMRFIA):
                        continue

        else:
            print(f"Файл {filename} не вписывается в паттерны, оставляем")


def move_file_to_dir(
filename: Optional[str] = None,
source_dir: Optional[str] = None,
dest_dir: Optional[str] = None,
) -> bool:
    # Проверяем наличие целевой директории. Если нет - сообщаем разработчику и пользователю
    # (в тест версии пишем в терминал)
    if not os.path.exists(dest_dir):
        print(f"Директории {dest_dir} не существует!")
        return False

    if not source_dir or not dest_dir or not filename:
        print("# Функцию не переданы директории или файл")
        return False

    source_path = os.path.join(source_dir, filename)
    destination_path = os.path.join(dest_dir, filename)

    try:
        # Перемещаем файл из исходного каталога в целевую директорию
        shutil.move(source_path, destination_path)
        print(f"Файл {filename} успешно перемещён.")
        return True
    except Exception as e:
        print(f"Ошибка при перемещении файла: {e}")
        return False


if __name__ == "__main__":
    # создание тестовых файлов
    # touch_test_files()

    # inactive
    # get_set_patterns(pattern_DOMRF_MSG, pattern_DOMRF_MSG_code)
    # move_file_with_pattern(SOURCE_DIR, DESTINATION_DIR, "0000")

    # сортировка файлов по папкам
    sort_files_DOMRF_DOMRFIA()
