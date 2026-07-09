"""Стандартные пути каталога периода Ord_Quantity (2026_05, …)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PERIOD_NAME_RE = re.compile(r"^(\d{4})_(\d{1,2})$")


@dataclass(frozen=True)
class OrdPeriodPaths:
    period_dir: Path
    workbook: Path
    gpb_i: Path
    gpb_d: Path
    gpb_rep: Path
    gpb_spr: Path
    rsd_i: Path
    rsd_rep: Path
    region_rep: Path
    region_spr: Path
    vtb_xml: Path
    vtb_zip: Path
    year: int | None
    month: int | None


def parse_period_year_month(period_name: str) -> tuple[int | None, int | None]:
    m = _PERIOD_NAME_RE.match(period_name.strip())
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def resolve_period_dir(period_dir: Path, project_root: Path | None = None) -> OrdPeriodPaths:
    """Каталог периода → пути входов и `{period}/{period}_Ord_Quantity.xlsx`."""
    root = project_root or Path(__file__).resolve().parent.parent
    period = Path(period_dir)
    if not period.is_absolute():
        period = root / period
    period = period.resolve()
    name = period.name
    year, month = parse_period_year_month(name)
    return OrdPeriodPaths(
        period_dir=period,
        workbook=period / f"{name}_Ord_Quantity.xlsx",
        gpb_i=period / "GPB" / "I",
        gpb_d=period / "GPB" / "D",
        gpb_rep=period / "GPB" / "REP",
        gpb_spr=period / "GPB" / "SPR",
        rsd_i=period / "RSD" / "I",
        rsd_rep=period / "RSD" / "REP",
        region_rep=period / "REGION" / "REP",
        region_spr=period / "REGION" / "SPR",
        vtb_xml=period / "VTBSD" / "REP" / "XML",
        vtb_zip=period / "VTBSD" / "REP" / "XML_приложения",
        year=year,
        month=month,
    )


def classify_and_resolve(
    path: Path | None,
    project_root: Path | None = None,
    *,
    leaf: str | None = None,
) -> tuple[Path | None, OrdPeriodPaths | None]:
    """
    Если path — корень периода (2026_05 или есть подкаталог GPB), вернуть путь leaf.
    Иначе path — уже конкретный каталог данных (legacy …/GPB/D).
    """
    if path is None:
        return None, None
    root = project_root or Path(__file__).resolve().parent.parent
    p = path if path.is_absolute() else root / path
    p = p.resolve()
    is_period = bool(_PERIOD_NAME_RE.match(p.name)) or (p / "GPB").is_dir()
    if is_period:
        pp = resolve_period_dir(p, root)
        if leaf:
            return getattr(pp, leaf), pp
        return pp.period_dir, pp
    return p, None


def try_resolve_from_workbook(workbook: Path, project_root: Path | None = None) -> OrdPeriodPaths | None:
    """Если книга `{period}/{period}_Ord_Quantity.xlsx` — вернуть пути периода."""
    wb = Path(workbook).resolve()
    parent = wb.parent
    if wb.name.casefold() == f"{parent.name}_Ord_Quantity.xlsx".casefold():
        return resolve_period_dir(parent, project_root)
    return None

