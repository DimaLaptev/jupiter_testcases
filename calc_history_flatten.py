"""
Преобразование скалярных calc_* в календарную развёртку (full flatten): calc_k__YYYY_MM.

Для строки с целевым периодом T=(year, month) колонка calc_k__YYYY_MM равна значению calc_k
за тот месяц в том же ряду (merge_keys, по умолчанию operation_id), если (YYYY, MM) < T; иначе 0.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


def _period_ord(year: int | float, month: int | float) -> np.ndarray:
    y = np.asarray(year, dtype=np.int64)
    m = np.asarray(month, dtype=np.int64)
    return y * 100 + m


def unique_period_keys(df: pd.DataFrame) -> list[tuple[int, int]]:
    """Все уникальные (year, month) в df, по возрастанию."""
    u = df[["year", "month"]].drop_duplicates().sort_values(["year", "month"])
    return [(int(r.year), int(r.month)) for r in u.itertuples(index=False)]


def scalar_calc_columns(df: pd.DataFrame) -> list[str]:
    """Колонки calc_* без календарного суффикса __YYYY_MM."""
    return [c for c in df.columns if c.startswith("calc_") and "__" not in c]


def flatten_column_names(calc_keys: list[str], period_keys: list[tuple[int, int]]) -> list[str]:
    out: list[str] = []
    for k in calc_keys:
        for yp, mp in period_keys:
            out.append(f"{k}__{yp:04d}_{mp:02d}")
    return out


def add_calc_history_flatten(
    df: pd.DataFrame,
    *,
    calc_keys: list[str] | None = None,
    drop_scalar_calc: bool = True,
    merge_keys: Sequence[str] = ("operation_id",),
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Добавляет колонки calc_k__YYYY_MM; опционально удаляет скалярные calc_*.

    merge_keys — ключи для привязки значения calc к строке (по умолчанию только operation_id).
    Для нескольких рядов в одном датафрейме, например: ("resist_id", "operation_id").

    Возвращает (df_расширенный, имена_всех_flatten_колонок, calc_keys_использованные).
    """
    mk = tuple(merge_keys)
    if not mk:
        raise ValueError("merge_keys не может быть пустым")

    need = set(mk) | {"year", "month"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"df: не хватает колонок {missing}")

    if calc_keys is None:
        calc_keys = scalar_calc_columns(df)
    else:
        calc_keys = [c for c in calc_keys if c in df.columns]

    if not calc_keys:
        return df.copy(), [], []

    period_keys = unique_period_keys(df)
    p_ord_map = {(_y, _m): _y * 100 + _m for _y, _m in period_keys}

    out = df.copy()
    flatten_names: list[str] = []

    base = df[list(mk) + ["year", "month"]].copy()
    target_ord = _period_ord(base["year"].values, base["month"].values)
    mk_list = list(mk)

    for yp, mp in period_keys:
        p_ord = p_ord_map[(yp, mp)]
        part = df[df["year"] == yp]
        part = part[part["month"] == mp][mk_list + calc_keys].drop_duplicates(
            subset=mk_list, keep="first"
        )
        merged = base[mk_list].merge(part, on=mk_list, how="left")
        for k in calc_keys:
            col_name = f"{k}__{yp:04d}_{mp:02d}"
            flatten_names.append(col_name)
            vals = merged[k].to_numpy(dtype=float, copy=True)
            vals = np.nan_to_num(vals, nan=0.0)
            mask = p_ord < target_ord
            out[col_name] = np.where(mask, vals, 0.0)

    if drop_scalar_calc:
        to_drop = [c for c in scalar_calc_columns(out) if c in out.columns]
        out = out.drop(columns=to_drop, errors="ignore")

    return out, flatten_names, calc_keys


def flatten_columns_for_sets(
    all_flatten_names: list[str],
    *,
    whitelist: list[str] | None,
) -> tuple[list[str], list[str]]:
    """
    Имена flatten-колонок для наборов B (все ключи) и C (whitelist ключей).

    whitelist — имена вида calc_employeesFact; если None, B и C по flatten совпадают с all.
    """
    if whitelist is None:
        return list(all_flatten_names), list(all_flatten_names)

    wl = set(whitelist)
    b_names = all_flatten_names
    c_names = [c for c in all_flatten_names if c.split("__", 1)[0] in wl]
    return b_names, c_names
