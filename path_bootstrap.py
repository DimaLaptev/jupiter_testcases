"""Добавление корня репозитория в sys.path для import sql_upload и др."""

from __future__ import annotations

import sys
from pathlib import Path


def bootstrap(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parents[2]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    pipeline_src = root / "SVOD_DEPO_PIPELINE" / "src"
    if pipeline_src.is_dir() and str(pipeline_src) not in sys.path:
        sys.path.insert(0, str(pipeline_src))
    return root
