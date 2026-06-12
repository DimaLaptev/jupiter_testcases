"""Загрузка config/paths.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PipelinePaths:
    pipeline_root: Path
    source_root: Path
    output_dir: Path
    depo_dom: Path
    sprav_workbook: Path
    template_workbook: Path
    gpb: Path
    rsd_msg: Path
    rsd_exl: Path
    region: Path
    vtbsd: Path
    staging: Path
    report_date: str = "31.03.2026"
    region_exclude_accounts: list[str] = field(default_factory=list)
    depository_aliases: dict[str, str] = field(default_factory=dict)


def _parse_simple_yaml(text: str) -> tuple[dict[str, str], list[str], dict[str, str], str]:
    paths: dict[str, str] = {}
    exclude: list[str] = []
    aliases: dict[str, str] = {}
    report_date = "31.03.2026"
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
        if s == "region_exclude_accounts:":
            section = "exclude"
            continue
        if s == "depository_aliases:":
            section = "aliases"
            continue
        if section == "paths" and ":" in s:
            k, _, v = s.partition(":")
            paths[k.strip()] = v.strip().strip('"').strip("'")
        elif section == "exclude" and s.startswith("-"):
            exclude.append(s[1:].strip().strip('"').strip("'"))
        elif section == "aliases" and ":" in s:
            k, _, v = s.partition(":")
            aliases[k.strip().strip('"').strip("'")] = v.strip().strip('"').strip("'")

    return paths, exclude, aliases, report_date


def load_config(pipeline_root: Path) -> PipelinePaths:
    cfg_path = pipeline_root / "config" / "paths.yaml"
    paths_raw, exclude, aliases, report_date = _parse_simple_yaml(
        cfg_path.read_text(encoding="utf-8"),
    )

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
        depo_dom=resolve("depo_dom", "source/DEPO_DOM.xlsx"),
        sprav_workbook=resolve("sprav_workbook", "source/SPRAV/Справочник.xlsx"),
        template_workbook=resolve("template_workbook", "source/2_СВОД_поДЕПО.xlsx"),
        gpb=resolve("gpb", "source/GPB"),
        rsd_msg=resolve("rsd_msg", "source/RSD_MSG"),
        rsd_exl=resolve("rsd_exl", "source/RSD_EXL"),
        region=resolve("region", "source/REGION"),
        vtbsd=resolve("vtbsd", "source/VTBSD"),
        staging=resolve("staging", "source/_staging"),
        report_date=report_date,
        region_exclude_accounts=exclude,
        depository_aliases=aliases,
    )
