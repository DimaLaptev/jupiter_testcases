"""Проверка покрытия счетов из Справочника строками источников ДО."""

from __future__ import annotations

import sys
from typing import TextIO

from models import ALL_PORTFOLIO_SHEETS, DepoReportRow
from references.spravochnik import Sprav1Lookup, normalize_account


def find_missing_sprav_accounts(
    sprav1: Sprav1Lookup,
    do_rows: list[DepoReportRow],
) -> list[str]:
    """
    Счета из col C «Номер счета депo», для которых не будет ни одной строки свода.

    Строка попадёт в свод, если есть DepoReportRow с этим счётом и заполнен
    «Раздел КП для Свода депo» (col K) из известных листов.
    """
    required = sprav1.normalized_accounts()
    if not required:
        return []

    valid_sections = set(ALL_PORTFOLIO_SHEETS)
    covered: set[str] = set()
    for row in do_rows:
        if not row.schet_depo:
            continue
        norm = normalize_account(row.schet_depo)
        if norm not in required:
            continue
        section = sprav1.portfolio_section(row.schet_depo)
        if section and section in valid_sections:
            covered.add(norm)

    missing_norms = required - covered
    return [
        sprav1.display_account(norm)
        for norm in sorted(missing_norms, key=lambda n: sprav1.display_account(n).casefold())
    ]


def report_missing_sprav_accounts(
    missing: list[str],
    *,
    out: TextIO | None = None,
) -> None:
    stream: TextIO = out or sys.stdout
    stream.write(
        "ОШИБКА валидации СВОД: для счетов из «Справочник.xlsx» "
        "нет ни одной строки на листах свода:\n",
    )
    for account in missing:
        stream.write(f"  - {account}\n")
    stream.write(
        f"Всего: {len(missing)} счёт(ов). Сборка прервана, файлы не записаны.\n",
    )
