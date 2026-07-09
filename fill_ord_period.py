#!/usr/bin/env python3
"""Сборка Ord_Quantity за период из одного каталога (2026_05, …)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from period_paths import resolve_period_dir  # noqa: E402


def _run_step(label: str, cmd: list[str]) -> int:
    print(f"\n=== {label} ===", flush=True)
    print(" ", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(_ROOT))
    if proc.returncode != 0:
        print(f"Ошибка на шаге «{label}» (код {proc.returncode})", file=sys.stderr)
    return proc.returncode


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Полная сборка Ord_Quantity из каталога периода: "
            "Dks → REPs → СВОД_операций → ORD Количество поручений"
        ),
    )
    p.add_argument(
        "--period-dir",
        "--input-dir",
        dest="period_dir",
        type=Path,
        required=True,
        help="Каталог периода (2026_05); --input-dir — синоним",
    )
    p.add_argument("--year", type=int, default=None, help="Год (по умолчанию из имени каталога)")
    p.add_argument("--month", type=int, default=None, help="Месяц (по умолчанию из имени каталога)")
    p.add_argument(
        "--init-workbook",
        action="store_true",
        help="Создать шаблон книги, если файла ещё нет",
    )
    p.add_argument("--skip-dks", action="store_true", help="Не заполнять лист Dks")
    p.add_argument("--skip-reps", action="store_true", help="Не заполнять лист REPs")
    p.add_argument("--skip-svod", action="store_true", help="Не заполнять лист СВОД_операций")
    p.add_argument("--skip-ord", action="store_true", help="Не строить матрицу ORD")
    p.add_argument(
        "--ensure-reference-sheets",
        action="store_true",
        help="На шаге СВОД: создать «Счета депо»/«Коды», если отсутствуют",
    )
    args = p.parse_args()

    pp = resolve_period_dir(args.period_dir, _ROOT)
    year = args.year if args.year is not None else pp.year
    month = args.month if args.month is not None else pp.month
    if year is None or month is None:
        print(
            "Укажите --year и --month или используйте каталог вида 2026_05",
            file=sys.stderr,
        )
        return 1

    py = sys.executable
    period = str(pp.period_dir)
    wb = str(pp.workbook)

    if args.init_workbook and not pp.workbook.is_file():
        rc = _run_step(
            "init",
            [
                py,
                str(_SCRIPTS / "init_ord_quantity_workbook.py"),
                "--out",
                wb,
            ],
        )
        if rc != 0:
            return rc

    if not args.skip_dks:
        rc = _run_step(
            "Dks",
            [py, str(_SCRIPTS / "fill_dks_from_d_msg.py"), "--period-dir", period],
        )
        if rc != 0:
            return rc

    if not args.skip_reps:
        rc = _run_step(
            "REPs",
            [py, str(_SCRIPTS / "fill_reps_from_rep_xls.py"), "--period-dir", period],
        )
        if rc != 0:
            return rc

    if not args.skip_svod:
        svod_cmd = [
            py,
            str(_SCRIPTS / "fill_svod_from_i_msg.py"),
            "--period-dir",
            period,
        ]
        if args.ensure_reference_sheets:
            svod_cmd.append("--ensure-reference-sheets")
        rc = _run_step("СВОД_операций", svod_cmd)
        if rc != 0:
            return rc

    if not args.skip_ord:
        rc = _run_step(
            "ORD Количество поручений",
            [
                py,
                str(_SCRIPTS / "fill_ord_quantity_from_svod.py"),
                "--period-dir",
                period,
                "--year",
                str(year),
                "--month",
                str(month),
                "--ensure-sheet",
            ],
        )
        if rc != 0:
            return rc

    print(f"\nГотово: {pp.workbook}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
