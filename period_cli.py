"""CLI-хелперы для --period-dir в скриптах Ord_Quantity."""

from __future__ import annotations

import argparse
from pathlib import Path

from period_paths import OrdPeriodPaths, classify_and_resolve


def add_period_dir_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--period-dir",
        "--input-dir",
        dest="period_dir",
        type=Path,
        default=None,
        help=(
            "Каталог периода (напр. 2026_05): все входы и книга "
            "{period}/{period}_Ord_Quantity.xlsx; --input-dir — синоним"
        ),
    )


def apply_period_workbook(
    args,
    *,
    project_root: Path,
    workbook_attr: str = "workbook",
) -> OrdPeriodPaths | None:
    period_dir = getattr(args, "period_dir", None)
    if not period_dir:
        return None
    _leaf, pp = classify_and_resolve(period_dir, project_root)
    if pp is None:
        return None
    setattr(args, workbook_attr, pp.workbook)
    return pp
