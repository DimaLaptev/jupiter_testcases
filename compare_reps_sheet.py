#!/usr/bin/env python3
"""Сверка листа «REPs» (образец vs тест) и проверка строк образца на листе «СВОД_операций»; отчёт в тестовой xlsx."""

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

from reps_excel import REPS_HEADERS
from svod_excel import SVOD_HEADERS

# Ключ REPs↔REPs: A,B,C,D,G,K (Источник, № п/п, Номер операции, НГРИ, Дата операции, счет депо)
_REPS_KEY_COL_INDICES = (0, 1, 2, 3, 6, 10)

# СВОД: дата, счёт депо, НГРИ, источник (для опционального ужесточения)
_SVOD_COL_DATE = 0
_SVOD_COL_DEPO = 5
_SVOD_COL_NGRI = 11
_SVOD_COL_SOURCE = 17

_RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
_TITLE_FONT = Font(bold=True)
_SECTION_FONT = Font(bold=True, size=12)


def _norm_header_cell(val: object) -> str:
    if val is None:
        return ""
    return str(val).strip()


def find_svod_header_row(ws: Worksheet, first_header: str) -> int:
    expect = first_header.strip()
    max_r = min(ws.max_row or 1, 200)
    for r in range(1, max_r + 1):
        if _norm_header_cell(ws.cell(row=r, column=1).value) == expect:
            return r
    return 0


def find_reps_header_row(ws: Worksheet, max_scan: int = 10) -> int:
    """Строка заголовка: в A — «Источник» (REPS_HEADERS[0])."""
    expect = REPS_HEADERS[0].strip()
    max_r = min(ws.max_row or 1, max_scan)
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
        f = float(s.replace(",", "."))
        if f == int(f):
            return str(int(f))
        return str(f)
    except ValueError:
        return s


def _row_values(ws: Worksheet, excel_row: int, ncols: int) -> list[object]:
    return [ws.cell(row=excel_row, column=c + 1).value for c in range(ncols)]


def reps_row_key(vals: list[object]) -> str:
    parts = [
        _normalize_for_compare(vals[i]) if i < len(vals) else ""
        for i in _REPS_KEY_COL_INDICES
    ]
    return "|".join(parts)


def reps_triple_for_svod(vals: list[object]) -> str:
    """Тройка для сопоставления с СВОД: дата | счёт депо | НГРИ (колонки G,K,D → индексы 6,10,3)."""
    d = _normalize_for_compare(vals[6]) if len(vals) > 6 else ""
    dep = _normalize_for_compare(vals[10]) if len(vals) > 10 else ""
    ngri = _normalize_for_compare(vals[3]) if len(vals) > 3 else ""
    return f"{d}|{dep}|{ngri}"


def load_reps_table(
    path: Path,
    sheet_name: str,
    label: str,
) -> tuple[dict[str, list[tuple[int, list[object]]]], int, int, int]:
    wb = load_workbook(path, data_only=True)
    try:
        if sheet_name not in wb.sheetnames:
            raise SystemExit(f"[{label}] Нет листа «{sheet_name}»: {path}")
        ws = wb[sheet_name]
        header_row = find_reps_header_row(ws)
        if header_row == 0:
            raise SystemExit(
                f"[{label}] Не найдена строка заголовка REPs (колонка A = «{REPS_HEADERS[0]}»): {path}",
            )
        for ci, title in enumerate(REPS_HEADERS):
            got = _norm_header_cell(ws.cell(row=header_row, column=ci + 1).value)
            if got and got != title.strip():
                print(
                    f"[{label}] Предупреждение: колонка {ci + 1} заголовок «{got}» != эталону «{title}» ({path.name})",
                    file=sys.stderr,
                )
        ncols = len(REPS_HEADERS)
        by_key: dict[str, list[tuple[int, list[object]]]] = defaultdict(list)
        skipped_empty = 0
        max_r = ws.max_row or header_row
        for r in range(header_row + 1, max_r + 1):
            vals = _row_values(ws, r, ncols)
            if all(v is None or str(v).strip() == "" for v in vals):
                continue
            key = reps_row_key(vals)
            key_parts = key.split("|")
            if not any(p.strip() for p in key_parts):
                skipped_empty += 1
                continue
            by_key[key].append((r, vals))
        return dict(by_key), header_row, skipped_empty, ncols
    finally:
        wb.close()


def load_svod_triple_index(
    path: Path,
    sheet_name: str,
    label: str,
) -> tuple[list[tuple[str, str]], int]:
    """
    Список (triple, source_norm) по строкам СВОД; triple = дата|счёт|НГРИ.
    Возвращает также header_row (0 если листа нет или заголовок не найден).
    """
    wb = load_workbook(path, data_only=True)
    try:
        if sheet_name not in wb.sheetnames:
            print(f"[{label}] Нет листа «{sheet_name}»: {path}", file=sys.stderr)
            return [], 0
        ws = wb[sheet_name]
        header_row = find_svod_header_row(ws, SVOD_HEADERS[0])
        if header_row == 0:
            print(
                f"[{label}] Не найден заголовок СВОД (A = «{SVOD_HEADERS[0]}»): {path}",
                file=sys.stderr,
            )
            return [], 0
        ncols = len(SVOD_HEADERS)
        out: list[tuple[str, str]] = []
        max_r = ws.max_row or header_row
        for r in range(header_row + 1, max_r + 1):
            vals = _row_values(ws, r, ncols)
            if all(v is None or str(v).strip() == "" for v in vals):
                continue
            d = _normalize_for_compare(vals[_SVOD_COL_DATE]) if len(vals) > _SVOD_COL_DATE else ""
            dep = _normalize_for_compare(vals[_SVOD_COL_DEPO]) if len(vals) > _SVOD_COL_DEPO else ""
            ngri = _normalize_for_compare(vals[_SVOD_COL_NGRI]) if len(vals) > _SVOD_COL_NGRI else ""
            src = ""
            if len(vals) > _SVOD_COL_SOURCE:
                src = _normalize_for_compare(vals[_SVOD_COL_SOURCE])
            triple = f"{d}|{dep}|{ngri}"
            out.append((triple, src))
        return out, header_row
    finally:
        wb.close()


def _reps_row_in_svod(
    reps_vals: list[object],
    svod_rows: list[tuple[str, str]],
    require_source: bool,
) -> bool:
    triple = reps_triple_for_svod(reps_vals)
    reps_src = (_normalize_for_compare(reps_vals[0]) if reps_vals else "").lower()
    if not any(triple.split("|")):
        return False
    for t, s_src in svod_rows:
        if t != triple:
            continue
        if not require_source:
            return True
        s_low = s_src.lower()
        if reps_src and reps_src in s_low:
            return True
    return False


def _ensure_output_sheet(wb, name: str, overwrite: bool) -> None:
    if name in wb.sheetnames:
        if not overwrite:
            raise SystemExit(
                f"Лист «{name}» уже есть. Укажите --overwrite-output-sheet или другое --output-sheet.",
            )
        wb.remove(wb[name])
    wb.create_sheet(name)


def _write_table_header(ws: Worksheet, row: int, headers: list[str], start_col: int = 1) -> int:
    for i, h in enumerate(headers):
        ws.cell(row=row, column=start_col + i, value=h).font = _TITLE_FONT
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
    reps_sheet: str,
    sample_reps_sheet: str | None,
    svod_sheet: str,
    output_sheet: str,
    overwrite: bool,
    require_source: bool,
) -> int:
    sample_sheet = sample_reps_sheet or reps_sheet
    sample_by_key, _, skip_empty_s, ncols = load_reps_table(
        sample_path, sample_sheet, "образец"
    )
    test_by_key, _, skip_empty_t, _ = load_reps_table(test_path, reps_sheet, "тест")

    svod_rows, _svod_hr = load_svod_triple_index(test_path, svod_sheet, "тест/СВОД")

    keys_sample = set(sample_by_key.keys())
    keys_test = set(test_by_key.keys())
    only_s = sorted(keys_sample - keys_test)
    only_t = sorted(keys_test - keys_sample)
    common = sorted(keys_sample & keys_test)

    compare_indices = list(range(ncols))
    mismatch_keys: list[str] = []
    for k in common:
        s_row = sample_by_key[k][0][1]
        t_row = test_by_key[k][0][1]
        diff = False
        for ci in compare_indices:
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

    sample_not_in_svod: list[list[object]] = []
    unmappable = 0
    for k, lst in sample_by_key.items():
        for _r, vals in lst:
            triple = reps_triple_for_svod(vals)
            parts = triple.split("|")
            if len(parts) >= 3 and not (parts[0].strip() or parts[1].strip() or parts[2].strip()):
                unmappable += 1
                sample_not_in_svod.append(vals)
                continue
            if not _reps_row_in_svod(vals, svod_rows, require_source):
                sample_not_in_svod.append(vals)

    stats = {
        "skip_empty_sample": skip_empty_s,
        "skip_empty_test": skip_empty_t,
        "only_sample": len(only_s),
        "only_test": len(only_t),
        "mismatch_rows": len(mismatch_keys),
        "sample_rows_not_in_svod": len(sample_not_in_svod),
        "unmappable_triple": unmappable,
        "svod_index_rows": len(svod_rows),
        "require_source": require_source,
    }

    wb = load_workbook(test_path, data_only=False)
    _ensure_output_sheet(wb, output_sheet, overwrite)
    ws = wb[output_sheet]

    r = 1
    ws.cell(row=r, column=1, value="Сверка листа «REPs» и связь с «СВОД_операций»").font = _SECTION_FONT
    r += 1
    ws.cell(row=r, column=1, value=f"Время (UTC): {datetime.now(timezone.utc).isoformat()}")
    r += 1
    ws.cell(row=r, column=1, value=f"Образец (sample): {sample_path}")
    r += 1
    ws.cell(row=r, column=1, value=f"Тест (test): {test_path}")
    r += 1
    ws.cell(row=r, column=1, value=f"Лист REPs (тест): «{reps_sheet}»; образец: «{sample_sheet}»")
    r += 1
    ws.cell(row=r, column=1, value=f"СВОД в тесте: «{svod_sheet}», строк в индексе: {stats['svod_index_rows']}")
    r += 1
    ws.cell(row=r, column=1, value=f"REPs→СВОД: жёсткая проверка «Источник» (substring): {stats['require_source']}")
    r += 1
    ws.cell(row=r, column=1, value=f"Пропущено пустой ключ REPs (образец): {stats['skip_empty_sample']}")
    r += 1
    ws.cell(row=r, column=1, value=f"Пропущено пустой ключ REPs (тест): {stats['skip_empty_test']}")
    r += 1
    ws.cell(row=r, column=1, value=f"Только в образце REPs (нет в тесте REPs): {stats['only_sample']}")
    r += 1
    ws.cell(row=r, column=1, value=f"Только в тесте REPs (нет в образце): {stats['only_test']}")
    r += 1
    ws.cell(row=r, column=1, value=f"Совпало по ключу REPs, но поля отличаются: {stats['mismatch_rows']}")
    r += 1
    ws.cell(row=r, column=1, value=f"Строк образца REPs без пары в СВОД_операций (тест): {stats['sample_rows_not_in_svod']}")
    r += 1
    if stats["unmappable_triple"]:
        ws.cell(row=r, column=1, value=f"Из них без тройки дата|счёт|НГРИ: {stats['unmappable_triple']}")
        r += 1
    r += 1

    ws.cell(row=r, column=1, value="Дубликаты ключа REPs (A|B|C|D|G|K)").font = _SECTION_FONT
    r += 1
    if dup_rows:
        r = _write_table_header(ws, r, ["Файл", "Ключ", "Строки Excel"])
        for label, k, nums in dup_rows:
            ws.cell(row=r, column=1, value=label)
            ws.cell(row=r, column=2, value=k)
            ws.cell(row=r, column=3, value=nums)
            r += 1
    else:
        ws.cell(row=r, column=1, value="— нет —")
        r += 1
    r += 1

    ws.cell(row=r, column=1, value="Только в образце REPs (missing in test REPs)").font = _SECTION_FONT
    r += 1
    r = _write_table_header(ws, r, list(REPS_HEADERS))
    for k in only_s:
        for _excel_r, vals in sample_by_key[k]:
            r = _write_data_row(ws, r, vals)
    if not only_s:
        ws.cell(row=r, column=1, value="— нет —")
        r += 1
    r += 1

    ws.cell(row=r, column=1, value="Только в тесте REPs (extra in test)").font = _SECTION_FONT
    r += 1
    r = _write_table_header(ws, r, list(REPS_HEADERS))
    for k in only_t:
        for _excel_r, vals in test_by_key[k]:
            r = _write_data_row(ws, r, vals)
    if not only_t:
        ws.cell(row=r, column=1, value="— нет —")
        r += 1
    r += 1

    ws.cell(row=r, column=1, value="Расхождения полей при совпадении ключа REPs (значения теста, красный ≠ образец)").font = _SECTION_FONT
    r += 1
    hdr = ["Ключ REPs"] + list(REPS_HEADERS)
    r = _write_table_header(ws, r, hdr)
    for k in mismatch_keys:
        sample_row = sample_by_key[k][0][1]
        test_row = test_by_key[k][0][1]
        red_local: set[int] = set()
        for j in range(ncols):
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
    r += 1

    ws.cell(row=r, column=1, value="Образец REPs: нет соответствующей строки в СВОД_операций (тест)").font = _SECTION_FONT
    r += 1
    note = (
        "Сопоставление: дата операции | счёт депо | НГРИ (колонки REPs G,K,D ↔ СВОД A,F,L). "
        "Пустой блок СВОД возможен по бизнес-правилам (не все REP попадают в свод)."
    )
    ws.cell(row=r, column=1, value=note)
    r += 1
    r = _write_table_header(ws, r, list(REPS_HEADERS))
    for vals in sample_not_in_svod:
        r = _write_data_row(ws, r, vals)
    if not sample_not_in_svod:
        ws.cell(row=r, column=1, value="— нет —")
        r += 1

    wb.save(test_path)
    wb.close()

    if dup_rows:
        print(
            f"Предупреждение: дубликаты ключа REPs ({len(dup_rows)} записей), см. лист «{output_sheet}».",
            file=sys.stderr,
        )
    print(
        f"Готово: {test_path} :: лист «{output_sheet}» "
        f"(только образец REPs: {len(only_s)}, только тест REPs: {len(only_t)}, "
        f"расхождения полей: {len(mismatch_keys)}, образец без СВОД: {len(sample_not_in_svod)}).",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Сверка REPs (образец vs тест) и проверка строк образца на листе СВОД_операций в тестовой книге.",
    )
    parser.add_argument(
        "--sample",
        type=Path,
        required=True,
        help="Путь к xlsx с эталонным листом REPs",
    )
    parser.add_argument(
        "--test",
        type=Path,
        default=_ROOT / "2026_01" / "2026_01_Ord_Quantity.xlsx",
        help="Тестируемая книга (куда пишется лист отчёта)",
    )
    parser.add_argument(
        "--reps-sheet",
        default="REPs",
        help="Имя листа REPs в тестовой книге",
    )
    parser.add_argument(
        "--sample-sheet",
        default=None,
        help="Имя листа REPs в книге образца (по умолчанию как --reps-sheet)",
    )
    parser.add_argument(
        "--svod-sheet",
        default="СВОД_операций",
        help="Имя листа СВОД в тестовой книге",
    )
    parser.add_argument(
        "--output-sheet",
        default="REPs_сверка",
        help="Имя нового листа с результатами в тестовой книге",
    )
    parser.add_argument(
        "--overwrite-output-sheet",
        action="store_true",
        help="Перезаписать лист отчёта, если он уже существует",
    )
    parser.add_argument(
        "--reps-svod-require-source",
        action="store_true",
        help="Для REPs→СВОД дополнительно: колонка R СВОД должна содержать подстроку из колонки A REPs",
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
        args.reps_sheet,
        args.sample_sheet,
        args.svod_sheet,
        args.output_sheet,
        args.overwrite_output_sheet,
        args.reps_svod_require_source,
    )


if __name__ == "__main__":
    raise SystemExit(main())
