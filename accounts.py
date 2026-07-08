"""Лист «Валидация»: счета из Справочника и количество закладных в отчёте."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from models import SvodRow
from references.spravochnik import Sprav1Lookup, normalize_account

VALIDATION_SHEET_NAME = "Валидация"
VALIDATION_HEADERS: tuple[str, ...] = (
    "Раздел КП",
    "Депозитарий",
    "Счет_ДЕПО",
    "Количество в отчет",
)


@dataclass(frozen=True)
class ValidationRow:
    razdel_kp: str | None
    depository: str | None
    schet_depo: str
    count: int


def _count_by_account(
    rows_by_sheet: dict[str, list[SvodRow]],
    sheet_order: tuple[str, ...],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for sheet_name in sheet_order:
        for row in rows_by_sheet.get(sheet_name, []):
            if not row.schet_depo:
                continue
            counts[normalize_account(row.schet_depo)] += 1
    return counts


def build_validation_rows(
    sprav1: Sprav1Lookup,
    rows_by_sheet: dict[str, list[SvodRow]],
    sheet_order: tuple[str, ...],
) -> list[ValidationRow]:
    """Счета Справочника для разделов КП данного workbook + число строк по счёту."""
    counts = _count_by_account(rows_by_sheet, sheet_order)
    allowed_sections = {name.casefold() for name in sheet_order}
    out: list[ValidationRow] = []
    for account, rec in sprav1.iter_accounts():
        section = (rec.portfolio_section or "").strip()
        if section.casefold() not in allowed_sections:
            continue
        norm = normalize_account(account)
        out.append(
            ValidationRow(
                razdel_kp=rec.portfolio_section,
                depository=rec.depository,
                schet_depo=account,
                count=counts.get(norm, 0),
            ),
        )
    return out


def count_zero_accounts(rows: list[ValidationRow]) -> int:
    return sum(1 for row in rows if row.count == 0)
