"""
Выгрузка полного сырого датафрейма в Excel.

Загружает CSV за 2022–2025 годы, разворачивает JSON (operation_parameter — в строки
по каждой операции; calculate_parameter — в отдельные колонки), сохраняет один xlsx.
Колонки: id, period, resist_id, division_name, cancel_approve, comment, forecast,
send, validate_count, validate_one, validate_two, coast_parameter, coast_data,
operation_id (+ поля операции), развёрнутый calculate_parameter.

Использование:
    python export_raw_to_excel.py
    python export_raw_to_excel.py --output data/processed/raw_export.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


RAW_DIR = Path("data/raw")
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]

DEFAULT_OUTPUT = Path("data/processed/raw_export.xlsx")

# Скалярные колонки из сырого массива (в порядке вывода)
SCALAR_COLS = [
    "id",
    "period",
    "resist_id",
    "division_name",
    "cancel_approve",
    "comment",
    "forecast",
    "send",
    "validate_count",
    "validate_one",
    "validate_two",
    "coast_parameter",
    "coast_data",
]


def parse_json_safe(raw, default=None):
    if default is None:
        default = {}
    if pd.isna(raw) or raw == "":
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def parse_division_title(div_json) -> str:
    """Из JSON division_name извлекает name для колонки division_title."""
    if pd.isna(div_json) or div_json == "":
        return ""
    obj = parse_json_safe(div_json, {})
    return str(obj.get("name", "")) if isinstance(obj, dict) else ""


def flatten_calc_to_dict(calc_obj: dict, prefix: str = "calc_") -> dict:
    """Разворачивает calculate_parameter в плоский словарь для колонок."""
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


def load_raw_all() -> pd.DataFrame:
    dfs = []
    for p in RAW_FILES:
        if not p.exists():
            print(f"Файл не найден, пропуск: {p}", file=sys.stderr)
            continue
        dfs.append(pd.read_csv(p, dtype=str))
    if not dfs:
        print("Нет CSV-файлов для загрузки.", file=sys.stderr)
        sys.exit(1)
    df = pd.concat(dfs, ignore_index=True)
    df["period"] = pd.to_datetime(df["period"], errors="coerce")
    if "resist_id" in df.columns:
        df["resist_id"] = pd.to_numeric(df["resist_id"], errors="coerce").astype("Int64")
    return df


def build_expanded_raw(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Строит датафрейм: одна строка на каждую операцию в каждой сырой записи.
    Скалярные поля дублируются по операциям; calculate_parameter развёрнут в колонки.
    """
    rows = []
    scalar_cols = [c for c in SCALAR_COLS if c in df_raw.columns]

    for _, row in df_raw.iterrows():
        op_raw = row.get("operation_parameter")
        calc_raw = row.get("calculate_parameter")
        calc_obj = parse_json_safe(calc_raw, {})
        calc_flat = flatten_calc_to_dict(calc_obj)

        base = {c: row.get(c) for c in scalar_cols}
        base["division_title"] = parse_division_title(row.get("division_name"))

        if pd.isna(op_raw) or op_raw == "":
            # Строка без операций — одна строка с пустым operation_id
            out = {**base, "operation_id": "", **calc_flat}
            rows.append(out)
            continue

        try:
            op_data = json.loads(op_raw)
        except Exception:
            out = {**base, "operation_id": "", **calc_flat}
            rows.append(out)
            continue

        if not isinstance(op_data, dict):
            out = {**base, "operation_id": "", **calc_flat}
            rows.append(out)
            continue

        for op_id, payload in op_data.items():
            op_dict = payload if isinstance(payload, dict) else {}
            # Поля операции как отдельные колонки (опционально)
            op_fact_value = op_dict.get("fact_value", "")
            op_fact_predict = op_dict.get("fact_predict", "")
            op_calculate_minute = op_dict.get("calculate_minute", "")
            op_active = op_dict.get("operation_active", op_dict.get("active", ""))

            out = {
                **base,
                "operation_id": op_id,
                "op_fact_value": op_fact_value,
                "op_fact_predict": op_fact_predict,
                "op_calculate_minute": op_calculate_minute,
                "op_active": op_active,
                **calc_flat,
            }
            rows.append(out)

    df = pd.DataFrame(rows)
    # Порядок колонок: скаляры, division_title, операция, развёрнутый calculate_parameter
    first_cols = [c for c in SCALAR_COLS + ["division_title", "operation_id", "op_fact_value", "op_fact_predict", "op_calculate_minute", "op_active"] if c in df.columns]
    rest = [c for c in df.columns if c not in first_cols]
    return df[first_cols + rest]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Выгрузка сырого датафрейма (все года) в Excel с развёрнутым JSON"
    )
    parser.add_argument(
        "--output", "-o",
        default=str(DEFAULT_OUTPUT),
        help="Путь к выходному xlsx",
    )
    args = parser.parse_args()

    print("Загрузка сырых CSV (2022–2025)...")
    df_raw = load_raw_all()
    print(f"  Загружено строк (сырых записей): {len(df_raw)}")

    print("Разворачивание JSON (операции + calculate_parameter)...")
    df = build_expanded_raw(df_raw)
    print(f"  Строк после развёртки: {len(df)}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(str(out_path), index=False)
    print(f"\nФайл сохранён: {out_path}")
    print(f"Строк: {len(df)}, колонок: {len(df.columns)}")


if __name__ == "__main__":
    main()
