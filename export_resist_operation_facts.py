"""
Экспорт факта (fact_value) по операциям (operation_id) для выбранного resist_id
из сырых CSV — та же логика, что в notebooks/20_per_series_data_augmentation_vanil.ipynb (ячейка загрузки).

По умолчанию id из EXCLUDED_RESIST_IDS исключаются до парсинга (как в ноутбуке).
Для таких id без флага --include-excluded строк не будет — используйте --include-excluded.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

EXCLUDED_RESIST_IDS = [
    25, 26, 27, 29, 54, 57, 61, 63, 66, 68, 80, 81, 82, 83, 100, 101, 102, 103,
    104, 105, 106, 109, 112, 113, 115, 116, 119, 120, 121, 122, 123, 125, 126,
    129, 131, 132, 134, 135, 136, 137, 138, 140, 141, 143, 144, 146, 147, 148,
    149, 150, 151, 152, 153, 154, 156, 157, 158, 162, 165, 169, 170, 171, 172,
    173, 174, 175, 176, 177, 178, 179, 181, 196, 139,
]
PREDICT_COMMENT = "first_predict_value_record"

NARROW_COLUMNS = [
    "resist_id",
    "operation_id",
    "year",
    "month",
    "date",
    "fact_value",
    "fact_predict",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_raw_files() -> list[Path]:
    raw_dir = _repo_root() / "data" / "raw"
    return [
        raw_dir / "data-2022.csv",
        raw_dir / "data-2023.csv",
        raw_dir / "data-2024.csv",
        raw_dir / "data-2025.csv",
    ]


def to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "t", "1"])


def to_bool_value(value):
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return None
    return str(value).strip().lower() in ["true", "t", "1"]


def parse_calculate_param(calc_json: str):
    if pd.isna(calc_json):
        return {}
    try:
        return json.loads(calc_json)
    except Exception:
        return {}


def flatten_calc_to_dict(calc_obj: dict, prefix: str = "calc_") -> dict:
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


def load_model39_from_raw(
    raw_paths: list[Path],
    *,
    include_excluded: bool = False,
) -> pd.DataFrame:
    dfs = []
    for p in raw_paths:
        if p.exists():
            dfs.append(pd.read_csv(p, dtype=str))
    if not dfs:
        raw_dir = raw_paths[0].parent if raw_paths else Path(".")
        raise FileNotFoundError(f"Файлы данных не найдены (ожидались CSV в {raw_dir})")

    df_all = pd.concat(dfs, ignore_index=True)
    df_all["period"] = pd.to_datetime(df_all["period"], errors="coerce")
    df_all["resist_id"] = pd.to_numeric(df_all["resist_id"], errors="coerce").astype("Int64")

    bool_cols = ["send", "validate_one", "validate_two", "cancel_approve", "forecast"]
    for col in bool_cols:
        if col in df_all.columns:
            df_all[col] = to_bool(df_all[col])
    df_all["validate_count"] = (
        pd.to_numeric(df_all["validate_count"], errors="coerce").fillna(0).astype(int)
    )
    if "comment" in df_all.columns:
        df_all["comment"] = df_all["comment"].fillna("")
        mask_predict_record = df_all["comment"] == PREDICT_COMMENT
    else:
        mask_predict_record = pd.Series(False, index=df_all.index)

    resist_ok = (
        pd.Series(True, index=df_all.index)
        if include_excluded
        else ~df_all["resist_id"].isin(EXCLUDED_RESIST_IDS)
    )
    mask_ok = ~df_all["cancel_approve"] & ~mask_predict_record & resist_ok
    df_ok = df_all[mask_ok].copy()

    records = []
    for _, row in df_ok.iterrows():
        calc_obj = parse_calculate_param(row.get("calculate_parameter"))
        calc_flat = flatten_calc_to_dict(calc_obj)
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
            if to_bool_value(payload.get("operation_active", payload.get("active"))) is False:
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
    if df_model39.empty:
        return df_model39

    df_model39["fact_value"] = pd.to_numeric(df_model39["fact_value"], errors="coerce")
    df_model39["fact_predict"] = pd.to_numeric(df_model39["fact_predict"], errors="coerce")
    df_model39["workDayMonth_2"] = pd.to_numeric(df_model39["workDayMonth_2"], errors="coerce")
    df_model39["calculate_minute"] = pd.to_numeric(
        df_model39["calculate_minute"], errors="coerce"
    )

    calc_cols = [c for c in df_model39.columns if c.startswith("calc_")]
    for col in calc_cols:
        df_model39[col] = pd.to_numeric(df_model39[col], errors="coerce")

    df_model39["date"] = pd.to_datetime(
        dict(year=df_model39["year"], month=df_model39["month"], day=1), errors="coerce"
    ).dt.date
    df_model39 = df_model39.dropna(subset=["fact_value"])
    df_model39 = df_model39.sort_values(["operation_id", "year", "month"]).reset_index(drop=True)
    return df_model39


def facts_for_resist(
    df: pd.DataFrame,
    resist_id: int,
    *,
    full_rows: bool = False,
) -> pd.DataFrame:
    sub = df[df["resist_id"] == resist_id].copy()
    if sub.empty:
        return sub
    if full_rows:
        return sub
    cols = [c for c in NARROW_COLUMNS if c in sub.columns]
    return sub[cols]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Выгрузка fact_value по operation_id для одного resist_id из data/raw/*.csv."
    )
    p.add_argument("--resist-id", type=int, required=True, help="Идентификатор resist_id.")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Путь к выходному CSV (если не задан — сводка и head в stdout).",
    )
    p.add_argument(
        "--include-excluded",
        action="store_true",
        help="Не отфильтровывать EXCLUDED_RESIST_IDS (как в ноутбуке по умолчанию они вырезаны).",
    )
    p.add_argument(
        "--full-rows",
        action="store_true",
        help="Включить все колонки df_model39 (calc_*, workDayMonth_2, …), не только узкий набор.",
    )
    p.add_argument(
        "--raw",
        type=Path,
        nargs="*",
        default=None,
        help="Явный список CSV; по умолчанию data-2022…2025 в data/raw от корня репозитория.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    raw_paths = list(args.raw) if args.raw else default_raw_files()
    try:
        df_model39 = load_model39_from_raw(raw_paths, include_excluded=args.include_excluded)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    if df_model39.empty:
        print("После загрузки и фильтров датафрейм пуст.", file=sys.stderr)
        return 1

    avail = {int(x) for x in df_model39["resist_id"].dropna().unique()}
    if args.resist_id not in avail:
        sample = sorted(avail)[:15]
        print(
            f"Нет данных для resist_id={args.resist_id}. "
            f"Примеры доступных id: {sample}... "
            f"(для исключённых id попробуйте --include-excluded)",
            file=sys.stderr,
        )
        return 1

    out = facts_for_resist(df_model39, args.resist_id, full_rows=args.full_rows)
    if out.empty:
        print(f"Пустая выборка для resist_id={args.resist_id}.", file=sys.stderr)
        return 1

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(args.output, index=False)
        print(f"Записано строк: {len(out)} -> {args.output}")
        return 0

    n_ops = out["operation_id"].nunique()
    print(f"resist_id={args.resist_id}: строк={len(out)}, операций (operation_id)={n_ops}")
    print(out.head(20).to_string(index=False))
    if len(out) > 20:
        print(f"... ещё {len(out) - 20} строк (используйте -o для полного CSV)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
