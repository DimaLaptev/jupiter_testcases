"""Справочник.xlsx — лист «Таблица сопоставления 1» для маршрута Ord и колонки ДЕПО."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets
from sql_upload.predsvod_layout import (
    SPRAV1_ACCOUNT_COL,
    SPRAV1_PORTFOLIO_SECTION_COL,
    SPRAV1_ROW_START,
)

# Col B «Депозитарий»
_SPRAV1_DEPOSITORY_COL = 2

WorkbookTarget = str  # "ia" | "dom"


@dataclass(frozen=True)
class SpravAccountRecord:
    depository: str | None
    portfolio_section: str | None


def normalize_account(s: str | None) -> str:
    return (s or "").strip().casefold()


def depo_code_from_depository(depository: str | None) -> str | None:
    """Краткий код для колонки ДЕПО."""
    if not depository:
        return None
    folded = depository.strip().casefold()
    if not folded:
        return None
    if "регион" in folded or "region" in folded:
        return "РЕГИОН"
    if "гпб" in folded or "gpb" in folded:
        return "ГПБ"
    if "втб" in folded or "vtb" in folded:
        return "VTBSD"
    if "рсд" in folded or "rsd" in folded:
        return "RSD"
    return depository.strip()


def workbook_target_from_portfolio(section: str | None) -> WorkbookTarget | None:
    """
    ДОМ / ИНВЕСТОРЫ / РезСервис → Day_Quantity_DOM;
    ДОМ ИА… → Day_Quantity (IA).
    """
    if not section:
        return None
    s = " ".join(section.strip().split())
    folded = s.casefold()
    if not folded:
        return None
    if "дом иа" in folded:
        return "ia"
    if folded in {"дом", "инвесторы"}:
        return "dom"
    if "резсервис" in folded or "оригинатор" in folded:
        return "dom"
    if folded.startswith("дом"):
        return "dom"
    return None


class Sprav1Lookup:
    def __init__(self) -> None:
        self._by_account: dict[str, SpravAccountRecord] = {}
        self._display_by_norm: dict[str, str] = {}

    @classmethod
    def load(cls, path: Path) -> Sprav1Lookup:
        lookup = cls()
        if not path.is_file():
            return lookup

        sheets = read_workbook_sheets(path)
        sheet_index = 0
        for i, (name, _) in enumerate(sheets):
            if "сопоставления 1" in (name or "").lower():
                sheet_index = i
                break
        if sheet_index >= len(sheets):
            return lookup

        _name, rows = sheets[sheet_index]
        last = last_row_in_column(rows, SPRAV1_ACCOUNT_COL)
        for r in range(SPRAV1_ROW_START, last + 1):
            account = cell_at(rows, r, SPRAV1_ACCOUNT_COL)
            if not account.strip():
                continue
            portfolio = cell_at(rows, r, SPRAV1_PORTFOLIO_SECTION_COL).strip() or None
            depository = cell_at(rows, r, _SPRAV1_DEPOSITORY_COL).strip() or None
            norm = normalize_account(account)
            lookup._display_by_norm.setdefault(norm, account.strip())
            lookup._by_account[norm] = SpravAccountRecord(
                depository=depository,
                portfolio_section=portfolio,
            )
        return lookup

    def get(self, schet_depo: str | None) -> SpravAccountRecord | None:
        if not schet_depo:
            return None
        return self._by_account.get(normalize_account(schet_depo))

    def portfolio_section(self, schet_depo: str | None) -> str | None:
        rec = self.get(schet_depo)
        return rec.portfolio_section if rec else None

    def depo_code(self, schet_depo: str | None) -> str | None:
        rec = self.get(schet_depo)
        if rec is None:
            return None
        return depo_code_from_depository(rec.depository)

    def workbook_target(self, schet_depo: str | None) -> WorkbookTarget | None:
        rec = self.get(schet_depo)
        if rec is None:
            return None
        return workbook_target_from_portfolio(rec.portfolio_section)

    def display_account(self, schet_depo: str) -> str:
        norm = normalize_account(schet_depo)
        return self._display_by_norm.get(norm, schet_depo.strip())
