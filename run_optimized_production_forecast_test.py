# -*- coding: utf-8 -*-
"""Запуск optimized production-прогноза из raw CSV для одного resist_id.

Аналог ``run_production_forecast_test.py``, но фасад и конфиги из
``optimized_predict_operation_count_v2`` / ``optimized_tsa_per_series_nb37_trainers``.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from scripts.nb37_raw_model39_load import (  # noqa: E402
    EXCLUDED_RESIST_IDS,
    load_df_model39_from_nb37_raw_files,
)
from scripts.test_optimized_predict_operation_count_v2 import (  # noqa: E402
    CsvHistoryRepository,
    HISTORY_START_DATE,
    PredictOparationCountV2,
)

RAW_DIR = _ROOT / "data" / "raw"
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]


def _coerce_operation_id(value: object) -> object:
    try:
        x = float(value)
        return int(x) if x == int(x) else x
    except (TypeError, ValueError):
        return value


def default_operations_for_resist(df: pd.DataFrame, resist_id: int) -> list:
    """Те же границы дат, что ``CsvHistoryRepository.fetch``."""
    now_period = (datetime.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    sub = df.loc[df["resist_id"] == resist_id].copy()
    if sub.empty:
        return []
    sub["_ts"] = pd.to_datetime(sub["date"], errors="coerce")
    sub = sub.dropna(subset=["_ts"])
    start_bound = pd.Timestamp(HISTORY_START_DATE)
    end_bound = pd.Timestamp(now_period)
    sub = sub.loc[(sub["_ts"] > start_bound) & (sub["_ts"] < end_bound)]
    raw = sub["operation_id"].dropna().unique().tolist()
    out = sorted({_coerce_operation_id(x) for x in raw}, key=lambda z: (str(type(z)), str(z)))
    return list(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Локальный optimized прогноз как PredictOparationCountV2.predict из CSV (nb37 raw).",
    )
    parser.add_argument("resist_id", type=int, help="Идентификатор модели нагрузки (resist_id).")
    parser.add_argument(
        "--operations",
        default=None,
        help="Список operation_id через запятую; по умолчанию все из CSV в окне дат.",
    )
    args = parser.parse_args()
    rid = args.resist_id

    if rid in EXCLUDED_RESIST_IDS:
        print(
            f"Предупреждение (warning): resist_id={rid} в EXCLUDED_RESIST_IDS loader — "
            "в выборке nb37 этого resist не будет.",
            file=sys.stderr,
        )

    for p in RAW_FILES:
        if not p.exists():
            print(f"Предупреждение (warning): нет файла {p}", file=sys.stderr)

    df = load_df_model39_from_nb37_raw_files(RAW_FILES)

    if args.operations:
        operations: list = []
        for part in args.operations.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                operations.append(int(part))
            except ValueError:
                operations.append(part)
    else:
        operations = default_operations_for_resist(df, rid)

    if not operations:
        print(
            "Нет operation_id для прогноза (пустой список после фильтра).",
            file=sys.stderr,
        )
        print(json.dumps({}, ensure_ascii=False, indent=2))
        return

    repo = CsvHistoryRepository(df)
    predictor = PredictOparationCountV2(repository=repo)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = predictor.predict(operations, str(rid))

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
