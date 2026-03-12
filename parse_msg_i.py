"""
Парсинг .MSG файлов в директории tz/I.
Формат: key:value в заголовке, data-строки с запятыми (,) в качестве разделителя.
Результат: словарь на print (ключи — key:value и номера строк, значения — список элементов).
"""

import sys
from pathlib import Path

# UTF-8 для консоли Windows (исключает искажение кириллицы)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from parse_doc_instruct_excel import parse_msg_tz_i, print_parsed_result

DEFAULT_SOURCE_DIR = Path(__file__).parent / "tz" / "I"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    source_dir = Path(args[0]) if args else DEFAULT_SOURCE_DIR
    use_json = "--json" in sys.argv

    if not source_dir.is_dir():
        print(f"Директория не найдена: {source_dir}")
        sys.exit(1)

    msg_files = sorted(f for f in source_dir.iterdir() if f.is_file() and f.suffix.upper() == ".MSG")
    if not msg_files:
        print(f"В {source_dir} нет файлов .MSG")
        sys.exit(0)

    for i, path in enumerate(msg_files):
        if i > 0:
            print("\n" + "=" * 60 + "\n")
        print(f"--- {path.name} ---")
        try:
            parsed = parse_msg_tz_i(path)
            print_parsed_result(parsed, use_json=use_json)
        except Exception as e:
            print(f"Ошибка: {e}")


if __name__ == "__main__":
    main()
