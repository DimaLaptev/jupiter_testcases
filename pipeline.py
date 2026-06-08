"""Оркестратор legacy ETL (порядок шагов как VBA)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sql_upload.base import LegacySqlPaths, UploadStats, is_workbook_loader
from sql_upload.db_backend import SqliteBackend
from sql_upload.post_process import run_post_process
from sql_upload.registry import get_loader
from sql_upload.runner import run_loader, run_workbook_loader

DEFAULT_PIPELINE_ORDER = ["gpb", "region2", "vtb", "rsd", "rsd_dop"]
DEFAULT_SVOD_PIPELINE_ORDER = ["svod_gpb", "svod_vtb", "svod_region", "svod_rsd"]
DEFAULT_SPRAV_PIPELINE_ORDER = ["spravochnik_1", "spravochnik_2"]

from sql_upload.depo.steps import DEFAULT_DEPO_PIPELINE_ORDER  # noqa: E402


@dataclass
class PipelineResult:
    steps: list[UploadStats] = field(default_factory=list)
    post_process: dict[str, int] | None = None
    depo_steps: list = field(default_factory=list)


def _run_steps(
    backend: SqliteBackend,
    paths: LegacySqlPaths,
    order: list[str],
) -> tuple[list[UploadStats], bool]:
    from sql_upload.loaders import register_all_loaders

    register_all_loaders()

    stats_list: list[UploadStats] = []
    run_post = False

    for step_name in order:
        loader = get_loader(step_name)
        cfg = loader.loader_config()
        if is_workbook_loader(step_name):
            wb_path = paths.workbook_for(step_name)
            stats = run_workbook_loader(loader, backend, wb_path)
        else:
            input_dir = paths.dir_for(step_name)
            stats = run_loader(loader, backend, input_dir)
        stats_list.append(stats)
        if cfg.run_post_process:
            run_post = True

    return stats_list, run_post


def run_pipeline(
    backend: SqliteBackend,
    paths: LegacySqlPaths,
    steps: list[str] | None = None,
    *,
    skip_post_process: bool = False,
) -> PipelineResult:
    """Upload-фаза (каталоги → *_temp)."""
    order = steps or DEFAULT_PIPELINE_ORDER
    result = PipelineResult()
    result.steps, run_post = _run_steps(backend, paths, order)
    if run_post and not skip_post_process:
        result.post_process = run_post_process(backend.conn)
    return result


def run_svod_pipeline(
    backend: SqliteBackend,
    paths: LegacySqlPaths,
    steps: list[str] | None = None,
) -> PipelineResult:
    order = steps or DEFAULT_SVOD_PIPELINE_ORDER
    result = PipelineResult()
    result.steps, _ = _run_steps(backend, paths, order)
    return result


def run_depo_pipeline(
    backend: SqliteBackend,
    paths: LegacySqlPaths,
    steps: list[str] | None = None,
    *,
    form_params=None,
    archived_at: str | None = None,
):
    from sql_upload.depo.pipeline import run_depo_pipeline as _run_depo

    order = steps or DEFAULT_DEPO_PIPELINE_ORDER
    return _run_depo(
        backend.conn,
        paths.svod_depo_workbook,
        order,
        form_params=form_params,
        archived_at=archived_at,
    )


def run_sprav_pipeline(
    backend: SqliteBackend,
    paths: LegacySqlPaths,
    steps: list[str] | None = None,
) -> PipelineResult:
    order = steps or DEFAULT_SPRAV_PIPELINE_ORDER
    result = PipelineResult()
    result.steps, _ = _run_steps(backend, paths, order)
    return result


def run_full_legacy_sql(
    backend: SqliteBackend,
    paths: LegacySqlPaths,
    *,
    upload_steps: list[str] | None = None,
    sprav_steps: list[str] | None = None,
    svod_steps: list[str] | None = None,
    skip_post_process: bool = False,
    skip_sprav: bool = False,
    skip_svod: bool = False,
    skip_depo: bool = False,
    depo_steps: list[str] | None = None,
    archived_at: str | None = None,
) -> PipelineResult:
    combined = PipelineResult()
    upload_result = run_pipeline(
        backend,
        paths,
        upload_steps,
        skip_post_process=skip_post_process,
    )
    combined.steps.extend(upload_result.steps)
    combined.post_process = upload_result.post_process

    if not skip_sprav:
        sprav_result = run_sprav_pipeline(backend, paths, sprav_steps)
        combined.steps.extend(sprav_result.steps)

    if not skip_svod:
        svod_result = run_svod_pipeline(backend, paths, svod_steps)
        combined.steps.extend(svod_result.steps)

    if not skip_depo:
        depo_result = run_depo_pipeline(
            backend,
            paths,
            depo_steps,
            archived_at=archived_at,
        )
        combined.depo_steps = depo_result.steps

    return combined
