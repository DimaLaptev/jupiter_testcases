#!/usr/bin/env python3
"""Заполнение листа REPs из файлов REP_*.xls / REP_*.xlsx и справочника «Счета депо».

Бинарные .xls требуют пакета xlrd: pip install "xlrd>=2.0.1,<3" (см. requirements.txt).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from depo_directory import lookup_depo_row_by_account_number, read_depo_directory_rows
from gpb_rep_xls import parse_rep_xls
from period_cli import add_period_dir_argument, apply_period_workbook
from period_paths import classify_and_resolve
from reps_excel import append_reps_rows, create_workbook_with_reps, reps_row_values, write_reps_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Парсинг REP_*.xls из каталога и запись листа REPs.",
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
        help="Создать книгу с листами REPs и «Счета депо», если файла нет",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Дописать строки под существующие данные вместо полной перезаписи листа",
    )
    args = parser.parse_args()
    apply_period_workbook(args, project_root=_ROOT)

    if args.period_dir:
        input_dir, pp = classify_and_resolve(args.period_dir, _ROOT, leaf="gpb_rep")
        if pp is None:
            input_dir = Path(args.period_dir).resolve()
    else:
        input_dir = (_ROOT / "2026_01" / "GPB" / "REP").resolve()

    wb_path = args.workbook.resolve()
    if not wb_path.exists():
        if not args.create_workbook:
            print(
                f"Файл не найден: {wb_path}. Запустите с --create-workbook или создайте книгу вручную.",
                file=sys.stderr,
            )
            return 1
        print(f"Создаю шаблон: {wb_path}")
        create_workbook_with_reps(wb_path)

    if not input_dir.is_dir():
        print(f"Каталог не найден: {input_dir}", file=sys.stderr)
        return 1

    seen = set()
    files: list[Path] = []
    for pat in ("REP_*.xls", "REP_*.xlsx", "rep_*.xls", "rep_*.xlsx"):
        for f in sorted(input_dir.glob(pat)):
            rp = f.resolve()
            if rp not in seen:
                seen.add(rp)
                files.append(f)
    if not files:
        print(f"Нет файлов REP_* в {input_dir}")
        return 0

    depo_rows = read_depo_directory_rows(str(wb_path))
    if not depo_rows:
        print(
            "Предупреждение: справочник «Счета депо» пуст или лист отсутствует — колонка «Tab1_Счета.владелец» будет пустой.",
            file=sys.stderr,
        )

    rows_out: list[list] = []
    skipped_reject = 0
    skipped_empty_sheet = 0
    skipped_no_table = 0

    for fp in files:
        try:
            parsed = parse_rep_xls(fp)
        except Exception as e:
            print(f"Ошибка чтения {fp}: {e}", file=sys.stderr)
            raise

        if parsed.empty_sheet:
            skipped_empty_sheet += 1
            print(f"Пропуск (пустой лист): {fp.name}", file=sys.stderr)
            continue

        if parsed.header_rejected:
            skipped_reject += 1
            print(f"Пропуск (отказ в исполнении в шапке): {fp.name}", file=sys.stderr)
            continue

        if not parsed.mortgage_rows:
            skipped_no_table += 1
            print(f"Предупреждение: нет строк «ЗАКЛАДНЫЕ»: {fp.name}", file=sys.stderr)

        depo = None
        acc = ""
        if parsed.depo_from_filename:
            acc = parsed.depo_from_filename
        elif parsed.depo_fallback:
            acc = parsed.depo_fallback
        if acc:
            depo = lookup_depo_row_by_account_number(depo_rows, acc)
        owner = depo.owner if depo else ""

        for mr in parsed.mortgage_rows:
            rows_out.append(reps_row_values(parsed, mr, owner))

    if args.append:
        append_reps_rows(wb_path, rows_out)
    else:
        write_reps_rows(wb_path, rows_out)

    print(
        f"Записано строк: {len(rows_out)} в {wb_path} "
        f"(пропущено отказов: {skipped_reject}, пустых листов: {skipped_empty_sheet}, без таблицы: {skipped_no_table})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
