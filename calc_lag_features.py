"""
Признаки calc_* через сдвиги по времени: *_lagN для N из DEFAULT_CALC_SHIFTS
(по умолчанию 1–6 и 12 месяцев, groupby по group_cols, по умолчанию только operation_id).
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

DEFAULT_CALC_SHIFTS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 12)


def scalar_calc_columns(df: pd.DataFrame) -> list[str]:
    """Скалярные колонки calc_* (без суффикса __… как у full flatten). Дубликат логики из calc_history_flatten — без импорта того модуля (меньше цепочка import, меньше риск конфликтов Numba/NumPy)."""
    return [c for c in df.columns if c.startswith("calc_") and "__" not in c]


def lag_feature_names(
    calc_keys: list[str],
    shifts: tuple[int, ...] | None = None,
) -> list[str]:
    """Имена колонок calc_*_lagN для каждого ключа и каждого N из shifts."""
    if shifts is None:
        shifts = DEFAULT_CALC_SHIFTS
    out: list[str] = []
    for k in calc_keys:
        for n in shifts:
            out.append(f"{k}_lag{n}")
    return out


def calc_lag_columns_for_sets(
    calc_keys: list[str],
    *,
    whitelist: list[str] | None,
    shifts: tuple[int, ...] | None = None,
) -> tuple[list[str], list[str]]:
    """Имена колонок для наборов B (все ключи) и C (whitelist ключей)."""
    if shifts is None:
        shifts = DEFAULT_CALC_SHIFTS
    b_names = lag_feature_names(calc_keys, shifts=shifts)
    if whitelist is None:
        return b_names, b_names
    wl = set(whitelist)
    c_keys = [k for k in calc_keys if k in wl]
    return b_names, lag_feature_names(c_keys, shifts=shifts)


def add_calc_shift_lags(
    df: pd.DataFrame,
    *,
    calc_keys: list[str] | None = None,
    drop_scalar_calc: bool = True,
    shifts: tuple[int, ...] | None = None,
    group_cols: Sequence[str] = ("operation_id",),
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Для каждого скалярного calc_k добавляет колонки k_lagN (groupby по group_cols, shift).

    По умолчанию group_cols=("operation_id",) — поведение как раньше.
    Для нескольких рядов в одном датафрейме, например: ("resist_id", "operation_id").

    Возвращает (df, имена_новых_колонок, использованные_calc_keys).
    """
    if shifts is None:
        shifts = DEFAULT_CALC_SHIFTS

    gc = tuple(group_cols)
    if not gc:
        raise ValueError("group_cols не может быть пустым")

    need = set(gc) | {"year", "month"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"df: не хватает колонок {missing}")

    sort_keys = list(gc) + ["year", "month"]
    out = df.copy()
    out = out.sort_values(sort_keys, kind="mergesort").reset_index(drop=True)

    if calc_keys is None:
        calc_keys = scalar_calc_columns(out)
    else:
        calc_keys = [c for c in calc_keys if c in out.columns]

    if not calc_keys:
        return out, [], []

    g = out.groupby(list(gc), sort=False)
    new_names: list[str] = []
    for k in calc_keys:
        for n in shifts:
            col = f"{k}_lag{n}"
            out[col] = g[k].shift(n)
            new_names.append(col)

    for col in new_names:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    if drop_scalar_calc:
        to_drop = [c for c in calc_keys if c in out.columns]
        out = out.drop(columns=to_drop, errors="ignore")

    return out, new_names, calc_keys


def add_calc_shift_lag1_lag12(
    df: pd.DataFrame,
    *,
    calc_keys: list[str] | None = None,
    drop_scalar_calc: bool = True,
    group_cols: Sequence[str] = ("operation_id",),
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Обратная совместимость: то же, что add_calc_shift_lags с shifts=DEFAULT_CALC_SHIFTS
    (lag 1–6 и 12, не только 1 и 12).
    """
    return add_calc_shift_lags(
        df,
        calc_keys=calc_keys,
        drop_scalar_calc=drop_scalar_calc,
        shifts=DEFAULT_CALC_SHIFTS,
        group_cols=group_cols,
    )
