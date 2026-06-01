"""Оркестратор legacy ETL (порядок шагов как VBA)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sql_upload.base import UploadPaths, UploadStats
from sql_upload.db_backend import SqliteBackend
from sql_upload.post_process import run_post_process
from sql_upload.registry import LOADER_REGISTRY, get_loader
from sql_upload.runner import run_loader

import sql_upload.loaders  # noqa: F401 — регистрация загрузчиков

DEFAULT_PIPELINE_ORDER = ["gpb", "region2", "vtb", "rsd", "rsd_dop"]


@dataclass
class PipelineResult:
    steps: list[UploadStats] = field(default_factory=list)
    post_process: dict[str, int] | None = None


def run_pipeline(
    backend: SqliteBackend,
    paths: UploadPaths,
    steps: list[str] | None = None,
    *,
    skip_post_process: bool = False,
) -> PipelineResult:
    order = steps or DEFAULT_PIPELINE_ORDER
    result = PipelineResult()
    run_post = False

    for step_name in order:
        loader = get_loader(step_name)
        cfg = loader.loader_config()
        input_dir = paths.dir_for(step_name)
        stats = run_loader(loader, backend, input_dir)
        result.steps.append(stats)
        if cfg.run_post_process:
            run_post = True

    if run_post and not skip_post_process:
        result.post_process = run_post_process(backend.conn)

    return result
