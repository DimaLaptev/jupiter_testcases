"""Загрузка config/paths.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PipelinePaths:
    pipeline_root: Path
    source_root: Path
    output_dir: Path
    ord_quantity: Path
    svod_prev: Path
    svod_curr: Path
    svod_dom_prev: Path
    svod_dom_curr: Path
    day_quantity: Path
    day_quantity_dom: Path
    report_date: str = "31.05.2026"


def _parse_simple_yaml(text: str) -> tuple[dict[str, str], str]:
    paths: dict[str, str] = {}
    report_date = "31.05.2026"
    section: str | None = None

    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("report_date:"):
            report_date = s.split(":", 1)[1].strip().strip('"').strip("'")
            continue
        if s == "paths:":
            section = "paths"
            continue
        if section == "paths" and ":" in s:
            k, _, v = s.partition(":")
            paths[k.strip()] = v.strip().strip('"').strip("'")

    return paths, report_date


def load_config(pipeline_root: Path) -> PipelinePaths:
    cfg_path = pipeline_root / "config" / "paths.yaml"
    paths_raw, report_date = _parse_simple_yaml(cfg_path.read_text(encoding="utf-8"))

    def resolve(key: str, default: str) -> Path:
        raw = paths_raw.get(key, default)
        p = Path(raw)
        if not p.is_absolute():
            p = pipeline_root / p
        return p

    return PipelinePaths(
        pipeline_root=pipeline_root,
        source_root=resolve("source_root", "source"),
        output_dir=resolve("output_dir", "output"),
        ord_quantity=resolve("ord_quantity", "source/2026_05_Ord_Quantity.xlsx"),
        svod_prev=resolve("svod_prev", "source/СВОД_поДЕПО_апрель.xlsx"),
        svod_curr=resolve("svod_curr", "source/СВОД_поДЕПО_май.xlsx"),
        svod_dom_prev=resolve("svod_dom_prev", "source/СВОД_поДЕПО_ДОМ_апрель.xlsx"),
        svod_dom_curr=resolve("svod_dom_curr", "source/СВОД_поДЕПО_ДОМ_май.xlsx"),
        day_quantity=resolve("day_quantity", "output/2026_05_Day_Quantity.xlsx"),
        day_quantity_dom=resolve("day_quantity_dom", "output/2026_05_Day_Quantity_DOM.xlsx"),
        report_date=report_date,
    )
