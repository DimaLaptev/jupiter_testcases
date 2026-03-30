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
from gpb_d_msg import parse_d_msg_file
from gpb_i_msg import parse_i_msg_file, passes_execution_filter
from openpyxl import Workbook, load_workbook
from svod_excel import (
    SVOD_HEADERS,
    build_svod_row,
    build_svod_row_from_d,
    create_workbook_with_svod_only,
    ensure_svod_sheet,
    write_svod_rows,
)

from dks_excel import SCHEETA_DEPO_HEADERS


# Строки листа «Коды» для СВОД из D*.MSG (тип поручения DF/DP, пустой код операции)
_CODE_DOC_DF = [
    "",
    "",
    "Документы - зачисление",
    "Документы - зачисление",
    "",
    "",
    "",
    "DF",
    "только для 10934",
]
_CODE_DOC_DP = [
    "",
    "",
    "Документы - списание",
    "Документы - списание",
    "",
    "",
    "",
    "DP",
    "",
]


def _codifier_has_document_df_dp_rows(workbook_path: str) -> bool:
    for r in read_codifier_rows(workbook_path):
        if r.op_code.strip():
            continue
        if r.instruction_type.strip().upper() not in ("DF", "DP"):
            continue
        if "документ" in r.op_type.lower():
            return True
    return False


def append_document_codifier_rows_if_missing(path: Path) -> None:
    """Добавляет строки «Документы - …» / DF|DP, если в «Коды» их ещё нет."""
    if _codifier_has_document_df_dp_rows(str(path)):
        return
    wb = load_workbook(path)
    if "Коды" not in wb.sheetnames:
        wb.close()
        return
    ws = wb["Коды"]
    ws.append(_CODE_DOC_DF)
    ws.append(_CODE_DOC_DP)
    wb.save(path)
    wb.close()


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
        ws_cod.append(_CODE_DOC_DF)
        ws_cod.append(_CODE_DOC_DP)
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
            ws_cod.append(_CODE_DOC_DF)
            ws_cod.append(_CODE_DOC_DP)
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
    ws_cod.append(_CODE_DOC_DF)
    ws_cod.append(_CODE_DOC_DP)

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
        description="Парсинг I*.MSG и D*.MSG и запись листа «СВОД_операций» (сначала I, затем D).",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=_ROOT / "2026_01" / "GPB" / "I",
        help="Каталог с I*.MSG",
    )
    parser.add_argument(
        "--input-dir-d",
        type=Path,
        default=_ROOT / "2026_01" / "GPB" / "D",
        help="Каталог с D*.MSG для строк СВОД (DOC_INSTRUCT)",
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
    parser.add_argument(
        "--no-d-msg",
        action="store_true",
        help="Не добавлять строки из D*.MSG (только отчёт I)",
    )
    parser.add_argument(
        "--svod-d-only",
        action="store_true",
        help="Только строки из D*.MSG (не обрабатывать I*.MSG)",
    )
    parser.add_argument(
        "--include-empty-doc-name",
        action="store_true",
        help="Для D*.MSG не отбрасывать строки с пустым наименованием документа",
    )
    args = parser.parse_args()

    wb_path = args.workbook.resolve()
    ensure_workbook_structure(wb_path, args.create_workbook, args.seed_demo_data)
    if args.ensure_reference_sheets:
        append_reference_sheets_if_missing(wb_path)
    append_document_codifier_rows_if_missing(wb_path)

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

    if not args.svod_d_only:
        input_dir = args.input_dir.resolve()
        files_i: list[Path] = []
        if not input_dir.is_dir():
            print(f"Каталог I не найден (пропуск I*.MSG): {input_dir}", file=sys.stderr)
        else:
            seen_i = set()
            for pat in ("I*.MSG", "i*.MSG"):
                for f in sorted(input_dir.glob(pat)):
                    rp = f.resolve()
                    if rp not in seen_i:
                        seen_i.add(rp)
                        files_i.append(f)
            if not files_i:
                print(f"Нет файлов I*.MSG в {input_dir}")
        for fp in files_i:
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

    if not args.no_d_msg:
        input_d = args.input_dir_d.resolve()
        if not input_d.is_dir():
            print(f"Каталог D не найден: {input_d}", file=sys.stderr)
            if args.svod_d_only:
                return 1
        else:
            seen_d = set()
            files_d: list[Path] = []
            for pat in ("D*.MSG", "d*.MSG"):
                for f in sorted(input_d.glob(pat)):
                    rp = f.resolve()
                    if rp not in seen_d:
                        seen_d.add(rp)
                        files_d.append(f)
            if not files_d:
                print(f"Нет файлов D*.MSG в {input_d}")
            for fp in files_d:
                try:
                    parsed = parse_d_msg_file(fp)
                except OSError as e:
                    print(f"Ошибка чтения {fp}: {e}", file=sys.stderr)
                    continue
                rt = (parsed.header.get("ReportType") or "").strip()
                if rt and rt != "DOC_INSTRUCT":
                    print(f"Пропуск D (не DOC_INSTRUCT): {fp.name}", file=sys.stderr)
                    continue
                client_id = (parsed.header.get("ClientID") or "").strip()
                for data in parsed.rows:
                    if not args.include_empty_doc_name and not data.doc_type.strip():
                        continue
                    rows_out.append(
                        build_svod_row_from_d(
                            parsed,
                            data,
                            depo_rows,
                            cod_rows,
                            client_id,
                        ),
                    )

    write_svod_rows(wb_path, rows_out)
    print(f"Записано строк: {len(rows_out)} в {wb_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
