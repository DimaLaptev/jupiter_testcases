"""
Сборка таблицы (лист Dks / Dds) из распарсенных DOC_INSTRUCT файлов.
Формат выгрузки — Ord Quantity/Dks.

По умолчанию проходит по директории месяц/D, парсит файлы .xlsx и .MSG
и собирает из них итоговый Excel.
"""

import sys
from pathlib import Path
from typing import List, Union

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

from parse_doc_instruct_excel import (
    parse_doc_instruct_excel,
    parse_doc_instruct_msg,
    transform_parsed_to_report_rows,
)

# Директория по умолчанию для сбора исходных файлов
DEFAULT_SOURCE_DIR = Path(__file__).parent / "tz" / "D"


COLUMNS = [
    "Дата операции",
    "Счет депо",
    "НГРИ",
    "Наименование документа",
    "Номер документа",
    "Дата документа",
    "Комментарий",
    "Для удаления дубликатов",
    "Тип поручения",
    "Источник",
]

EXT_XLSX = (".xlsx", ".xls")
EXT_MSG = (".msg", ".MSG")


def collect_files_from_directory(source_dir: Union[str, Path]) -> List[Path]:
    """Собирает пути к файлам .xlsx и .MSG в указанной директории."""
    path = Path(source_dir)
    if not path.is_dir():
        return []
    files = []
    for f in sorted(path.iterdir()):
        if f.is_file():
            suf = f.suffix
            if suf in EXT_XLSX or suf in EXT_MSG:
                files.append(f)
    return files


def parse_doc_instruct_file(file_path: Path) -> dict:
    """Парсит файл .xlsx или .MSG, возвращает результат в формате DOC_INSTRUCT."""
    suf = file_path.suffix.lower()
    if suf in (".xlsx", ".xls"):
        return parse_doc_instruct_excel(file_path)
    if suf == ".msg":
        return parse_doc_instruct_msg(file_path)
    return {}


def build_report_excel(
    input_paths: List[Union[str, Path]],
    output_path: Union[str, Path] = "Dks_report.xlsx",
    sheet_name: str = "Dks",
) -> None:
    """
    Читает файлы DOC_INSTRUCT (.xlsx, .MSG), трансформирует в строки отчёта,
    выгружает в Excel.
    """
    all_rows = []
    for path in input_paths:
        p = Path(path)
        if not p.exists():
            print(f"Пропуск (не найден): {path}")
            continue
        try:
            parsed = parse_doc_instruct_file(p)
        except Exception as e:
            print(f"Ошибка парсинга {p}: {e}")
            continue
        if not parsed:
            continue
        rows = transform_parsed_to_report_rows(parsed)
        all_rows.extend(rows)

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    header_fill = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    ws.cell(row=1, column=4, value="Удалить закладные с пустыми строками в наименовании (= закладные, к которым не прилагаются документы)")
    ws.cell(row=1, column=8, value="Удалить дубликаты")

    for col, name in enumerate(COLUMNS, 1):
        cell = ws.cell(row=2, column=col, value=name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", wrap_text=True)

    for row_idx, row_dict in enumerate(all_rows, 3):
        for col, key in enumerate(COLUMNS, 1):
            ws.cell(row=row_idx, column=col, value=row_dict.get(key, ""))

    for col in range(1, len(COLUMNS) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 18

    wb.save(output_path)
    print(f"Сохранено: {output_path}, строк: {len(all_rows)}")


if __name__ == "__main__":
    args = []
    output = "Dks_report.xlsx"
    source_dir = None

    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "-o" and i + 1 < len(sys.argv):
            output = sys.argv[i + 1]
            i += 2
            continue
        if sys.argv[i] == "-d" and i + 1 < len(sys.argv):
            source_dir = sys.argv[i + 1]
            i += 2
            continue
        if not sys.argv[i].startswith("-"):
            args.append(sys.argv[i])
        i += 1

    if not args and source_dir is None:
        source_dir = str(DEFAULT_SOURCE_DIR)
        files = collect_files_from_directory(source_dir)
        if not files:
            print(f"В директории {source_dir} нет файлов .xlsx и .MSG.")
            print("Использование: python build_doc_instruct_report.py [-d dir] [-o output.xlsx]")
            print("              или: python build_doc_instruct_report.py <file1> [file2 ...] [-o output.xlsx]")
            sys.exit(1)
        print(f"Найдено файлов в {source_dir}: {len(files)}")
        args = files
    elif source_dir:
        files = collect_files_from_directory(source_dir)
        args = files if files else args

    if not args:
        print("Нет файлов для обработки.")
        sys.exit(1)

    build_report_excel(args, output_path=output)
