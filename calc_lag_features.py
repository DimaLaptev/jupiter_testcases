"""
Признаки calc_* через сдвиги по времени: *_lag1 (как период для lag_1), *_lag12 (как для lag_12).
"""

from __future__ import annotations

import pandas as pd

from scripts.calc_history_flatten import scalar_calc_columns


def lag_feature_names(calc_keys: list[str]) -> list[str]:
    out: list[str] = []
    for k in calc_keys:
        out.append(f"{k}_lag1")
        out.append(f"{k}_lag12")
    return out


def calc_lag_columns_for_sets(
    calc_keys: list[str],
    *,
    whitelist: list[str] | None,
) -> tuple[list[str], list[str]]:
    """Имена колонок для наборов B (все ключи) и C (whitelist ключей)."""
    b_names = lag_feature_names(calc_keys)
    if whitelist is None:
        return b_names, b_names
    wl = set(whitelist)
    c_keys = [k for k in calc_keys if k in wl]
    return b_names, lag_feature_names(c_keys)


def add_calc_shift_lag1_lag12(
    df: pd.DataFrame,
    *,
    calc_keys: list[str] | None = None,
    drop_scalar_calc: bool = True,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Для каждого скалярного calc_k добавляет колонки k_lag1 и k_lag12 (groupby operation_id, shift).

    Возвращает (df, имена_новых_колонок, использованные_calc_keys).
    """
    need = {"operation_id", "year", "month"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"df: не хватает колонок {missing}")

    out = df.copy()
    out = out.sort_values(["operation_id", "year", "month"], kind="mergesort").reset_index(
        drop=True
    )

    if calc_keys is None:
        calc_keys = scalar_calc_columns(out)
    else:
        calc_keys = [c for c in calc_keys if c in out.columns]

    if not calc_keys:
        return out, [], []

    g = out.groupby("operation_id", sort=False)
    new_names: list[str] = []
    for k in calc_keys:
        c1 = f"{k}_lag1"
        c12 = f"{k}_lag12"
        out[c1] = g[k].shift(1)
        out[c12] = g[k].shift(12)
        new_names.extend([c1, c12])

    for col in new_names:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    if drop_scalar_calc:
        to_drop = [c for c in calc_keys if c in out.columns]
        out = out.drop(columns=to_drop, errors="ignore")

    return out, new_names, calc_keys
