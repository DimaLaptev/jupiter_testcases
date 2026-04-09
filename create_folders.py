import os

from get_month_name_dir import get_today_year_month
from config_ews import REPORS_DEPO_DIRECTORY


def create_folder_structure():
    current_month = get_today_year_month()
    root_folder = os.path.join(
        REPORS_DEPO_DIRECTORY, current_month
    )  # Теперь папка создается внутри директории из config_ews.py
    print("\n" + "=" * 70)
    print(f"создаем структуру папок для месяца: {current_month}")
    print("\n" + "=" * 70)

    # Определяем структуру папок согласно схеме
    folder_structure = {
        "GPB": ["D", "I", "R", "REP", "SPR", "zDetalization"],
        "REGION": ["REP", "SPR", "EDO", "zDetalization"],
        "RSD": ["D", "I", "R", "REP", "SPR", "EDO", "zDetalization"],
        "VTBSD": ["REP", "SPR", "EDO", "zDetalization"],
    }

    if os.path.exists(root_folder):
        print(f'Корневая папка "{root_folder}" уже существует')
    else:
        os.makedirs(root_folder)
        print(f'Создана корневая папка "{root_folder}"')

    # Создаем структуру подпапок
    created_count = 0
    skipped_count = 0
    for main_folder, subfolders in folder_structure.items():
        main_path = os.path.join(root_folder, main_folder)
        # Create main folder
        if not os.path.exists(main_path):
            os.makedirs(main_path)
            print(f"\n Создана папка: {main_folder}")
            created_count += 1
        else:
            print(f"\n Папка существует: {main_folder}")
            skipped_count += 1

        # Подпапки
        for subfolder in subfolders:
            subfolder_path = os.path.join(main_path, subfolder)
            if not os.path.exists(subfolder_path):
                os.makedirs(subfolder_path)
                print(f"  -{subfolder}/")
                created_count += 1
            else:
                print(f"  -{subfolder}/ (существует)")
                skipped_count += 1
    # Итоговая статистика
    print("\n" + "=" * 70)
    print("ИТОГО:")
    print(f"Новых папок создано: {created_count}")
    print(f"Пропущено (уже существует): {skipped_count}")
    print(f"Путь к структуре: {os.path.abspath(root_folder)}")
    print("\n" + "=" * 70)
    return root_folder


def show_folder_tree(root_folder):
    """Показ дерева созданных папок."""
    print("\n" + "=" * 70)
    print("Структура папок")
    if not os.path.exists(root_folder):
        print(f"Папка {root_folder} не найдена")
        return
    print(f"{root_folder}/")

    # Список папок первого уровня
    main_folders = sorted(
        [f for f in os.listdir(root_folder) if os.path.isdir(os.path.join(root_folder, f))]
    )
    for i, main_folder in enumerate(main_folders):
        is_last_main = i == len(main_folders) - 1
        main_prefix = "└──" if is_last_main else "├──"
        print(f"{main_prefix} {main_folder}/")

        # Получаем список подпапок
        main_path = os.path.join(root_folder, main_folder)
        subfolders = sorted(
            [f for f in os.listdir(main_path) if os.path.isdir(os.path.join(main_path, f))]
        )
        for j, subfolder in enumerate(subfolders):
            is_last_sub = j == len(subfolders) - 1
            sub_prefix = "  └──" if is_last_sub else "  ├──"
            if not is_last_main:
                sub_prefix = "│ └──" if is_last_sub else "│ ├──"
            print(f"{sub_prefix} {subfolder}/")


def create_custom_month_structure(year, month):
    """Создание структуры папок вручную для определенного месяца."""
    root_folder = f"{year}_{month:02d}"
    full_root_folder = os.path.join(
        REPORS_DEPO_DIRECTORY, root_folder
    )  # Путь формируется с учетом базовой директории
    print("\n" + "=" * 70)
    print(f"Создание структуры папок для: {full_root_folder}")
    print("\n" + "=" * 70)
    folder_structure = {
        "GPB": ["D", "I", "R", "REP", "SPR", "zDetalization"],
        "REGION": ["REP", "SPR", "EDO", "zDetalization"],
        "RSD": ["D", "I", "R", "REP", "SPR", "EDO", "zDetalization"],
        "VTBSD": ["REP", "SPR", "EDO", "zDetalization"],
    }
    # Создаем корневую папку
    if not os.path.exists(full_root_folder):
        os.makedirs(full_root_folder)
        print(f"Создана корневая папка: {full_root_folder}\n")
    else:
        print(f"Папка: {full_root_folder} уже существует\n")

    # Подпапки
    for main_folder, subfolders in folder_structure.items():
        main_path = os.path.join(full_root_folder, main_folder)
        os.makedirs(main_path, exist_ok=True)
        for subfolder in subfolders:
            subfolder_path = os.path.join(main_path, subfolder)
            os.makedirs(subfolder_path, exist_ok=True)
    print(f"Структура создана: {os.path.abspath(full_root_folder)}\n")
    return full_root_folder


if __name__ == "__main__":
    # Структура для текущего месяца
    root_folder = create_folder_structure()
    # Показываем дерево папок
    show_folder_tree(root_folder)
    print("Готово!\n")
    # Примеры использования
