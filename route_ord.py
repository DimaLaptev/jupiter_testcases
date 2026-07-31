"""Маршрутизация поручений Ord в Day IA / Day DOM по Справочник.xlsx."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TextIO

from models import OrdOpRow, SvodDepoRow
from references.spravochnik import Sprav1Lookup


@dataclass
class OrdRouteResult:
    ia_ops: list[OrdOpRow]
    dom_ops: list[OrdOpRow]
    unknown_accounts: dict[str, set[str]]  # display account → source file names
    unknown_sections: dict[str, set[str]]  # section → accounts


def route_ord_ops(
    ops: list[OrdOpRow],
    sprav: Sprav1Lookup,
    *,
    source_file: str,
) -> OrdRouteResult:
    """Разделить Ord по разделу КП; неизвестные счета не попадают никуда."""
    ia_ops: list[OrdOpRow] = []
    dom_ops: list[OrdOpRow] = []
    unknown_accounts: dict[str, set[str]] = defaultdict(set)
    unknown_sections: dict[str, set[str]] = defaultdict(set)

    for op in ops:
        target = sprav.workbook_target(op.schet_depo)
        if target is None:
            rec = sprav.get(op.schet_depo)
            if rec is None:
                display = (op.schet_depo or "").strip() or "(пусто)"
                unknown_accounts[display].add(source_file)
            else:
                section = rec.portfolio_section or "(пусто)"
                unknown_sections[section].add(op.schet_depo.strip())
                unknown_accounts[op.schet_depo.strip()].add(source_file)
            continue
        if target == "ia":
            ia_ops.append(op)
        else:
            dom_ops.append(op)

    return OrdRouteResult(
        ia_ops=ia_ops,
        dom_ops=dom_ops,
        unknown_accounts=dict(unknown_accounts),
        unknown_sections=dict(unknown_sections),
    )


def collect_svod_unknown_accounts(
    rows: list[SvodDepoRow],
    sprav: Sprav1Lookup,
    *,
    into: dict[str, set[str]] | None = None,
) -> dict[str, set[str]]:
    """Дополнить unknown-список счетами из СВОД, отсутствующими в справочнике."""
    out = into if into is not None else {}
    for row in rows:
        if not row.schet_depo or not row.schet_depo.strip():
            continue
        if sprav.get(row.schet_depo) is not None:
            continue
        display = row.schet_depo.strip()
        files = out.setdefault(display, set())
        if row.source_file:
            files.add(row.source_file)
        else:
            files.add("(СВОД)")
    return out


def warn_unknown_accounts(
    unknown: dict[str, set[str]],
    *,
    out: TextIO,
    unknown_sections: dict[str, set[str]] | None = None,
) -> None:
    if unknown:
        print("WARN: счета не найдены в Справочник.xlsx:", file=out)
        for acc in sorted(unknown.keys(), key=lambda s: s.casefold()):
            files = ", ".join(sorted(unknown[acc]))
            print(f"  {acc} — файлы: {files}", file=out)
    if unknown_sections:
        print("WARN: неопознанный раздел КП в Справочнике:", file=out)
        for section, accounts in sorted(unknown_sections.items(), key=lambda x: x[0].casefold()):
            accs = ", ".join(sorted(accounts, key=lambda s: s.casefold()))
            print(f"  {section!r} — счета: {accs}", file=out)
