"""Поиск дублей НГРИ и номеров закладных в портфеле по workbook."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from models import SvodRow

DUPLICATES_SHEET_NAME = "Дубли"
DUPLICATES_NGRI_HEADER = "НГРИ в депо"
DUPLICATES_PORTFOLIO_HEADER = "Номер закладной в портфеле"


@dataclass(frozen=True)
class WorkbookDuplicates:
    ngri: tuple[str, ...]
    portfolio: tuple[str, ...]

    @property
    def has_any(self) -> bool:
        return bool(self.ngri or self.portfolio)


def _collect_values(
    rows_by_sheet: dict[str, list[SvodRow]],
    sheet_order: tuple[str, ...],
    attr: str,
) -> Counter[str]:
    display_by_norm: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for sheet_name in sheet_order:
        for row in rows_by_sheet.get(sheet_name, []):
            raw = getattr(row, attr)
            if raw is None:
                continue
            display = raw.strip()
            if not display:
                continue
            norm = display.casefold()
            display_by_norm.setdefault(norm, display)
            counts[norm] += 1
    return Counter({display_by_norm[n]: c for n, c in counts.items()})


def find_workbook_duplicates(
    rows_by_sheet: dict[str, list[SvodRow]],
    sheet_order: tuple[str, ...],
) -> WorkbookDuplicates:
    """Дубли по всем листам одного workbook (значение встречается > 1 раза)."""
    ngri_counts = _collect_values(rows_by_sheet, sheet_order, "ngri_v_depo")
    portfolio_counts = _collect_values(rows_by_sheet, sheet_order, "n_zakladnoy_portfel")

    dup_ngri = tuple(sorted((v for v, c in ngri_counts.items() if c > 1), key=str.casefold))
    dup_portfolio = tuple(
        sorted((v for v, c in portfolio_counts.items() if c > 1), key=str.casefold),
    )
    return WorkbookDuplicates(ngri=dup_ngri, portfolio=dup_portfolio)
