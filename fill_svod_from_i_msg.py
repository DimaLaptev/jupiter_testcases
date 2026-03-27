#!/usr/bin/env python3
"""Заполнение листа «СВОД_операций» из файлов I*.MSG."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from codifier_table import read_codifier_rows
from depo_directory import read_depo_directory_rows
from gpb_i_msg import parse_i_msg_file, passes_execution_filter
from openpyxl import Workbook, load_workbook
from svod_excel import (
    SVOD_HEADERS,
    build_svod_row,
    create_workbook_with_svod_only,
    ensure_svod_sheet,
    write_svod_rows,
)

from dks_excel import SCHEETA_DEPO_HEADERS


def _depo_demo_row() -> list:
    return [
        "ДОМ",
        "Банк ГПБ АО",
        33563,
        "—",
        "БДРФ",
        "—",
        "залоговый",
        248,
        "",
        "ПАО ДОМ.РФ",
    ]


def append_reference_sheets_if_missing(path: Path) -> None:
    """Добавляет «Счета депо» и «Коды» с тестовыми строками, если листов нет или только заголовки (например после fill_dks)."""
    wb = load_workbook(path)
    changed = False
    if "Счета депо" not in wb.sheetnames:
        ws_dep = wb.create_sheet("Счета депо")
        for col, title in enumerate(SCHEETA_DEPO_HEADERS, start=1):
            ws_dep.cell(row=1, column=col, value=title)
        ws_dep.append(_depo_demo_row())
        changed = True
    else:
        ws_dep = wb["Счета депо"]
        has_data = ws_dep.max_row > 1 and ws_dep.cell(row=2, column=3).value not in (None, "")
        if not has_data:
            ws_dep.append(_depo_demo_row())
            changed = True
    if "Коды" not in wb.sheetnames:
        ws_cod = wb.create_sheet("Коды")
        code_headers = [
            "Код операции",
            "Код исполнения",
            "Тип операции",
            "Содержание ГПБ",
            "Содержание РСД",
            "Содержание РЕГИОН",
            "Содержание ВТБСД",
            "Тип поручения",
            "Комментарий",
        ]
        for col, title in enumerate(code_headers, start=1):
            ws_cod.cell(row=1, column=col, value=title)
        ws_cod.append(
            [
                12005,
                "",
                "Прекращение залога - зачисление",
                "Зачисление ЦБ - прекращение залога",
                "",
                "",
                "",
                "VF",
                "",
            ]
        )
        ws_cod.append(
            [
                12005,
                "",
                "Прекращение залога - списание",
                "Списание ЦБ - прекращение залога",
                "",
                "",
                "",
                "VP",
                "",
            ]
        )
        changed = True
    else:
        ws_cod = wb["Коды"]
        has_codes = ws_cod.max_row > 1 and ws_cod.cell(row=2, column=1).value not in (None, "")
        if not has_codes:
            ws_cod.append(
                [
                    12005,
                    "",
                    "Прекращение залога - зачисление",
                    "Зачисление ЦБ - прекращение залога",
                    "",
                    "",
                    "",
                    "VF",
                    "",
                ]
            )
            ws_cod.append(
                [
                    12005,
                    "",
                    "Прекращение залога - списание",
                    "Списание ЦБ - прекращение залога",
                    "",
                    "",
                    "",
                    "VP",
                    "",
                ]
            )
            changed = True
    if changed:
        wb.save(path)
    wb.close()


def seed_minimal_reference_workbook(path: Path) -> None:
    """Листы «Счета депо» и «Коды» с заголовками и минимальными строками для теста (ClientID 248 → 33563)."""
    wb = Workbook()
    wb.remove(wb.active)

    ws_dep = wb.create_sheet("Счета депо")
    for col, title in enumerate(SCHEETA_DEPO_HEADERS, start=1):
        ws_dep.cell(row=1, column=col, value=title)
    # строка как в memory/3_GBP_cods_1 (залоговый 33563, код ДОМ 248)
    ws_dep.append(
        [
            "ДОМ",
            "Банк ГПБ АО",
            33563,
            "—",
            "БДРФ",
            "—",
            "залоговый",
            248,
            "",
            "ПАО ДОМ.РФ",
        ]
    )

    ws_cod = wb.create_sheet("Коды")
    code_headers = [
        "Код операции",
        "Код исполнения",
        "Тип операции",
        "Содержание ГПБ",
        "Содержание РСД",
        "Содержание РЕГИОН",
        "Содержание ВТБСД",
        "Тип поручения",
        "Комментарий",
    ]
    for col, title in enumerate(code_headers, start=1):
        ws_cod.cell(row=1, column=col, value=title)
    ws_cod.append(
        [
            12005,
            "",
            "Прекращение залога - зачисление",
            "Зачисление ЦБ - прекращение залога",
            "",
            "",
            "",
            "VF",
            "",
        ]
    )
    ws_cod.append(
        [
            12005,
            "",
            "Прекращение залога - списание",
            "Списание ЦБ - прекращение залога",
            "",
            "",
            "",
            "VP",
            "",
        ]
    )

    ws_svod = wb.create_sheet("СВОД_операций")
    for col, title in enumerate(SVOD_HEADERS, start=1):
        ws_svod.cell(row=1, column=col, value=title)

    wb.save(path)


def ensure_workbook_structure(path: Path, create: bool, seed: bool) -> None:
    if not path.exists():
        if not create:
            print(
                f"Файл не найден: {path}. Укажите --create-workbook.",
                file=sys.stderr,
            )
            sys.exit(1)
        if seed:
            print(f"Создаю книгу с тестовыми справочниками: {path}")
            seed_minimal_reference_workbook(path)
        else:
            create_workbook_with_svod_only(path)
        return

    wb = load_workbook(path)
    if "СВОД_операций" not in wb.sheetnames:
        ensure_svod_sheet(wb)
        wb.save(path)
    wb.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Парсинг I*.MSG и запись листа «СВОД_операций».",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=_ROOT / "2026_01" / "GPB" / "I",
        help="Каталог с I*.MSG",
    )
    parser.add_argument(
        "--workbook",
        type=Path,
        default=_ROOT / "2026_01" / "2026_01_Ord_Quantity.xlsx",
        help="Путь к xlsx",
    )
    parser.add_argument(
        "--create-workbook",
        action="store_true",
        help="Создать файл, если отсутствует",
    )
    parser.add_argument(
        "--seed-demo-data",
        action="store_true",
        help="При создании книги добавить тестовые листы «Счета депо» и «Коды»",
    )
    parser.add_argument(
        "--ensure-reference-sheets",
        action="store_true",
        help="Если нет листов «Счета депо» или «Коды», создать их с демо-данными",
    )
    args = parser.parse_args()

    wb_path = args.workbook.resolve()
    ensure_workbook_structure(wb_path, args.create_workbook, args.seed_demo_data)
    if args.ensure_reference_sheets:
        append_reference_sheets_if_missing(wb_path)

    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        print(f"Каталог не найден: {input_dir}", file=sys.stderr)
        return 1

    seen = set()
    files: list[Path] = []
    for pat in ("I*.MSG", "i*.MSG"):
        for f in sorted(input_dir.glob(pat)):
            rp = f.resolve()
            if rp not in seen:
                seen.add(rp)
                files.append(f)
    if not files:
        print(f"Нет файлов I*.MSG в {input_dir}")
        return 0

    depo_rows = read_depo_directory_rows(str(wb_path))
    cod_rows = read_codifier_rows(str(wb_path))
    if not depo_rows:
        print(
            "Предупреждение: лист «Счета депо» пуст или отсутствует — колонки B, E могут быть пустыми.",
            file=sys.stderr,
        )
    if not cod_rows:
        print(
            "Предупреждение: лист «Коды» пуст или отсутствует — колонки D, N могут быть пустыми.",
            file=sys.stderr,
        )

    rows_out: list[list] = []
    for fp in files:
        parsed = parse_i_msg_file(fp)
        rt = (parsed.header.get("ReportType") or "").strip()
        if rt and rt.upper() != "INSTRUCTIONS":
            print(f"Пропуск (не INSTRUCTIONS): {fp.name}", file=sys.stderr)
            continue
        client_id = (parsed.header.get("ClientID") or "").strip()

        for data in parsed.rows:
            if not passes_execution_filter(data):
                continue
            if len(data.parts) < 18:
                continue
            rows_out.append(
                build_svod_row(parsed, data, depo_rows, cod_rows, client_id),
            )

    write_svod_rows(wb_path, rows_out)
    print(f"Записано строк: {len(rows_out)} в {wb_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
