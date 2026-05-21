# -*- coding: utf-8 -*-
"""Сервис: турнир конфигов по JSON или прогноз (forecast) с победителем из JSON.

- ``COMPARISON=True`` или ``--comparison`` → ``run_comparison`` (только JSON).
- Иначе → ``PredictOparationCountCombo``: прогноз как ``optim_2_predict``, но конфиг берётся из JSON.

Флаги можно задать константой ``COMPARISON`` или CLI (CLI переопределяет).
История: Django ``ResistParameterCalculateHistory`` либо CSV через ``CsvHistoryRepository``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

COMPARISON: bool = False

DEFAULT_CONFIG_JSON: Path = _ROOT / "data" / "processed" / "comparison_winner_configs.json"

try:
    from app_history.models import ResistParameterCalculateHistory
except ImportError:
    ResistParameterCalculateHistory = None  # type: ignore[misc, assignment]

from scripts.comparison_operation_count_v2 import ConfigDispatcher  # noqa: E402
from scripts.comparison_operation_count_v2 import (
    FALLBACK_WINDOW_MEDIAN_3_LABEL,
    HISTORY_START_DATE,
    MODEL_KEY,
    OperationHistoryCleaner,
    ProductionForecaster,
    WinnerConfigStore,
    _format_date_key,
    operations_discovered_from_rows,
    run_comparison,
)
from scripts.benchmark_predict_v2_vs_optimized import (  # noqa: E402
    SyntheticDfHistoryRepository,
    build_synthetic_history_df,
)
from scripts.comparison_tsa_per_series_nb37_trainers import SERIES_CONFIGS as SERIES_CONFIGS_CMP  # noqa: E402
from scripts.nb37_raw_model39_load import (  # noqa: E402
    EXCLUDED_RESIST_IDS,
    load_df_model39_from_nb37_raw_files,
)
import scripts.optim_2_predict_operation_count_v2 as o2mod_predict  # noqa: E402
from scripts.optim_2_tsa_per_series_nb37_trainers import SERIES_CONFIGS as SERIES_CONFIGS_OPT2  # noqa: E402
from scripts.test_predict_operation_count_v2 import CsvHistoryRepository  # noqa: E402

logger = logging.getLogger(__name__)

RAW_DIR = _ROOT / "data" / "raw"
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]


class HistoryRepository:
    """Production: ``ResistParameterCalculateHistory`` (как в optim_2)."""

    def fetch(self, resist: str) -> Iterable[Mapping[str, Any]]:
        if ResistParameterCalculateHistory is None:
            raise ImportError("Нужен app_history.models.ResistParameterCalculateHistory")
        now_period = (datetime.today().replace(day=1) - timedelta(days=1)).replace(day=1)
        return (
            ResistParameterCalculateHistory.objects.filter(
                resist=int(resist),
                period__gt=HISTORY_START_DATE,
                period__lt=now_period,
            )
            .values("period", "operation_parameter")
            .order_by("period")
        )


def _coerce_operation_id(value: object) -> object:
    try:
        x = float(value)
        return int(x) if x == int(x) else x
    except (TypeError, ValueError):
        return value


def default_operations_for_resist_csv(df: pd.DataFrame, resist_id: int) -> list:
    """Список operation_id для resist в окне дат production (csv)."""
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
    return sorted({_coerce_operation_id(x) for x in raw}, key=lambda z: (str(type(z)), str(z)))


class JsonConfigSelector:
    """Поиск конфига по ключу из JSON-словаря."""

    def __init__(self, mapping: Mapping[str, str]) -> None:
        self._mapping = dict(mapping)

    def get(self, resist_id: int, operation_id: Any) -> str:
        keys = []
        keys.append(WinnerConfigStore.compose_json_key(resist_id, operation_id))
        try:
            keys.append(WinnerConfigStore.compose_json_key(resist_id, int(operation_id)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
        for k in keys:
            if k in self._mapping:
                return self._mapping[k]
        logger.warning(
            "JsonConfigSelector: ключ не найден для rid=%s op=%s пробовали=%s → Fallback-WM-3",
            resist_id, operation_id, keys,
        )
        return FALLBACK_WINDOW_MEDIAN_3_LABEL


class PredictOparationCountCombo:
    """Прогноз без inline-турнира: конфиг из JSON-словаря."""

    def __init__(
        self,
        *,
        winner_mapping: Mapping[str, str],
        repository: Any,
        cleaner: Optional[OperationHistoryCleaner] = None,
        dispatcher: Optional[ConfigDispatcher] = None,
        forecaster: Optional[ProductionForecaster] = None,
    ) -> None:
        self._repository = repository
        self._cleaner = cleaner or OperationHistoryCleaner()
        self._dispatcher = dispatcher or ConfigDispatcher()
        self._forecaster = forecaster or ProductionForecaster(self._dispatcher)
        self._selector = JsonConfigSelector(winner_mapping)

    def predict(self, operations: List[Any], resist: str) -> Dict[Any, Dict[str, Any]]:
        query_rows = self._repository.fetch(resist)
        oper_data = self._cleaner.format_data(operations, query_rows)
        oper_data_valid = self._cleaner.drop_leading_zeros(oper_data)

        try:
            rid = int(resist)
        except (TypeError, ValueError):
            rid = 0

        result: Dict[Any, Dict[str, Any]] = {}
        for op_id, history in oper_data_valid.items():
            if not history:
                continue
            df_op = self._cleaner.to_dataframe(history, op_id, rid)
            if df_op.empty:
                continue
            winner = self._selector.get(rid, op_id)
            try:
                forecast_map = self._forecaster.forecast(df_op, rid, winner)
            except Exception as exc:
                logger.exception("predict_combo op=%s rid=%s winner=%s: %s", op_id, rid, winner, exc)
                forecast_map = {}

            merged: Dict[str, Any] = {}
            for period, value in history.items():
                try:
                    fv = float(value) if value is not None else 0.0
                except (TypeError, ValueError):
                    fv = 0.0
                merged[_format_date_key(period)] = fv
            for dk, fv in forecast_map.items():
                merged[str(dk)] = float(fv)
            merged[MODEL_KEY] = winner
            result[op_id] = merged
        return result


def build_repository(data_source: str, df_optional: Optional[pd.DataFrame]) -> Any:
    if data_source == "csv":
        if df_optional is None or df_optional.empty:
            raise ValueError("--data-source csv требует загруженный df из raw CSV.")
        return CsvHistoryRepository(df_optional)
    if data_source == "django":
        return HistoryRepository()
    raise ValueError(f"Неизвестный data-source={data_source!r}")


def _run_smoke_fast() -> None:
    """Турнир на 3 конфигах vs ``WalkForwardSelector`` optim_2 на синтетике."""
    from scripts import comparison_operation_count_v2 as c_mod

    keys = ["ETS-add", "Theta-default", "WindowMedian-3"]
    tiny_cmp = {k: SERIES_CONFIGS_CMP[k] for k in keys}
    tiny_opt = {k: SERIES_CONFIGS_OPT2[k] for k in keys}

    df_syn = build_synthetic_history_df(
        n_operations=2,
        n_months=26,
        resist_id=1,
        seed=7,
        history_start_date=c_mod.HISTORY_START_DATE,
    )
    repo_syn = SyntheticDfHistoryRepository(df_syn, c_mod.HISTORY_START_DATE)
    rows_syn = list(repo_syn.fetch("1"))
    cleaner = c_mod.OperationHistoryCleaner()
    oper_valid = cleaner.drop_leading_zeros(cleaner.format_data([1], rows_syn))
    df_op = cleaner.to_dataframe(oper_valid[1], 1, 1)

    runner = c_mod.ConfigTournamentRunner(configs=tiny_cmp)
    w_tour = runner.winner_for_series(df_op, 1)
    w_opt = o2mod_predict.WalkForwardSelector(
        o2mod_predict.ConfigDispatcher(),
        configs=tiny_opt,
    ).select(df_op, 1)
    assert w_tour == w_opt, (w_tour, w_opt)

    jpath = Path(tempfile.gettempdir()) / "comp_predict_smoke_winner.json"
    jpath.write_text("{}", encoding="utf-8")
    cmap = run_comparison([1], repo_syn, config_json_path=jpath, operations=[1], tournament=runner)
    key = WinnerConfigStore.compose_json_key(1, 1)
    assert key in cmap
    pr = PredictOparationCountCombo(winner_mapping=cmap, repository=repo_syn)
    out = pr.predict([1], "1")
    assert out[1][MODEL_KEY] == cmap[key]
    jpath.unlink(missing_ok=True)
    print(json.dumps({"smoke_fast": "OK", "winner": cmap[key]}, ensure_ascii=False))


def _parse_operations_arg(s: Optional[str]) -> Optional[List[Any]]:
    if not s:
        return None
    ops: List[Any] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ops.append(int(part))
        except ValueError:
            ops.append(part)
    return ops if ops else None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description=(
            "COMPARISON: турнир и JSON победителей; иначе прогноз по JSON "
            "(comp_predict_operation_count_v2)."
        ),
    )
    parser.add_argument("--comparison", action="store_true", help="Режим турнира → JSON только.")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Синоним --comparison.",
    )
    parser.add_argument(
        "--smoke-fast",
        action="store_true",
        help="Быстрый регресс: 3 конфига, синтетика, турнир=WalkForwardSelector, JSON→combo predict.",
    )
    parser.add_argument(
        "--resist-ids",
        default=None,
        help="Список resist_id через запятую (--smoke-fast не требует).",
    )
    parser.add_argument(
        "--operations",
        default=None,
        help="Список operation_id через запятую; для всех resists одинаково. Иначе — авто-список (csv/discovered из БД).",
    )
    parser.add_argument(
        "--config-json",
        type=Path,
        default=DEFAULT_CONFIG_JSON,
        help="Путь JSON с победителями (<resist_id>_<operation_id> → имя конфига).",
    )
    parser.add_argument(
        "--data-source",
        choices=("django", "csv"),
        default="csv",
        help="django: БД приложения; csv: nb37 raw (по умолчанию csv для локальных прогонов).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Путь для JSON результата predict; по умолчанию stdout.",
    )
    args = parser.parse_args()

    if args.smoke_fast:
        logging.disable(logging.CRITICAL)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _run_smoke_fast()
        return

    if not args.resist_ids:
        parser.error("--resist-ids обязателен если не указан --smoke-fast")

    do_compare = COMPARISON or args.comparison or args.compare
    resist_ids = [int(x.strip()) for x in args.resist_ids.split(",") if x.strip()]

    if args.data_source == "csv":
        for p in RAW_FILES:
            if not p.exists():
                print(f"Предупреждение (warning): нет файла {p}", file=sys.stderr)
        df_loaded = load_df_model39_from_nb37_raw_files(RAW_FILES)
    else:
        df_loaded = None

    for rid in resist_ids:
        if rid in EXCLUDED_RESIST_IDS:
            print(
                f"Предупреждение: resist_id={rid} в EXCLUDED_RESIST_IDS — данных в nb37 может не быть.",
                file=sys.stderr,
            )

    ops_arg = _parse_operations_arg(args.operations)

    repo = build_repository(args.data_source, df_loaded)

    if do_compare:
        for rid in resist_ids:
            if ops_arg is not None:
                ops_for_rid = ops_arg
            elif args.data_source == "csv" and df_loaded is not None:
                ops_for_rid = default_operations_for_resist_csv(df_loaded, rid)
            else:
                ops_for_rid = None
            if ops_for_rid is not None and not ops_for_rid:
                logger.warning("Сравнение: нет operation_id после фильтра resist=%s", rid)
                continue
            run_comparison(
                [rid],
                repo,
                config_json_path=args.config_json,
                operations=ops_for_rid,
            )
        print(
            json.dumps(
                {"saved": str(args.config_json.resolve()), "resist_ids": resist_ids},
                ensure_ascii=False,
                indent=2,
            ),
        )
        return

    if not args.config_json.exists():
        print(
            json.dumps({"error": f"нет JSON {args.config_json}; сначала --comparison"}, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        sys.exit(2)

    mapping = WinnerConfigStore.load_mapping(Path(args.config_json))
    predictor = PredictOparationCountCombo(winner_mapping=mapping, repository=repo)

    all_out: Dict[str, Dict[Any, Dict[str, Any]]] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for rid in resist_ids:
            if ops_arg is None:
                if args.data_source == "csv" and df_loaded is not None:
                    ops = default_operations_for_resist_csv(df_loaded, rid)
                else:
                    rows = list(repo.fetch(str(rid)))
                    ops = operations_discovered_from_rows(rows)
            else:
                ops = ops_arg
            if not ops:
                logger.warning("Прогноз: нет операций resist=%s", rid)
                all_out[str(rid)] = {}
                continue
            all_out[str(rid)] = predictor.predict(ops, str(rid))

    text = json.dumps(all_out, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"wrote": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    else:
        print(text)


if __name__ == "__main__":
    main()

