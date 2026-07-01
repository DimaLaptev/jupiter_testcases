"""Загрузка DEPO_DOM.xlsx / DEPO_IA.xlsx (свод за пред. месяц)."""

from __future__ import annotations

from pathlib import Path

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets

from models import DEPO_DOM_SHEETS, DEPO_IA_SHEETS, DepoDomRecord


def _norm_key(s: str | None) -> str:
    return (s or "").strip().casefold()


class DepoDomIndex:
    """Индексы по листам отчёта пред. месяца: by_portfolio[A], by_ngri[K]."""

    def __init__(self) -> None:
        self._by_portfolio: dict[str, dict[str, DepoDomRecord]] = {}
        self._by_ngri: dict[str, dict[str, DepoDomRecord]] = {}

    @classmethod
    def load(
        cls,
        path: Path,
        sheet_names: tuple[str, ...] = DEPO_DOM_SHEETS,
    ) -> DepoDomIndex:
        idx = cls()
        for sheet_name in sheet_names:
            idx._by_portfolio[sheet_name] = {}
            idx._by_ngri[sheet_name] = {}

        if not path.is_file():
            return idx

        wb_sheets = read_workbook_sheets(path)
        sheet_map = {name: rows for name, rows in wb_sheets}

        for sheet_name in sheet_names:
            rows = sheet_map.get(sheet_name)
            if not rows:
                for k, v in sheet_map.items():
                    if k.strip().upper() == sheet_name.upper():
                        rows = v
                        break
            if not rows:
                continue
            idx._load_sheet(sheet_name, rows)
        return idx

    def _load_sheet(self, sheet_name: str, rows: list[list[str]]) -> None:
        last = last_row_in_column(rows, 1)
        for r in range(4, last + 1):
            rec = DepoDomRecord(
                portfolio_no=cell_at(rows, r, 1) or None,
                dom_no=cell_at(rows, r, 2) or None,
                fio=cell_at(rows, r, 9) or None,
                nomer_kd=cell_at(rows, r, 10) or None,
                ngri_v_depo=cell_at(rows, r, 11) or None,
                data_pogasheniya=cell_at(rows, r, 19) or None,
                mos_nz=cell_at(rows, r, 20) or None,
                comment=cell_at(rows, r, 22) or None,
                kadastr=cell_at(rows, r, 23) or None,
                address=cell_at(rows, r, 24) or None,
            )
            if rec.portfolio_no:
                self._by_portfolio[sheet_name][_norm_key(rec.portfolio_no)] = rec
            if rec.ngri_v_depo:
                self._by_ngri[sheet_name][_norm_key(rec.ngri_v_depo)] = rec

    def by_portfolio(self, sheet: str, key: str | None) -> DepoDomRecord | None:
        if not key:
            return None
        return self._by_portfolio.get(sheet, {}).get(_norm_key(key))

    def by_ngri(self, sheet: str, ngri: str | None) -> DepoDomRecord | None:
        if not ngri:
            return None
        return self._by_ngri.get(sheet, {}).get(_norm_key(ngri))
