# -*- coding: utf-8 -*-
"""Загрузка данных как в ноутбуке 37: concat raw CSV → разбор JSON → df_model39."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

EXCLUDED_RESIST_IDS = [
    25,
    26,
    27,
    29,
    54,
    57,
    61,
    63,
    66,
    68,
    80,
    81,
    82,
    83,
    100,
    101,
    102,
    103,
    104,
    105,
    106,
    109,
    112,
    113,
    115,
    116,
    119,
    120,
    121,
    122,
    123,
    125,
    126,
    129,
    131,
    132,
    134,
    135,
    136,
    137,
    138,
    140,
    141,
    143,
    144,
    146,
    147,
    148,
    149,
    150,
    151,
    152,
    153,
    154,
    156,
    157,
    158,
    162,
    165,
    169,
    170,
    171,
    172,
    173,
    174,
    175,
    176,
    177,
    178,
    179,
    181,
    196,
    139,
]
PREDICT_COMMENT = "first_predict_value_record"


def _to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "t", "1"])


def _to_bool_value(value):
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return None
    return str(value).strip().lower() in ["true", "t", "1"]


def _parse_calculate_param(calc_json: str):
    if pd.isna(calc_json):
        return {}
    try:
        return json.loads(calc_json)
    except Exception:
        return {}


def _flatten_calc_to_dict(calc_obj: dict, prefix: str = "calc_") -> dict:
    out = {}
    for k, v in (calc_obj or {}).items():
        col = f"{prefix}{k}"
        if isinstance(v, dict):
            if "value" in v:
                out[col] = v.get("value")
            else:
                out[col] = json.dumps(v, ensure_ascii=False) if v else ""
        else:
            out[col] = v
    return out


def _coerce_numeric_series(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    mask = out.isna() & series.notna()
    if mask.any():
        fixed = (
            series[mask]
            .astype(str)
            .str.strip()
            .str.replace(",", ".", regex=False)
        )
        out.loc[mask] = pd.to_numeric(fixed, errors="coerce")
    return out


def load_df_model39_from_nb37_raw_files(raw_files: Sequence[Path]) -> pd.DataFrame:
    """Читает существующие файлы из ``raw_files``, concat → ``df_model39`` как в nb37."""
    dfs = []
    for p in raw_files:
        if p.exists():
            dfs.append(pd.read_csv(p, dtype=str, low_memory=False))
    if not dfs:
        paths = ", ".join(str(p) for p in raw_files)
        raise FileNotFoundError(
            "Не найден ни один из файлов данных (nb37 RAW_FILES): "
            f"{paths}. Передайте готовый CSV через --csv или положите raw в data/raw."
        )
    df_all = pd.concat(dfs, ignore_index=True)
    df_all["period"] = pd.to_datetime(df_all["period"], errors="coerce")
    df_all["resist_id"] = pd.to_numeric(df_all["resist_id"], errors="coerce").astype("Int64")

    bool_cols = ["send", "validate_one", "validate_two", "cancel_approve", "forecast"]
    for col in bool_cols:
        if col in df_all.columns:
            df_all[col] = _to_bool(df_all[col])
    df_all["validate_count"] = (
        pd.to_numeric(df_all["validate_count"], errors="coerce").fillna(0).astype(int)
    )
    if "comment" in df_all.columns:
        df_all["comment"] = df_all["comment"].fillna("")
        mask_predict_record = df_all["comment"] == PREDICT_COMMENT
    else:
        mask_predict_record = pd.Series(False, index=df_all.index)

    mask_ok = (
        ~df_all["cancel_approve"]
        & ~mask_predict_record
        & ~df_all["resist_id"].isin(EXCLUDED_RESIST_IDS)
    )
    df_ok = df_all[mask_ok].copy()

    records = []
    for _, row in df_ok.iterrows():
        calc_obj = _parse_calculate_param(row.get("calculate_parameter"))
        calc_flat = _flatten_calc_to_dict(calc_obj)
        op_raw = row.get("operation_parameter")
        if pd.isna(op_raw):
            continue
        try:
            op_data = json.loads(op_raw)
        except Exception:
            continue
        period = row.get("period")
        if pd.isna(period):
            continue
        for op_id, payload in op_data.items():
            if not isinstance(payload, dict):
                continue
            if _to_bool_value(payload.get("operation_active", payload.get("active"))) is False:
                continue
            base_record = {
                "resist_id": row.get("resist_id"),
                "month": int(period.month),
                "year": int(period.year),
                "operation_id": op_id,
                "fact_value": payload.get("fact_value"),
                "fact_predict": payload.get("fact_predict"),
                "workDayMonth_2": calc_flat.get("calc_workDayMonth_2"),
                "calculate_minute": payload.get("calculate_minute"),
            }
            records.append({**base_record, **calc_flat})

    df_model39 = pd.DataFrame(records)
    df_model39["fact_value"] = _coerce_numeric_series(df_model39["fact_value"])
    df_model39["fact_predict"] = _coerce_numeric_series(df_model39["fact_predict"])
    df_model39["workDayMonth_2"] = _coerce_numeric_series(df_model39["workDayMonth_2"])
    df_model39["calculate_minute"] = _coerce_numeric_series(df_model39["calculate_minute"])

    calc_cols = [c for c in df_model39.columns if c.startswith("calc_")]
    for col in calc_cols:
        df_model39[col] = _coerce_numeric_series(df_model39[col])

    df_model39["date"] = pd.to_datetime(
        dict(year=df_model39["year"], month=df_model39["month"], day=1), errors="coerce"
    ).dt.date
    df_model39 = df_model39.dropna(subset=["fact_value"])
    df_model39 = df_model39.sort_values(["operation_id", "year", "month"]).reset_index(drop=True)

    df_model39["operation_id"] = pd.to_numeric(df_model39["operation_id"], errors="coerce")
    df_model39["resist_id"] = pd.to_numeric(df_model39["resist_id"], errors="coerce")
    df_model39 = df_model39.dropna(subset=["operation_id", "resist_id"])

    return df_model39


def describe_missing_raw_paths(raw_files: Iterable[Path]) -> list[Path]:
    """Пути из списка, для которых файла нет (для предупреждения в консоли)."""
    return [p for p in raw_files if not p.exists()]
