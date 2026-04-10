"""
Дашборд (phase1) из нескольких Excel во вложенной папке: для каждого resist_id
выбирается лучший источник по листам «… Итог» (максимум «Качество, %» среди файлов),
затем как в build_model_comparison_dashboard: если «Кач. fact_predict, %» выше —
в итоге «Текущий» (fact_predict).

Использование:
    python scripts/build_model_comparison_dashboard_from_folder.py
    python scripts/build_model_comparison_dashboard_from_folder.py -d data/processed/dashboards
    python scripts/build_model_comparison_dashboard_from_folder.py -d path/to/dir -o out.xlsx
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


def _load_build_model_comparison_dashboard():
    path = _project_root / "scripts" / "build_model_comparison_dashboard.py"
    if not path.is_file():
        raise FileNotFoundError(f"Не найден модуль: {path}")
    spec = importlib.util.spec_from_file_location("build_model_comparison_dashboard", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Не удалось загрузить {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _best_row_metrics_from_itog(df_it: pd.DataFrame) -> tuple[float | None, str, float | None] | None:
    """Верхняя строка после сортировки по «Качество, %» — как в _pick_best_from_itog."""
    if df_it.empty or "Комбинация" not in df_it.columns:
        return None
    d = df_it.copy()
    if "Качество, %" in d.columns:
        d["Качество, %"] = pd.to_numeric(d["Качество, %"], errors="coerce")
        d = d.sort_values("Качество, %", ascending=False, na_position="last").reset_index(drop=True)
    if d.empty:
        return None
    row0 = d.iloc[0]
    q_new = pd.to_numeric(row0.get("Качество, %"), errors="coerce")
    q_fp = pd.to_numeric(row0.get("Кач. fact_predict, %"), errors="coerce")
    combo = str(row0["Комбинация"])
    return (
        float(q_new) if pd.notna(q_new) else None,
        combo,
        float(q_fp) if pd.notna(q_fp) else None,
    )


def _q_new_sort_key(q_new: float | None) -> float:
    return float(q_new) if q_new is not None else float("-inf")


def _collect_itog_candidates(
    dashboards_dir: Path,
    itog_suffix: str,
) -> tuple[dict[int | str, list[dict[str, Any]]], list[Path]]:
    """
    По всем *.xlsx в каталоге собирает кандидатов по (resist_id, файл):
    q_new, q_fp, combo, path.
    """
    paths = sorted(p for p in dashboards_dir.glob("*.xlsx") if p.is_file() and not p.name.startswith("~$"))
    by_rid: dict[int | str, list[dict[str, Any]]] = {}

    for xlsx_path in paths:
        xl = pd.ExcelFile(xlsx_path, engine="openpyxl")
        for name in xl.sheet_names:
            if not name.endswith(itog_suffix):
                continue
            rid_raw = name.removesuffix(itog_suffix).strip()
            try:
                rid = int(rid_raw)
            except ValueError:
                rid = rid_raw
            df_it = pd.read_excel(xlsx_path, sheet_name=name, engine="openpyxl")
            metrics = _best_row_metrics_from_itog(df_it)
            if metrics is None:
                continue
            q_new, combo, q_fp = metrics
            by_rid.setdefault(rid, []).append({
                "path": xlsx_path,
                "q_new": q_new,
                "q_fp": q_fp,
                "combo": combo,
            })

    return by_rid, paths


def _pick_winning_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Максимум q_new; при равенстве — лексикографически меньший path (str)."""
    return min(
        candidates,
        key=lambda c: (-_q_new_sort_key(c.get("q_new")), str(c["path"])),
    )


def _warn_q_fp_mismatch(rid: int | str, candidates: list[dict[str, Any]]) -> None:
    fps = [c["q_fp"] for c in candidates if c.get("q_fp") is not None]
    if len(fps) <= 1:
        return
    mx, mn = max(fps), min(fps)
    if mx - mn > 1e-6:
        print(
            f"Предупреждение: для resist_id={rid!r} разные «Кач. fact_predict, %» "
            f"на листах Итог в разных файлах (min={mn:.4f}, max={mx:.4f}); "
            f"для решения используется значение с выигравшего файла.",
            file=sys.stderr,
        )


def _read_data_sheet_normalized(xlsx_path: Path, sheet_name: str, bmcd) -> pd.DataFrame:
    df_d = pd.read_excel(xlsx_path, sheet_name=sheet_name, engine="openpyxl")
    new_col = bmcd._find_new_col(list(df_d.columns))

    rename: dict[str, str] = {}
    for c in df_d.columns:
        if c == "fact_value (факт)":
            rename[c] = "fact_value"
        elif c == "fact_predict (текущий)":
            rename[c] = "fact_predict"
    if new_col:
        rename[new_col] = "predict_new"

    df_d = df_d.rename(columns=rename)

    for col in ("fact_value", "fact_predict"):
        if col in df_d.columns:
            df_d[col] = pd.to_numeric(df_d[col], errors="coerce").fillna(0)
    if "predict_new" in df_d.columns:
        df_d["predict_new"] = pd.to_numeric(df_d["predict_new"], errors="coerce").fillna(0)
    else:
        df_d["predict_new"] = 0.0

    return df_d


def load_source_phase1_from_folder(
    dashboards_dir: Path,
    bmcd,
) -> tuple[pd.DataFrame, dict[int | str, str]]:
    """
    Несколько Excel: по каждому resist_id — лучший файл по Итог, затем выбор Текущий vs новый.
    """
    itog_suffix: str = bmcd.ITOG_SUFFIX
    data_suffix: str = bmcd.DATA_SUFFIX

    by_rid, input_paths = _collect_itog_candidates(dashboards_dir, itog_suffix)

    if not input_paths:
        raise SystemExit(f"В каталоге нет файлов *.xlsx: {dashboards_dir}")

    if not by_rid:
        raise SystemExit(
            f"Ни в одном из файлов не найдены листы «…{itog_suffix.strip()}»: {dashboards_dir}"
        )

    best_map: dict[int | str, str] = {}
    use_fp_map: dict[int | str, bool] = {}
    winner_path: dict[int | str, Path] = {}

    for rid, cands in by_rid.items():
        _warn_q_fp_mismatch(rid, cands)
        w = _pick_winning_candidate(cands)
        winner_path[rid] = w["path"]
        q_new = w.get("q_new")
        q_fp = w.get("q_fp")

        if (
            q_fp is not None
            and q_new is not None
            and float(q_fp) > float(q_new)
        ):
            best_map[rid] = "Текущий"
            use_fp_map[rid] = True
        else:
            best_map[rid] = w["combo"]
            use_fp_map[rid] = False

    frames: list[pd.DataFrame] = []
    _accuracy_col = bmcd._accuracy_col

    for rid, path in sorted(winner_path.items(), key=lambda x: (str(type(x[0])), x[0])):
        sheet_name = f"{rid}{data_suffix}"
        xl = pd.ExcelFile(path, engine="openpyxl")
        if sheet_name not in xl.sheet_names:
            raise SystemExit(
                f"В файле-победителе для resist_id={rid!r} нет листа {sheet_name!r}: {path}"
            )
        df_d = _read_data_sheet_normalized(path, sheet_name, bmcd)
        frames.append(df_d)

    df = pd.concat(frames, ignore_index=True)

    df["abs_error"] = (df["fact_value"] - df["fact_predict"]).abs()
    df["accuracy_pct"] = _accuracy_col(df["fact_value"], df["fact_predict"])

    df["abs_error_new"] = (df["fact_value"] - df["predict_new"]).abs()
    df["accuracy_pct_new"] = _accuracy_col(df["fact_value"], df["predict_new"])

    df["predict_chosen"] = np.where(
        df["resist_id"].map(use_fp_map).fillna(False),
        df["fact_predict"],
        df["predict_new"],
    )
    df["abs_error_chosen"] = (df["fact_value"] - df["predict_chosen"]).abs()
    df["accuracy_pct_chosen"] = _accuracy_col(df["fact_value"], df["predict_chosen"])

    if "resist_id" in df.columns:
        df["resist_id"] = pd.to_numeric(df["resist_id"], errors="coerce")
        df["resist_id"] = df["resist_id"].apply(
            lambda x: int(x) if pd.notna(x) and float(x) == int(x) else x
        )
    if "month" in df.columns:
        df["month"] = pd.to_numeric(df["month"], errors="coerce").fillna(0).astype(int)
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)

    df["best_model_name"] = df["resist_id"].map(best_map).fillna("")

    if "division_title" not in df.columns:
        df["division_title"] = ""

    # Дубликаты ключей после concat разных resist_id не ожидаются; пересечение — предупреждение
    key_cols = [c for c in ("resist_id", "operation_id", "year", "month") if c in df.columns]
    if key_cols:
        dup = df.duplicated(subset=key_cols, keep=False)
        if dup.any():
            print(
                f"Предупреждение: {dup.sum()} строк с дублирующимися ключами {key_cols}.",
                file=sys.stderr,
            )

    return df, best_map


def _default_dashboards_dir() -> Path:
    return _project_root / "data" / "processed" / "dashboards"


def _default_output_path() -> Path:
    return _project_root / "data" / "processed" / "model_comparison_dashboard_merged.xlsx"


def build_dashboard_merged(
    dashboards_dir: Path,
    output_path: Path | None = None,
) -> Path:
    bmcd = _load_build_model_comparison_dashboard()
    df, _best_map = load_source_phase1_from_folder(dashboards_dir, bmcd)
    div_stats = bmcd._division_stats_dual(df)

    wb = Workbook()
    wb.remove(wb.active)

    bmcd.build_data_sheet(wb, df)
    bmcd.build_dashboard_sheet(
        wb,
        df,
        div_stats,
        main_title="Оценка качества прогноза (объединение из папки dashboards)",
        second_forecast_label="Новый",
        second_block_table_label="новый",
    )
    bmcd.build_heatmap_sheet(wb, df)

    out = output_path if output_path is not None else _default_output_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))

    print(f"Дашборд сохранён: {out.resolve()}")
    print(f"  resist_id в выборе: {len(_best_map)}, строк данных: {len(df)}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(
        description="Дашборд phase1 из нескольких Excel в папке (лучший Итог на resist_id + сравнение с fact_predict)."
    )
    p.add_argument(
        "--dashboards-dir",
        "-d",
        type=Path,
        default=_default_dashboards_dir(),
        help="Каталог с входными .xlsx (по умолчанию: data/processed/dashboards)",
    )
    p.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Выходной xlsx (по умолчанию: data/processed/model_comparison_dashboard_merged.xlsx)",
    )
    args = p.parse_args()

    d = args.dashboards_dir
    if not d.is_dir():
        print(f"Каталог не найден: {d}", file=sys.stderr)
        sys.exit(1)

    build_dashboard_merged(d, args.output)


if __name__ == "__main__":
    main()
