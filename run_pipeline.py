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
from extract.rsd_msg import iter_rsd_msg_rows
from extract.rsd_r05 import iter_rsd_r05_rows
from extract.vtb import iter_vtb_rows
from references.depo_dom import DepoDomIndex
from references.spravochnik import Sprav1Lookup, Sprav2Lookup
from unpack import prepare_staging
from write.excel_writer import write_svod_workbooks


def collect_do_rows(cfg, staging: Path) -> list:
    rows = []
    rows.extend(iter_gpb_rows(cfg.gpb))
    rows.extend(iter_rsd_msg_rows(cfg.rsd_msg))
    rows.extend(iter_rsd_r05_rows(staging / "RSD_EXL"))
    rows.extend(iter_rsd_r05_rows(cfg.rsd_exl))
    region_root = staging / "REGION" if (staging / "REGION").is_dir() else cfg.region
    rows.extend(iter_region_rows(region_root, cfg.region_exclude_accounts))
    vtbsd_root = staging / "VTBSD" if (staging / "VTBSD").is_dir() else cfg.vtbsd
    rows.extend(iter_vtb_rows(vtbsd_root))
    return rows


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
    args = parser.parse_args(argv)

    cfg = load_config(args.pipeline_root)
    report_date = args.report_date or cfg.report_date
    svod_path = args.output or cfg.svod_workbook
    svod_dom_path = args.output_dom or cfg.svod_dom_workbook

    staging = prepare_staging([cfg.region, cfg.rsd_exl], cfg.staging)

    depo_dom = DepoDomIndex.load(cfg.depo_dom)
    sprav1 = Sprav1Lookup.load(cfg.sprav_workbook)
    sprav2 = Sprav2Lookup.load(cfg.sprav_workbook)

    do_rows = collect_do_rows(cfg, staging)
    rows_by_sheet = build_all_rows(do_rows, depo_dom, sprav1, sprav2)

    template = cfg.template_workbook if cfg.template_workbook.is_file() else None
    template_dom = cfg.template_dom_workbook if cfg.template_dom_workbook.is_file() else None
    write_svod_workbooks(
        svod_path,
        svod_dom_path,
        rows_by_sheet,
        report_date,
        template,
        template_dom,
    )

    total = sum(len(v) for v in rows_by_sheet.values())
    for name, rows in rows_by_sheet.items():
        print(f"  {name}: {len(rows)} строк")
    print(f"Итого: {total} строк -> {svod_path}, {svod_dom_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
