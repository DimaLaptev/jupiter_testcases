"""Справочник.xlsx — листы «Таблица сопоставления 1» и «2»."""

from __future__ import annotations

import re
from pathlib import Path

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets
from sql_upload.predsvod_layout import (
    SPRAV1_ACCOUNT_COL,
    SPRAV1_PORTFOLIO_SECTION_COL,
    SPRAV1_ROW_START,
    SPRAV2_ROW_START,
)

from models import Sprav1Record


def _norm_account(s: str | None) -> str:
    return (s or "").strip().casefold()


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().casefold())


class Sprav1Lookup:
    def __init__(self) -> None:
        self._by_account: dict[str, Sprav1Record] = {}
        self._display_by_norm: dict[str, str] = {}

    @classmethod
    def load(cls, path: Path, sheet_index: int = 0) -> Sprav1Lookup:
        lookup = cls()
        if not path.is_file():
            return lookup

        sheets = read_workbook_sheets(path)
        if sheet_index >= len(sheets):
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
            enc = cell_at(rows, r, 12)
            vid = cell_at(rows, r, 13)
            if "кодификатор" in enc.lower() or "см." in enc.lower():
                enc = ""
            if "кодификатор" in vid.lower() or "см." in vid.lower():
                vid = ""
            portfolio = cell_at(rows, r, SPRAV1_PORTFOLIO_SECTION_COL).strip() or None
            norm = _norm_account(account)
            lookup._display_by_norm.setdefault(norm, account.strip())
            lookup._by_account[norm] = Sprav1Record(
                depository=cell_at(rows, r, 2) or None,
                owner=cell_at(rows, r, 10) or None,
                servisny_agent=cell_at(rows, r, 5) or None,
                sdelka_ia=cell_at(rows, r, 6) or None,
                enc=enc or None,
                vid_ucheta=vid or None,
                portfolio_section=portfolio,
            )
        return lookup

    def get(self, schet_depo: str | None) -> Sprav1Record | None:
        if not schet_depo:
            return None
        return self._by_account.get(_norm_account(schet_depo))

    def portfolio_section(self, schet_depo: str | None) -> str | None:
        rec = self.get(schet_depo)
        if rec is None:
            return None
        return rec.portfolio_section

    def all_accounts(self) -> list[str]:
        """Все «Номер счета депo» из листа 1 (как в файле)."""
        return sorted(self._display_by_norm.values(), key=lambda s: s.casefold())

    def normalized_accounts(self) -> frozenset[str]:
        return frozenset(self._display_by_norm.keys())

    def display_account(self, norm: str) -> str:
        return self._display_by_norm.get(norm, norm)


def normalize_account(s: str | None) -> str:
    return _norm_account(s)


class Sprav2Lookup:
    def __init__(self) -> None:
        self._by_section: dict[str, str] = {}
        self._depository_rows: list[tuple[str, str]] = []

    @classmethod
    def load(cls, path: Path, sheet_index: int = 1) -> Sprav2Lookup:
        lookup = cls()
        if not path.is_file():
            return lookup

        sheets = read_workbook_sheets(path)
        if sheet_index >= len(sheets):
            for i, (name, _) in enumerate(sheets):
                if "сопоставления 2" in (name or "").lower():
                    sheet_index = i
                    break

        if sheet_index >= len(sheets):
            return lookup

        _name, rows = sheets[sheet_index]
        if not rows:
            return lookup

        header_row = 1
        header = rows[header_row - 1] if header_row <= len(rows) else []
        col_map = {_norm_header(h): i for i, h in enumerate(header) if (h or "").strip()}

        depository_col: int | None = None
        section_col: int | None = None
        city_col: int | None = None
        for key, idx in col_map.items():
            if key == "депозитарий" or key.startswith("депозитарий"):
                depository_col = idx + 1
            if "номер раздела" in key and "текст" in key:
                section_col = idx + 1
            if "город" in key and "место хранения" in key:
                city_col = idx + 1

        depository_col = depository_col or 1
        section_col = section_col or 2
        city_col = city_col or 3

        last = max(
            last_row_in_column(rows, depository_col),
            last_row_in_column(rows, section_col),
        )
        for r in range(SPRAV2_ROW_START, last + 1):
            depo = cell_at(rows, r, depository_col).strip()
            section = cell_at(rows, r, section_col).strip()
            city = cell_at(rows, r, city_col).strip()
            if depo and city:
                lookup._depository_rows.append((depo, city))
            if section:
                lookup._by_section[section] = city
        return lookup

    def get(self, section: str | None) -> str | None:
        if not section:
            return None
        sec = section.strip()
        city = self._by_section.get(sec)
        if city:
            return city
        for key, val in self._by_section.items():
            if key.casefold() == sec.casefold():
                return val
        return None

    def get_by_depository_substring(self, *needles: str) -> str | None:
        """Первая строка, где «Депозитарий» содержит одну из подстрок."""
        for depo, city in self._depository_rows:
            depo_norm = depo.casefold()
            for needle in needles:
                if needle.casefold() in depo_norm:
                    return city
        return None
