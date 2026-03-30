#!/usr/bin/env python3
"""Сверка листа «СВОД_операций» между эталонной книгой и тестовой; лист отчёта в тестовой xlsx."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from svod_excel import SVOD_HEADERS

# Колонка Q — индекс 16 (0-based), служебный ключ; при совпадении ключа не подсвечиваем Q.
_COL_Q_INDEX = 16
_COMPARE_COL_INDICES = list(range(16)) + [17]  # A–P и R (без Q)

_RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
_TITLE_FONT = Font(bold=True)
_SECTION_FONT = Font(bold=True, size=12)


def _norm_header_cell(val: object) -> str:
    if val is None:
        return ""
    return str(val).strip()


def find_header_row(ws: Worksheet, first_header: str) -> int:
    """Первая строка, где ячейка A совпадает с первым заголовком SVOD (например «Дата операции»)."""
    expect = first_header.strip()
    max_r = ws.max_row or 1
    for r in range(1, max_r + 1):
        if _norm_header_cell(ws.cell(row=r, column=1).value) == expect:
            return r
    return 0


def _normalize_for_compare(val: object) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return str(val)
    if isinstance(val, datetime):
        return val.strftime("%d.%m.%Y")
    if isinstance(val, date):
        return val.strftime("%d.%m.%Y")
    if isinstance(val, time):
        return val.strftime("%H:%M:%S")
    s = str(val).strip()
    if s == "":
        return ""
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
        return str(f)
    except ValueError:
        return s


def _row_values(ws: Worksheet, excel_row: int, ncols: int) -> list[object]:
    return [ws.cell(row=excel_row, column=c + 1).value for c in range(ncols)]


def load_svod_table(
    path: Path,
    sheet_name: str,
    label: str,
) -> tuple[
    dict[str, list[tuple[int, list[object]]]],
    int,
    int,
    int,
]:
    """
    Возвращает:
      by_key: ключ Q -> список (номер_строки_Excel, значения_колонок)
      header_row
      skipped_empty_q
      max_data_col (фактически len(SVOD_HEADERS))
    """
    wb = load_workbook(path, data_only=True)
    try:
        if sheet_name not in wb.sheetnames:
            raise SystemExit(f"[{label}] Нет листа «{sheet_name}»: {path}")
        ws = wb[sheet_name]
        header_row = find_header_row(ws, SVOD_HEADERS[0])
        if header_row == 0:
            raise SystemExit(
                f"[{label}] Не найдена строка заголовка (колонка A = «{SVOD_HEADERS[0]}»): {path}",
            )
        for ci, title in enumerate(SVOD_HEADERS):
            got = _norm_header_cell(ws.cell(row=header_row, column=ci + 1).value)
            if got and got != title.strip():
                print(
                    f"[{label}] Предупреждение: колонка {ci + 1} заголовок «{got}» != эталону «{title}» ({path.name})",
                    file=sys.stderr,
                )
        ncols = len(SVOD_HEADERS)
        by_key: dict[str, list[tuple[int, list[object]]]] = defaultdict(list)
        skipped_empty_q = 0
        max_r = ws.max_row or header_row
        for r in range(header_row + 1, max_r + 1):
            vals = _row_values(ws, r, ncols)
            if all(v is None or str(v).strip() == "" for v in vals):
                continue
            key_cell = vals[_COL_Q_INDEX] if len(vals) > _COL_Q_INDEX else None
            key = _normalize_for_compare(key_cell)
            if key == "":
                skipped_empty_q += 1
                continue
            by_key[key].append((r, vals))
        return dict(by_key), header_row, skipped_empty_q, ncols
    finally:
        wb.close()


def _ensure_output_sheet(wb, name: str, overwrite: bool) -> None:
    if name in wb.sheetnames:
        if not overwrite:
            raise SystemExit(
                f"Лист «{name}» уже есть. Укажите --overwrite-output-sheet или другое --output-sheet.",
            )
        wb.remove(wb[name])
    wb.create_sheet(name)


def _write_metadata(ws: Worksheet, row: int, sample: Path, test: Path, stats: dict) -> int:
    ws.cell(row=row, column=1, value="Сверка листа «СВОД_операций»").font = _SECTION_FONT
    row += 1
    ws.cell(row=row, column=1, value=f"Время (UTC): {datetime.now(timezone.utc).isoformat()}")
    row += 1
    ws.cell(row=row, column=1, value=f"Образец (sample): {sample}")
    row += 1
    ws.cell(row=row, column=1, value=f"Тест (test): {test}")
    row += 1
    ws.cell(row=row, column=1, value=f"Строк с пустым Q (образец): {stats['skip_q_sample']}")
    row += 1
    ws.cell(row=row, column=1, value=f"Строк с пустым Q (тест): {stats['skip_q_test']}")
    row += 1
    ws.cell(row=row, column=1, value=f"Только в образце (строк): {stats['only_sample']}")
    row += 1
    ws.cell(row=row, column=1, value=f"Только в тесте (строк): {stats['only_test']}")
    row += 1
    ws.cell(row=row, column=1, value=f"Совпало по ключу Q, но поля отличаются (строк): {stats['mismatch_rows']}")
    row += 1
    return row + 1


def _write_table_header(ws: Worksheet, row: int, headers: list[str], start_col: int = 1) -> int:
    for i, h in enumerate(headers):
        c = ws.cell(row=row, column=start_col + i, value=h)
        c.font = _TITLE_FONT
    return row + 1


def _write_data_row(
    ws: Worksheet,
    row: int,
    values: list[object],
    start_col: int = 1,
    red_indices: set[int] | None = None,
) -> int:
    red_indices = red_indices or set()
    for i, v in enumerate(values):
        cell = ws.cell(row=row, column=start_col + i, value=v)
        if i in red_indices:
            cell.fill = _RED_FILL
    return row + 1


def build_report(
    sample_path: Path,
    test_path: Path,
    sheet_name: str,
    output_sheet: str,
    overwrite: bool,
) -> int:
    sample_by_key, _, skip_q_s, ncols = load_svod_table(sample_path, sheet_name, "образец")
    test_by_key, _, skip_q_t, _ = load_svod_table(test_path, sheet_name, "тест")

    keys_sample = set(sample_by_key.keys())
    keys_test = set(test_by_key.keys())
    only_s = sorted(keys_sample - keys_test)
    only_t = sorted(keys_test - keys_sample)
    common = sorted(keys_sample & keys_test)

    mismatch_keys: list[str] = []
    for k in common:
        s_row = sample_by_key[k][0][1]
        t_row = test_by_key[k][0][1]
        diff = False
        for ci in _COMPARE_COL_INDICES:
            if _normalize_for_compare(s_row[ci]) != _normalize_for_compare(t_row[ci]):
                diff = True
                break
        if diff:
            mismatch_keys.append(k)

    dup_rows: list[tuple[str, str, str]] = []
    for label, bk in (("образец", sample_by_key), ("тест", test_by_key)):
        for k, lst in bk.items():
            if len(lst) > 1:
                nums = ", ".join(str(x[0]) for x in lst)
                dup_rows.append((label, k, nums))

    stats = {
        "skip_q_sample": skip_q_s,
        "skip_q_test": skip_q_t,
        "only_sample": len(only_s),
        "only_test": len(only_t),
        "mismatch_rows": len(mismatch_keys),
    }

    wb = load_workbook(test_path, data_only=False)
    _ensure_output_sheet(wb, output_sheet, overwrite)
    ws = wb[output_sheet]

    r = 1
    r = _write_metadata(ws, r, sample_path, test_path, stats)

    ws.cell(row=r, column=1, value="Дубликаты ключа Q (duplicate key)").font = _SECTION_FONT
    r += 1
    if dup_rows:
        r = _write_table_header(ws, r, ["Файл", "Ключ Q", "Строки Excel"])
        for label, k, nums in dup_rows:
            ws.cell(row=r, column=1, value=label)
            ws.cell(row=r, column=2, value=k)
            ws.cell(row=r, column=3, value=nums)
            r += 1
    else:
        ws.cell(row=r, column=1, value="— нет —")
        r += 1
    r += 1

    ws.cell(row=r, column=1, value="Только в образце (missing in test)").font = _SECTION_FONT
    r += 1
    r = _write_table_header(ws, r, list(SVOD_HEADERS))
    for k in only_s:
        for _excel_r, vals in sample_by_key[k]:
            r = _write_data_row(ws, r, vals)
    if not only_s:
        ws.cell(row=r, column=1, value="— нет —")
        r += 1
    r += 1

    ws.cell(row=r, column=1, value="Только в тесте (extra in test)").font = _SECTION_FONT
    r += 1
    r = _write_table_header(ws, r, list(SVOD_HEADERS))
    for k in only_t:
        for _excel_r, vals in test_by_key[k]:
            r = _write_data_row(ws, r, vals)
    if not only_t:
        ws.cell(row=r, column=1, value="— нет —")
        r += 1
    r += 1

    ws.cell(row=r, column=1, value="Расхождения по полям при совпадении Q (test values, red = differs from sample)").font = _SECTION_FONT
    r += 1
    hdr = ["Ключ Q"] + list(SVOD_HEADERS)
    r = _write_table_header(ws, r, hdr)
    for k in mismatch_keys:
        sample_row = sample_by_key[k][0][1]
        test_row = test_by_key[k][0][1]
        red_local: set[int] = set()
        for j in range(ncols):
            if j in _COMPARE_COL_INDICES:
                if _normalize_for_compare(sample_row[j]) != _normalize_for_compare(test_row[j]):
                    red_local.add(j)
        ws.cell(row=r, column=1, value=k)
        for j in range(ncols):
            col = 2 + j
            cell = ws.cell(row=r, column=col, value=test_row[j])
            if j in red_local:
                cell.fill = _RED_FILL
        r += 1

    if not mismatch_keys:
        ws.cell(row=r, column=1, value="— нет —")
        r += 1

    wb.save(test_path)
    wb.close()

    if dup_rows:
        print(f"Предупреждение: найдены дубликаты ключа Q ({len(dup_rows)} записей), см. лист «{output_sheet}».", file=sys.stderr)
    print(
        f"Готово: {test_path} :: лист «{output_sheet}» "
        f"(только образец: {len(only_s)}, только тест: {len(only_t)}, расхождения полей: {len(mismatch_keys)}).",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сверка листа «СВОД_операций»: эталон vs тест, отчёт в тестовой книге.",
    )
    parser.add_argument(
        "--sample",
        type=Path,
        required=True,
        help="Путь к xlsx с эталонным листом «СВОД_операций»",
    )
    parser.add_argument(
        "--test",
        type=Path,
        default=_ROOT / "2026_01" / "2026_01_Ord_Quantity.xlsx",
        help="Тестируемая книга (куда пишется лист отчёта)",
    )
    parser.add_argument(
        "--sheet-name",
        default="СВОД_операций",
        help="Имя листа для чтения в обоих файлах",
    )
    parser.add_argument(
        "--output-sheet",
        default="СВОД_сверка",
        help="Имя нового листа с результатами в тестовой книге",
    )
    parser.add_argument(
        "--overwrite-output-sheet",
        action="store_true",
        help="Перезаписать лист отчёта, если он уже существует",
    )
    args = parser.parse_args()
    sample = args.sample.resolve()
    test = args.test.resolve()
    if not sample.is_file():
        print(f"Файл образца не найден: {sample}", file=sys.stderr)
        return 1
    if not test.is_file():
        print(f"Файл теста не найден: {test}", file=sys.stderr)
        return 1

    return build_report(
        sample,
        test,
        args.sheet_name,
        args.output_sheet,
        args.overwrite_output_sheet,
    )


if __name__ == "__main__":
    raise SystemExit(main())
