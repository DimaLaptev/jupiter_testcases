"""Сборка SvodRow из DepoReportRow + справочники + DEPO_DOM."""

from __future__ import annotations

import sys
from typing import TextIO

from date_format import format_date_ddmmyyyy
from models import (
    ALL_PORTFOLIO_SHEETS,
    SOURCE_TO_DEPO_DOM_SHEET,
    DepoReportRow,
    SourceKind,
    SvodRow,
)
from references.depo_dom import DepoDomIndex
from references.spravochnik import Sprav1Lookup, Sprav2Lookup
from references.vtb_codifier import lookup_vtb_section

from assemble.source_matrix import (
    data_priema_from_do,
    fio_from_do,
    kd_from_do,
    status_constant,
    status_from_do,
    use_depo_dom_portfolio,
    use_vtb_codifier,
)


def _apply_depo_dom(svod: SvodRow, dom, *, fill_kd: bool) -> None:
    if dom is None:
        return
    if dom.portfolio_no:
        svod.n_zakladnoy_portfel = dom.portfolio_no
    if dom.dom_no:
        svod.n_zakladnoy_dom = dom.dom_no
    if dom.fio:
        svod.fio = dom.fio
    if fill_kd and dom.nomer_kd:
        svod.nomer_kd = dom.nomer_kd
    if dom.data_pogasheniya:
        svod.data_pogasheniya = format_date_ddmmyyyy(dom.data_pogasheniya)
    if dom.mos_nz:
        svod.mos_nz = dom.mos_nz
    if dom.comment:
        svod.comment = dom.comment
    if dom.kadastr:
        svod.kadastr = dom.kadastr
    if dom.address:
        svod.address = dom.address


def build_svod_row(
    do: DepoReportRow,
    depo_dom: DepoDomIndex,
    sprav1: Sprav1Lookup,
    sprav2: Sprav2Lookup,
) -> SvodRow:
    depo_dom_sheet = SOURCE_TO_DEPO_DOM_SHEET[do.source_kind].value
    svod = SvodRow(
        schet_depo=do.schet_depo or None,
        razdel_scheta=do.razdel_scheta or None,
        ngri_v_depo=do.ngri_v_depo or None,
        quantity="1",
        istochnik=do.source_file,
    )

    spr = sprav1.get(do.schet_depo)
    if spr:
        svod.depository = spr.depository
        svod.owner = spr.owner
        svod.servisny_agent = spr.servisny_agent
        svod.sdelka_ia = spr.sdelka_ia
        if not use_vtb_codifier(do.source_kind):
            svod.enc = spr.enc
            svod.vid_ucheta = spr.vid_ucheta

    fill_kd_from_dom = use_depo_dom_portfolio(do.source_kind) and not kd_from_do(do.source_kind)
    if use_depo_dom_portfolio(do.source_kind):
        dom = depo_dom.by_ngri(depo_dom_sheet, do.ngri_v_depo)
        if dom:
            _apply_depo_dom(svod, dom, fill_kd=fill_kd_from_dom)

    if fio_from_do(do.source_kind) and do.fio:
        svod.fio = do.fio

    if kd_from_do(do.source_kind) and do.nomer_kd:
        svod.nomer_kd = do.nomer_kd

    if data_priema_from_do(do.source_kind) and do.data_priema:
        svod.data_priema = format_date_ddmmyyyy(do.data_priema)

    const_status = status_constant(do.source_kind)
    if const_status:
        svod.sostoyanie = const_status
    elif status_from_do(do.source_kind) and do.status:
        svod.sostoyanie = do.status

    if use_vtb_codifier(do.source_kind):
        cod = lookup_vtb_section(do.section_text)
        svod.sostoyanie = cod.sostoyanie
        svod.enc = cod.enc
        svod.vid_ucheta = cod.vid_ucheta

    if do.source_kind == SourceKind.REGION:
        city = sprav2.get_by_depository_substring("регион", "дк регион")
    elif do.source_kind == SourceKind.VTBSD:
        city = sprav2.get_by_depository_substring("втб")
    else:
        city = sprav2.get(svod.razdel_scheta)
    if city:
        svod.gorod_hraneniya = city

    if svod.depository and svod.schet_depo:
        svod.mestonahozhdenie = f"{svod.depository}_{svod.schet_depo}"

    return svod


def build_all_rows(
    do_rows: list[DepoReportRow],
    depo_dom: DepoDomIndex,
    sprav1: Sprav1Lookup,
    sprav2: Sprav2Lookup,
    *,
    warn: TextIO | None = None,
) -> dict[str, list[SvodRow]]:
    out: TextIO = warn or sys.stdout
    by_sheet: dict[str, list[SvodRow]] = {name: [] for name in ALL_PORTFOLIO_SHEETS}
    skipped = 0
    for do in do_rows:
        portfolio = sprav1.portfolio_section(do.schet_depo)
        if not portfolio or portfolio not in by_sheet:
            skipped += 1
            out.write(
                f"  предупреждение: пропуск строки — нет «Раздел КП для Свода депо» "
                f"для счёта {do.schet_depo!r} (НГРИ {do.ngri_v_depo})\n",
            )
            continue
        by_sheet[portfolio].append(
            build_svod_row(do, depo_dom, sprav1, sprav2),
        )
    if skipped:
        out.write(f"  пропущено строк без маршрутизации: {skipped}\n")
    return by_sheet
