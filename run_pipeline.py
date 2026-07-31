#!/usr/bin/env python3
"""Сборка Day_Quantity.xlsx и Day_Quantity_DOM.xlsx из source/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PIPELINE_ROOT.parent
sys.path.insert(0, str(PIPELINE_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from assemble.builder import build_day_rows
from assemble.route_ord import (
    collect_svod_unknown_accounts,
    route_ord_ops,
    warn_unknown_accounts,
)
from config import load_config
from extract.ord_quantity import iter_ord_op_rows
from extract.svod_depo import iter_svod_depo_rows
from references.spravochnik import Sprav1Lookup
from write.excel_writer import write_day_workbooks


def _default_output_name(report_date: str, *, dom: bool) -> str:
    """2026_05_Day_Quantity.xlsx из report_date ДД.ММ.ГГГГ."""
    parts = (report_date or "").strip().split(".")
    if len(parts) == 3:
        _d, month, year = parts
        stem = f"{year}_{int(month):02d}_Day_Quantity"
    else:
        stem = "Day_Quantity"
    return f"{stem}_DOM.xlsx" if dom else f"{stem}.xlsx"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DAY DEPO pipeline — Day_Quantity")
    parser.add_argument(
        "--pipeline-root",
        type=Path,
        default=PIPELINE_ROOT,
        help="Корень DAY_DEPO_PIPELINE",
    )
    parser.add_argument("--report-date", type=str, default=None)
    parser.add_argument("--ord", type=Path, default=None, dest="ord_path")
    parser.add_argument("--sprav-workbook", type=Path, default=None)
    parser.add_argument("--svod-prev", type=Path, default=None)
    parser.add_argument("--svod-curr", type=Path, default=None)
    parser.add_argument("--svod-dom-prev", type=Path, default=None)
    parser.add_argument("--svod-dom-curr", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--output-dom", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = load_config(args.pipeline_root)
    report_date = args.report_date or cfg.report_date

    ord_path = args.ord_path or cfg.ord_quantity
    sprav_path = args.sprav_workbook or cfg.sprav_workbook
    svod_prev = args.svod_prev or cfg.svod_prev
    svod_curr = args.svod_curr or cfg.svod_curr
    svod_dom_prev = args.svod_dom_prev or cfg.svod_dom_prev
    svod_dom_curr = args.svod_dom_curr or cfg.svod_dom_curr

    out_dir = cfg.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    day_path = args.output or cfg.day_quantity
    day_dom_path = args.output_dom or cfg.day_quantity_dom
    if args.output is None and not day_path.name:
        day_path = out_dir / _default_output_name(report_date, dom=False)
    if args.output_dom is None and not day_dom_path.name:
        day_dom_path = out_dir / _default_output_name(report_date, dom=True)

    print(f"report_date={report_date}")
    print(f"Ord: {ord_path}")
    print(f"Справочник: {sprav_path}")
    print(f"СВОД prev/curr: {svod_prev.name} / {svod_curr.name}")
    print(f"СВОД_ДОМ prev/curr: {svod_dom_prev.name} / {svod_dom_curr.name}")

    sprav = Sprav1Lookup.load(sprav_path)
    if not sprav_path.is_file():
        print(f"WARN: Справочник.xlsx не найден: {sprav_path}", file=sys.stdout)

    ord_ops = iter_ord_op_rows(ord_path, warn=sys.stdout)
    print(f"Ord поручений (фильтр): {len(ord_ops)}")

    routed = route_ord_ops(ord_ops, sprav, source_file=ord_path.name)
    print(f"Ord → IA: {len(routed.ia_ops)}, Ord → DOM: {len(routed.dom_ops)}")

    prev_ia = iter_svod_depo_rows(svod_prev, warn=sys.stdout)
    curr_ia = iter_svod_depo_rows(svod_curr, warn=sys.stdout)
    print(f"СВОД IA: prev={len(prev_ia)}, curr={len(curr_ia)}")

    prev_dom = iter_svod_depo_rows(svod_dom_prev, warn=sys.stdout)
    curr_dom = iter_svod_depo_rows(svod_dom_curr, warn=sys.stdout)
    print(f"СВОД DOM: prev={len(prev_dom)}, curr={len(curr_dom)}")

    unknown = dict(routed.unknown_accounts)
    for rows, path in (
        (prev_ia, svod_prev),
        (curr_ia, svod_curr),
        (prev_dom, svod_dom_prev),
        (curr_dom, svod_dom_curr),
    ):
        # ensure source_file set for warn (iter_svod already sets name)
        collect_svod_unknown_accounts(rows, sprav, into=unknown)
        _ = path
    warn_unknown_accounts(
        unknown,
        out=sys.stdout,
        unknown_sections=routed.unknown_sections,
    )

    depo_fn = sprav.depo_code
    ia_rows = build_day_rows(
        prev_ia, curr_ia, routed.ia_ops, report_date, depo_for_schet=depo_fn
    )
    dom_rows = build_day_rows(
        prev_dom, curr_dom, routed.dom_ops, report_date, depo_for_schet=depo_fn
    )
    print(f"Day_Quantity строк: {len(ia_rows)}")
    print(f"Day_Quantity_DOM строк: {len(dom_rows)}")

    write_day_workbooks(day_path, day_dom_path, ia_rows, dom_rows, report_date)
    print(f"OK: {day_path}")
    print(f"OK: {day_dom_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
