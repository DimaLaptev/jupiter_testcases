"""Справочник.xlsx — листы «Таблица сопоставления 1» и «2»."""

from __future__ import annotations

from pathlib import Path

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets
from sql_upload.predsvod_layout import (
    SPRAV1_ACCOUNT_COL,
    SPRAV1_COL_END,
    SPRAV1_ROW_START,
    SPRAV2_COL_END,
    SPRAV2_ROW_START,
)

from models import Sprav1Record


def _norm_account(s: str | None) -> str:
    return (s or "").strip().casefold()


def _norm_depo(s: str | None) -> str:
    return (s or "").strip().casefold()


class Sprav1Lookup:
    def __init__(self) -> None:
        self._by_account: dict[str, Sprav1Record] = {}

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
            lookup._by_account[_norm_account(account)] = Sprav1Record(
                depository=cell_at(rows, r, 2) or None,
                owner=cell_at(rows, r, 10) or None,
                servisny_agent=cell_at(rows, r, 5) or None,
                sdelka_ia=cell_at(rows, r, 6) or None,
                enc=enc or None,
                vid_ucheta=vid or None,
            )
        return lookup

    def get(self, schet_depo: str | None) -> Sprav1Record | None:
        if not schet_depo:
            return None
        return self._by_account.get(_norm_account(schet_depo))


class Sprav2Lookup:
    def __init__(self) -> None:
        self._by_depo_section: dict[tuple[str, str], str] = {}

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
        last = last_row_in_column(rows, 1)
        for r in range(SPRAV2_ROW_START, last + 1):
            depo = cell_at(rows, r, 1)
            section = cell_at(rows, r, 2)
            city = cell_at(rows, r, 3)
            if not section.strip():
                continue
            lookup._by_depo_section[(_norm_depo(depo), section.strip())] = city.strip()
        return lookup

    def get(self, depository: str | None, section: str | None, aliases: dict[str, str] | None = None) -> str | None:
        if not section:
            return None
        sec = section.strip()
        depo_keys = [_norm_depo(depository)]
        if aliases and depository:
            alias = aliases.get(_norm_depo(depository))
            if alias:
                depo_keys.append(_norm_depo(alias))

        for dk in depo_keys:
            city = self._by_depo_section.get((dk, sec))
            if city:
                return city
        for (d, s), city in self._by_depo_section.items():
            if s == sec and (not depository or d in depo_keys):
                return city
        return None
