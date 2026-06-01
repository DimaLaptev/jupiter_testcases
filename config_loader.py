"""Загрузка config/upload_paths.yaml (минимальный YAML без внешних зависимостей)."""

from __future__ import annotations

from pathlib import Path

from sql_upload.base import UploadPaths
from sql_upload.pipeline import DEFAULT_PIPELINE_ORDER


def load_upload_config(
    config_path: Path,
    project_root: Path,
) -> tuple[UploadPaths, list[str]]:
    paths_raw: dict[str, str] = {}
    pipeline: list[str] = []
    section: str | None = None

    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "paths:":
            section = "paths"
            continue
        if stripped == "pipeline:":
            section = "pipeline"
            continue
        if section == "paths" and ":" in stripped:
            key, _, value = stripped.partition(":")
            paths_raw[key.strip()] = value.strip().strip('"').strip("'")
        elif section == "pipeline" and stripped.startswith("-"):
            pipeline.append(stripped[1:].strip())

    def resolve(key: str, default: str) -> Path:
        raw = paths_raw.get(key, default)
        p = Path(raw)
        if not p.is_absolute():
            p = project_root / p
        return p

    upload_paths = UploadPaths(
        gpb=resolve("gpb", "2026_01/GPB"),
        vtb=resolve("vtb", "2026_01/VTBSD"),
        region=resolve("region", "2026_01/REGION"),
        rsd=resolve("rsd", "2026_01/RSD/I"),
        rsd_dop=resolve("rsd_dop", "2026_01/RSD/R01"),
    )
    if not pipeline:
        pipeline = list(DEFAULT_PIPELINE_ORDER)
    return upload_paths, pipeline
