#!/usr/bin/env python3
"""Сборка СВОД_поДЕПО.xlsx и СВОД_поДЕПО_ДОМ.xlsx из source/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PIPELINE_ROOT.parent
sys.path.insert(0, str(PIPELINE_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from assemble.builder import build_all_rows
from config import load_config
from extract.gpb_r_msg import iter_gpb_rows
from extract.region import iter_region_rows
from extract.rsd_dedupe import dedupe_rsd_do_rows
from extract.rsd_msg import iter_rsd_msg_rows
from extract.rsd_r05 import iter_rsd_r05_rows
from extract.vtb import iter_vtb_rows
from models import DEPO_DOM_SHEETS, DEPO_IA_SHEETS, SVOD_DOM_SHEETS, SVOD_IA_SHEETS
from references.depo_dom import DepoDomIndex
from references.spravochnik import Sprav1Lookup, Sprav2Lookup
from unpack import prepare_staging
from validate.accounts import count_zero_accounts, build_validation_rows
from write.excel_writer import write_svod_workbooks


def collect_do_rows(cfg, staging: Path, *, warn=None) -> list:
    rows = []
    rows.extend(iter_gpb_rows(cfg.gpb))
    rows.extend(iter_rsd_msg_rows(cfg.rsd_msg))
    rsd_exl_root = staging / "RSD_EXL"
    if not rsd_exl_root.is_dir():
        rsd_exl_root = cfg.rsd_exl
    rows.extend(iter_rsd_r05_rows(rsd_exl_root))
    region_root = staging / "REGION" if (staging / "REGION").is_dir() else cfg.region
    rows.extend(iter_region_rows(region_root, cfg.region_exclude_accounts, warn=warn))
    vtbsd_root = staging / "VTBSD" if (staging / "VTBSD").is_dir() else cfg.vtbsd
    rows.extend(iter_vtb_rows(vtbsd_root))
    return dedupe_rsd_do_rows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SVOD DEPO pipeline")
    parser.add_argument(
        "--pipeline-root",
        type=Path,
        default=PIPELINE_ROOT,
        help="Корень SVOD_DEPO_PIPELINE",
    )
    parser.add_argument("--report-date", type=str, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Путь к СВОД_поДЕПО.xlsx (основной файл)",
    )
    parser.add_argument(
        "--output-dom",
        type=Path,
        default=None,
        help="Путь к СВОД_поДЕПО_ДОМ.xlsx",
    )
    parser.add_argument(
        "--prior-from-svod",
        action="store_true",
        help=(
            "Читать свод предыдущего месяца в формате СВОД_поДЕПО "
            "(листы портфеля, данные с строки 6) вместо DEPO_IA/DEPO_DOM"
        ),
    )
    parser.add_argument(
        "--depo-ia",
        type=Path,
        default=None,
        help="Путь к своду пред. месяца для ИА (DEPO_IA.xlsx или СВОД_поДЕПО.xlsx)",
    )
    parser.add_argument(
        "--depo-dom",
        type=Path,
        default=None,
        help="Путь к своду пред. месяца для ДОМ (DEPO_DOM.xlsx или СВОД_поДЕПО_ДОМ.xlsx)",
    )
    parser.add_argument(
        "--debug-ngri",
        type=str,
        default=None,
        help=(
            "Диагностика prior-lookup для одной НГРИ: где лежит в depo-ia/depo-dom "
            "и в каком кармане ищем при сборке"
        ),
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.pipeline_root)
    report_date = args.report_date or cfg.report_date
    svod_path = args.output or cfg.svod_workbook
    svod_dom_path = args.output_dom or cfg.svod_dom_workbook
    depo_ia_path = args.depo_ia or cfg.depo_ia
    depo_dom_path = args.depo_dom or cfg.depo_dom
    # auto: predsvod по умолчанию, но книга с листами «ДОМ ИА»… переключится на svod
    prior_layout = "svod" if args.prior_from_svod else "auto"

    staging = prepare_staging([cfg.region, cfg.rsd_exl], cfg.staging)

    sprav1 = Sprav1Lookup.load(cfg.sprav_workbook)

    do_rows = collect_do_rows(cfg, staging, warn=sys.stdout)

    print(f"  свод пред. месяца ИА:  {depo_ia_path}")
    print(f"  свод пред. месяца ДОМ: {depo_dom_path}")
    depo_dom = DepoDomIndex.load(
        depo_dom_path,
        DEPO_DOM_SHEETS,
        layout=prior_layout,
        warn=sys.stdout,
    )
    depo_ia = DepoDomIndex.load(
        depo_ia_path,
        DEPO_IA_SHEETS,
        layout=prior_layout,
        warn=sys.stdout,
    )
    if args.debug_ngri:
        depo_ia.debug_ngri_location("depo-ia (prior)", args.debug_ngri, out=sys.stdout)
        depo_dom.debug_ngri_location("depo-dom (prior)", args.debug_ngri, out=sys.stdout)
    sprav2 = Sprav2Lookup.load(cfg.sprav_workbook)

    rows_by_sheet = build_all_rows(
        do_rows,
        depo_ia,
        depo_dom,
        sprav1,
        sprav2,
        warn=sys.stdout,
        debug_ngri=args.debug_ngri,
    )

    _, _, ia_dups, dom_dups = write_svod_workbooks(
        svod_path,
        svod_dom_path,
        rows_by_sheet,
        report_date,
        sprav1,
    )

    ia_validation = build_validation_rows(sprav1, rows_by_sheet, SVOD_IA_SHEETS)
    dom_validation = build_validation_rows(sprav1, rows_by_sheet, SVOD_DOM_SHEETS)
    ia_zero = count_zero_accounts(ia_validation)
    dom_zero = count_zero_accounts(dom_validation)
    if ia_zero:
        print(f"  Валидация {svod_path.name}: {ia_zero} счёт(ов) с количеством 0 (лист «Валидация»)")
    if dom_zero:
        print(f"  Валидация {svod_dom_path.name}: {dom_zero} счёт(ов) с количеством 0 (лист «Валидация»)")

    if ia_dups.has_any:
        print(f"  предупреждение: дубли в {svod_path.name} — лист «Дубли»:")
        if ia_dups.ngri:
            print(f"    НГРИ в депо ({len(ia_dups.ngri)}): {', '.join(ia_dups.ngri)}")
        if ia_dups.portfolio:
            print(f"    Номер закладной в портфеле ({len(ia_dups.portfolio)}): {', '.join(ia_dups.portfolio)}")
    if dom_dups.has_any:
        print(f"  предупреждение: дубли в {svod_dom_path.name} — лист «Дубли»:")
        if dom_dups.ngri:
            print(f"    НГРИ в депо ({len(dom_dups.ngri)}): {', '.join(dom_dups.ngri)}")
        if dom_dups.portfolio:
            print(f"    Номер закладной в портфеле ({len(dom_dups.portfolio)}): {', '.join(dom_dups.portfolio)}")

    total = sum(len(v) for v in rows_by_sheet.values())
    for name, rows in rows_by_sheet.items():
        print(f"  {name}: {len(rows)} строк")
    print(f"Итого: {total} строк -> {svod_path}, {svod_dom_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
