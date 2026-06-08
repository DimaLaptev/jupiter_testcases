"""Оркестратор фазы depo."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sql_upload.depo.runner import DepoStepStats, FormUpdateParams, run_depo_step
from sql_upload.depo.steps import DEFAULT_DEPO_PIPELINE_ORDER


@dataclass
class DepoPipelineResult:
    steps: list[DepoStepStats] = field(default_factory=list)


def run_depo_pipeline(
    conn,
    workbook_path: Path,
    steps: list[str] | None = None,
    *,
    form_params: FormUpdateParams | None = None,
    archived_at: str | None = None,
) -> DepoPipelineResult:
    order = steps or DEFAULT_DEPO_PIPELINE_ORDER
    result = DepoPipelineResult()
    for step_name in order:
        stats = run_depo_step(
            conn,
            step_name,
            workbook_path,
            form_params=form_params,
            archived_at=archived_at,
        )
        result.steps.append(stats)
    return result
