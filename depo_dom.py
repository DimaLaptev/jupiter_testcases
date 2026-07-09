"""Загрузка DEPO_DOM.xlsx / DEPO_IA.xlsx / СВОД_поДЕПО (свод за пред. месяц)."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Literal, TextIO

from path_bootstrap import bootstrap

bootstrap()

from sql_upload.excel_grid import cell_at, last_row_in_column, read_workbook_sheets

from models import ALL_PORTFOLIO_SHEETS, DEPO_DOM_SHEETS, DepoDomRecord

SVOD_DATA_START_ROW = 6
PREDSVOD_DATA_START_ROW = 4
_SKIP_SHEETS = frozenset({"Валидация", "Дубли"})
_DEPO_SHEET_MARKERS = frozenset(
    {"GPB", "REGION", "VTBSD", "RSD_XLS", "RSD_MSG"},
)

_GPB_MSG_RE = re.compile(r"^R_102_.*\.MSG$", re.IGNORECASE)
_RSD_MSG_RE = re.compile(r"^R_.*\.MSG$", re.IGNORECASE)
_VL_STEM_RE = re.compile(r"^VL[\w]+$", re.IGNORECASE)
_VRSN_LKK_STEM_RE = re.compile(r"^(?:BpCH|ВрСн)_VL([\w]+)_\d+$", re.IGNORECASE)


def _norm_key(s: str | None) -> str:
    return (s or "").strip().casefold()


def _record_from_row(rows: list[list[str]], r: int) -> DepoDomRecord:
    return DepoDomRecord(
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


def _last_data_row(rows: list[list[str]]) -> int:
    """Конец данных: max по A (№ портфеля) и K (НГРИ) — A часто пуста в первом цикле."""
    return max(last_row_in_column(rows, 1), last_row_in_column(rows, 11))


def _rsd_logical_sheet(sheet_names: tuple[str, ...]) -> str:
    if "RSD_MSG" in sheet_names:
        return "RSD_MSG"
    return "RSD_XLS"


def _route_by_istochnik(istochnik: str, rsd_sheet: str) -> str | None:
    name = Path((istochnik or "").strip()).name
    if not name:
        return None
    stem = Path(name).stem
    suffix = Path(name).suffix.lower()

    if _GPB_MSG_RE.match(name):
        return "GPB"
    if _RSD_MSG_RE.match(name):
        return rsd_sheet
    if suffix == ".xml" or _VL_STEM_RE.match(stem) or _VRSN_LKK_STEM_RE.match(stem):
        return "REGION"
    if suffix in (".xls", ".xlsx"):
        folded = name.casefold()
        if "r-05" in folded or "r05" in folded or "выписка" in folded:
            return rsd_sheet
        if "втб" in folded or "vtb" in folded:
            return "VTBSD"
        if _VL_STEM_RE.match(stem) or _VRSN_LKK_STEM_RE.match(stem):
            return "REGION"
    return None


def _route_by_depository(depository: str, rsd_sheet: str) -> str | None:
    folded = _norm_key(depository)
    if not folded:
        return None
    if "гпб" in folded or "gpb" in folded:
        return "GPB"
    if "рсд" in folded or "rsd" in folded:
        return rsd_sheet
    if "регион" in folded or "region" in folded:
        return "REGION"
    if "втб" in folded or "vtb" in folded:
        return "VTBSD"
    return None


def route_svod_row_to_sheet(
    depository: str | None,
    istochnik: str | None,
    sheet_names: tuple[str, ...],
) -> str | None:
    """Логический лист DEPO_* для строки СВОД_поДЕПО (Y, затем C)."""
    rsd_sheet = _rsd_logical_sheet(sheet_names)
    target = _route_by_istochnik(istochnik or "", rsd_sheet)
    if target is None:
        target = _route_by_depository(depository or "", rsd_sheet)
    if target is None:
        return None
    if target not in sheet_names:
        return None
    return target


def detect_prior_layout(sheet_map: dict[str, list[list[str]]]) -> Literal["predsvod", "svod"]:
    """Определить формат книги: листы депозитария vs листы портфеля СВОД."""
    names = {n.strip() for n in sheet_map}
    names_cf = {n.casefold() for n in names}
    portfolio_cf = {p.casefold() for p in ALL_PORTFOLIO_SHEETS}
    depo_cf = {d.casefold() for d in _DEPO_SHEET_MARKERS}
    if names_cf & portfolio_cf:
        return "svod"
    if names_cf & depo_cf:
        return "predsvod"
    return "predsvod"


class DepoDomIndex:
    """Индексы по листам отчёта пред. месяца: by_portfolio[A], by_ngri[K]."""

    def __init__(self) -> None:
        self._by_portfolio: dict[str, dict[str, DepoDomRecord]] = {}
        self._by_ngri: dict[str, dict[str, DepoDomRecord]] = {}

    def ngri_count(self) -> int:
        return sum(len(m) for m in self._by_ngri.values())

    @classmethod
    def load(
        cls,
        path: Path,
        sheet_names: tuple[str, ...] = DEPO_DOM_SHEETS,
        *,
        layout: Literal["predsvod", "svod", "auto"] = "predsvod",
        warn: TextIO | None = None,
    ) -> DepoDomIndex:
        out: TextIO = warn or sys.stderr
        idx = cls()
        for sheet_name in sheet_names:
            idx._by_portfolio[sheet_name] = {}
            idx._by_ngri[sheet_name] = {}

        if not path.is_file():
            out.write(
                f"  предупреждение: файл свода пред. месяца не найден: {path}\n"
                f"    колонки A/B (№ закладной) не будут заполнены из пред. месяца\n",
            )
            return idx

        wb_sheets = read_workbook_sheets(path)
        sheet_map = {name: rows for name, rows in wb_sheets}

        resolved: Literal["predsvod", "svod"]
        if layout == "auto":
            resolved = detect_prior_layout(sheet_map)
        else:
            resolved = layout
            if layout == "predsvod" and detect_prior_layout(sheet_map) == "svod":
                out.write(
                    f"  предупреждение: {path.name} похож на СВОД_поДЕПО "
                    f"(листы портфеля) — переключаю layout=svod. "
                    f"Явно: --prior-from-svod\n",
                )
                resolved = "svod"

        if resolved == "svod":
            idx._load_svod(sheet_map, sheet_names, warn=out)
        else:
            for sheet_name in sheet_names:
                rows = sheet_map.get(sheet_name)
                if not rows:
                    for k, v in sheet_map.items():
                        if k.strip().upper() == sheet_name.upper():
                            rows = v
                            break
                if not rows:
                    continue
                idx._load_sheet(sheet_name, rows, start_row=PREDSVOD_DATA_START_ROW)

        n = idx.ngri_count()
        if n == 0:
            out.write(
                f"  предупреждение: в {path.name} не найдено записей по НГРИ "
                f"(layout={resolved}, листы {', '.join(sheet_names)})\n",
            )
        else:
            out.write(f"  свод пред. месяца {path.name}: {n} НГРИ (layout={resolved})\n")
        return idx

    def _index_record(self, sheet_name: str, rec: DepoDomRecord) -> None:
        if rec.portfolio_no:
            self._by_portfolio[sheet_name][_norm_key(rec.portfolio_no)] = rec
        if rec.ngri_v_depo:
            self._by_ngri[sheet_name][_norm_key(rec.ngri_v_depo)] = rec

    def _load_sheet(
        self,
        sheet_name: str,
        rows: list[list[str]],
        *,
        start_row: int = PREDSVOD_DATA_START_ROW,
    ) -> None:
        last = _last_data_row(rows)
        for r in range(start_row, last + 1):
            rec = _record_from_row(rows, r)
            # пропускаем строку-шапку, если попала в диапазон
            if rec.ngri_v_depo and "нгри" in rec.ngri_v_depo.casefold():
                continue
            if rec.portfolio_no and "номер закладной" in rec.portfolio_no.casefold():
                continue
            self._index_record(sheet_name, rec)

    def _load_svod(
        self,
        sheet_map: dict[str, list[list[str]]],
        sheet_names: tuple[str, ...],
        *,
        warn: TextIO | None = None,
    ) -> None:
        out: TextIO = warn or sys.stderr
        unrouted = 0
        portfolio_names = set(ALL_PORTFOLIO_SHEETS)

        for sheet_name, rows in sheet_map.items():
            name = sheet_name.strip()
            if name in _SKIP_SHEETS:
                continue
            if name not in portfolio_names:
                matched = next(
                    (p for p in portfolio_names if p.casefold() == name.casefold()),
                    None,
                )
                if matched is None:
                    continue

            last = _last_data_row(rows)
            for r in range(SVOD_DATA_START_ROW, last + 1):
                rec = _record_from_row(rows, r)
                if not rec.portfolio_no and not rec.ngri_v_depo:
                    continue
                if rec.ngri_v_depo and "нгри" in rec.ngri_v_depo.casefold():
                    continue
                depository = cell_at(rows, r, 3) or None
                istochnik = cell_at(rows, r, 25) or None
                target = route_svod_row_to_sheet(depository, istochnik, sheet_names)
                if target is None:
                    unrouted += 1
                    continue
                self._index_record(target, rec)

        if unrouted:
            out.write(
                f"  предупреждение: СВОД prior — {unrouted} строк(и) без маршрута "
                f"на листы {', '.join(sheet_names)}\n",
            )

    def by_portfolio(self, sheet: str, key: str | None) -> DepoDomRecord | None:
        if not key:
            return None
        return self._by_portfolio.get(sheet, {}).get(_norm_key(key))

    def by_ngri(self, sheet: str, ngri: str | None) -> DepoDomRecord | None:
        if not ngri:
            return None
        return self._by_ngri.get(sheet, {}).get(_norm_key(ngri))


__all__ = [
    "DepoDomIndex",
    "detect_prior_layout",
    "route_svod_row_to_sheet",
]
