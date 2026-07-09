#!/usr/bin/env python3
"""Заполнение листа Dks из отчётов D*.MSG и справочника «Счета депо»."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from depo_directory import lookup_account_by_client_id, read_depo_directory_rows
from dks_excel import create_workbook_template, row_values, write_dks_rows
from gpb_d_msg import parse_d_msg_file
from period_cli import add_period_dir_argument, apply_period_workbook
from period_paths import classify_and_resolve


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Парсинг D*.MSG из каталога GPB/D и запись листа Dks.",
    )
    add_period_dir_argument(parser)
    parser.add_argument(
        "--workbook",
        type=Path,
        default=_ROOT / "2026_01" / "2026_01_Ord_Quantity.xlsx",
        help="Путь к Ord_Quantity.xlsx",
    )
    parser.add_argument(
        "--create-workbook",
        action="store_true",
        help="Создать книгу с листами Dks и «Счета депо», если файла нет",
    )
    parser.add_argument(
        "--include-empty-doc-name",
        action="store_true",
        help="Не отфильтровывать строки с пустым «Наименование документа» (по умолчанию такие строки пропускаются)",
    )
    args = parser.parse_args()
    apply_period_workbook(args, project_root=_ROOT)

    if args.period_dir:
        input_dir, pp = classify_and_resolve(args.period_dir, _ROOT, leaf="gpb_d")
        if pp is None:
            input_dir = Path(args.period_dir).resolve()
    else:
        input_dir = (_ROOT / "2026_01" / "GPB" / "D").resolve()

    wb_path = args.workbook.resolve()
    if not wb_path.exists():
        if not args.create_workbook:
            print(
                f"Файл не найден: {wb_path}. Запустите с --create-workbook или создайте книгу вручную.",
                file=sys.stderr,
            )
            return 1
        print(f"Создаю шаблон: {wb_path}")
        create_workbook_template(wb_path)

    if not input_dir.is_dir():
        print(f"Каталог не найден: {input_dir}", file=sys.stderr)
        return 1

    seen = set()
    files = []
    for pat in ("D*.MSG", "d*.MSG"):
        for f in sorted(input_dir.glob(pat)):
            rp = f.resolve()
            if rp not in seen:
                seen.add(rp)
                files.append(f)
    if not files:
        print(f"Нет файлов D*.MSG в {input_dir}")
        return 0

    depo_rows = read_depo_directory_rows(str(wb_path))
    if not depo_rows:
        print(
            "Предупреждение: справочник «Счета депо» пуст или лист отсутствует — колонка «Счет депо» будет пустой.",
            file=sys.stderr,
        )

    rows_out: list[list] = []
    for fp in files:
        try:
            parsed = parse_d_msg_file(fp)
        except Exception as e:
            print(f"Ошибка чтения {fp}: {e}", file=sys.stderr)
            raise
        rt = (parsed.header.get("ReportType") or "").strip()
        if rt and rt != "DOC_INSTRUCT":
            print(f"Пропуск (не DOC_INSTRUCT): {fp.name}", file=sys.stderr)
            continue

        client_id = (parsed.header.get("ClientID") or "").strip()
        depo_account = lookup_account_by_client_id(depo_rows, client_id)

        for data in parsed.rows:
            if not args.include_empty_doc_name and not data.doc_type.strip():
                continue
            rows_out.append(row_values(parsed, data, depo_account))

    write_dks_rows(wb_path, rows_out)
    print(f"Записано строк: {len(rows_out)} в {wb_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
