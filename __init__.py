"""Фаза depo (svod_depo): SQL ↔ Excel для 2_СВОД_поДЕПО.xlsx."""

from sql_upload.depo.pipeline import DepoPipelineResult, run_depo_pipeline
from sql_upload.depo.runner import DepoStepStats, FormUpdateParams, run_depo_step
from sql_upload.depo.steps import DEFAULT_DEPO_PIPELINE_ORDER, DEPO_STEPS

__all__ = [
    "DEFAULT_DEPO_PIPELINE_ORDER",
    "DEPO_STEPS",
    "DepoPipelineResult",
    "DepoStepStats",
    "FormUpdateParams",
    "run_depo_pipeline",
    "run_depo_step",
]
