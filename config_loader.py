"""Загрузка config/upload_paths.yaml (минимальный YAML без внешних зависимостей)."""

from __future__ import annotations

from pathlib import Path

from sql_upload.base import LegacySqlPaths
from sql_upload.depo.steps import DEFAULT_DEPO_PIPELINE_ORDER
from sql_upload.pipeline import (
    DEFAULT_PIPELINE_ORDER,
    DEFAULT_SPRAV_PIPELINE_ORDER,
    DEFAULT_SVOD_PIPELINE_ORDER,
)


def _parse_yaml_sections(text: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    paths_raw: dict[str, str] = {}
    pipelines: dict[str, list[str]] = {}
    section: str | None = None
    pipeline_key: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "paths:":
            section = "paths"
            pipeline_key = None
            continue
        if stripped.startswith("pipeline") and stripped.endswith(":"):
            section = "pipeline"
            pipeline_key = stripped[:-1].strip()
            pipelines.setdefault(pipeline_key, [])
            continue
        if section == "paths" and ":" in stripped:
            key, _, value = stripped.partition(":")
            paths_raw[key.strip()] = value.strip().strip('"').strip("'")
        elif section == "pipeline" and pipeline_key and stripped.startswith("-"):
            pipelines[pipeline_key].append(stripped[1:].strip())

    return paths_raw, pipelines


def load_upload_config(
    config_path: Path,
    project_root: Path,
) -> tuple[LegacySqlPaths, dict[str, list[str]]]:
    paths_raw, pipelines = _parse_yaml_sections(
        config_path.read_text(encoding="utf-8"),
    )

    def resolve(key: str, default: str) -> Path:
        raw = paths_raw.get(key, default)
        p = Path(raw)
        if not p.is_absolute():
            p = project_root / p
        return p

    legacy_paths = LegacySqlPaths(
        gpb=resolve("gpb", "2026_01/GPB"),
        vtb=resolve("vtb", "2026_01/VTBSD"),
        region=resolve("region", "2026_01/REGION"),
        rsd=resolve("rsd", "2026_01/RSD/I"),
        rsd_dop=resolve("rsd_dop", "2026_01/RSD/R01"),
        svod_gpb_workbook=resolve("svod_gpb_workbook", ""),
        svod_vtb_workbook=resolve("svod_vtb_workbook", ""),
        svod_region_workbook=resolve("svod_region_workbook", ""),
        svod_rsd_workbook=resolve("svod_rsd_workbook", ""),
        sprav_workbook=resolve("sprav_workbook", ""),
        svod_depo_workbook=resolve("svod_depo_workbook", ""),
    )

    upload_order = (
        pipelines.get("pipeline_upload")
        or pipelines.get("pipeline")
        or list(DEFAULT_PIPELINE_ORDER)
    )
    sprav_order = pipelines.get("pipeline_sprav") or list(DEFAULT_SPRAV_PIPELINE_ORDER)
    svod_order = pipelines.get("pipeline_svod") or list(DEFAULT_SVOD_PIPELINE_ORDER)
    depo_order = pipelines.get("pipeline_depo") or list(DEFAULT_DEPO_PIPELINE_ORDER)

    pipeline_map = {
        "upload": upload_order,
        "sprav": sprav_order,
        "svod": svod_order,
        "depo": depo_order,
    }
    return legacy_paths, pipeline_map
