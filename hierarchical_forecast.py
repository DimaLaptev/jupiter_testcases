"""
Иерархический (top-down) прогноз операционной нагрузки в подразделениях.

Прогнозирование выполняется в три этапа:
1. Прогноз итоговой нагрузки (load %) по подразделениям (resist_id)
2. Прогноз долей трудозатрат операций (operation shares)
3. Расчёт прогноза количества операций через трудозатраты

Библиотеки: pandas, numpy; statsmodels (ExponentialSmoothing / Holt-Winters) — опциональна.
При отсутствии statsmodels используется fallback (среднее по ряду).
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    HAS_ETS = True
except ImportError:
    HAS_ETS = False


# Минимальная длина ряда для сезонной модели (Holt-Winters с seasonal_periods=12)
_MIN_SEASONAL_LEN = 12
# Горизонт прогноза (месяцев)
FORECAST_STEPS = 4


def _forecast_exponential_smoothing(
    series: pd.Series,
    steps: int = FORECAST_STEPS,
) -> np.ndarray:
    """
    Прогноз с ExponentialSmoothing (Holt-Winters).

    При len >= 12: trend='add', seasonal='add', seasonal_periods=12.
    При len < 12: несезонная модель (trend='add', seasonal=None).

    :param series: временной ряд с DatetimeIndex/PeriodIndex
    :param steps: число шагов прогноза
    :return: массив прогнозов длины steps, при ошибке — np.nan
    """
    if series.empty:
        return np.full(steps, np.nan)

    n = len(series)
    vals = np.asarray(series.values, dtype=float)
    finite = vals[np.isfinite(vals)]

    if n == 1:
        return np.full(steps, float(vals[0]))

    # Fallback при отсутствии statsmodels: среднее по ряду
    if not HAS_ETS:
        fallback = float(np.mean(finite)) if len(finite) > 0 else np.nan
        return np.full(steps, fallback)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            if n >= _MIN_SEASONAL_LEN:
                model = ExponentialSmoothing(
                    vals,
                    trend="add",
                    seasonal="add",
                    seasonal_periods=12,
                )
            else:
                # Недостаточно точек для сезонности — модель без seasonal
                model = ExponentialSmoothing(
                    vals,
                    trend="add",
                    seasonal=None,
                )
            fit = model.fit()
            pred = fit.forecast(steps=steps)

        return np.asarray(pred, dtype=float)

    except Exception:
        # Fallback: среднее или последнее значение
        return np.full(steps, float(np.nanmean(vals)) if np.any(np.isfinite(vals)) else np.nan)


def _get_last_values_per_resist(
    df: pd.DataFrame,
    resist_ids: list,
) -> pd.DataFrame:
    """
    Для каждого resist_id возвращает последние известные staff_count и work_hours_in_month
    (по максимальному period).
    """
    subset = df[df["resist_id"].isin(resist_ids)][
        ["resist_id", "period", "staff_count", "work_hours_in_month"]
    ]
    idx = subset.groupby("resist_id")["period"].idxmax()
    last_per_resist = subset.loc[idx][["resist_id", "staff_count", "work_hours_in_month"]]
    return last_per_resist.reset_index(drop=True)


def _generate_future_periods(last_period: pd.Timestamp, steps: int) -> pd.DatetimeIndex:
    """Генерирует steps следующих периодов (месяцев) после last_period."""
    return pd.date_range(
        start=last_period + pd.DateOffset(months=1),
        periods=steps,
        freq="MS",
    )


def _work_hours_for_month(period: pd.Timestamp, hours_per_day: float = 8.0) -> float:
    """
    Временная функция: Рабочие часы по реальному календарю РФ (2023-2025).
    Заменяет pd.bdate_range для корректного учёта праздников.
    """
    # Словарь: (Год, Месяц) -> Количество рабочих дней
    ru_calendar = {
        # 2023 год
        (2023, 1): 17, (2023, 2): 18, (2023, 3): 22, (2023, 4): 20, (2023, 5): 20, (2023, 6): 21,
        (2023, 7): 21, (2023, 8): 23, (2023, 9): 21, (2023, 10): 22, (2023, 11): 21, (2023, 12): 21,
        # 2024 год
        (2024, 1): 17, (2024, 2): 20, (2024, 3): 20, (2024, 4): 21, (2024, 5): 20, (2024, 6): 19,
        (2024, 7): 23, (2024, 8): 22, (2024, 9): 21, (2024, 10): 23, (2024, 11): 21, (2024, 12): 21,
        # 2025 год (для будущих прогнозов)
        (2025, 1): 17, (2025, 2): 20, (2025, 3): 21, (2025, 4): 22, (2025, 5): 18, (2025, 6): 20,
        (2025, 7): 23, (2025, 8): 21, (2025, 9): 22, (2025, 10): 23, (2025, 11): 19, (2025, 12): 22,
    }

    n_days = ru_calendar.get((period.year, period.month))

    if n_days is None:
        # Fallback для периодов вне захардкоженного диапазона
        start = period.replace(day=1)
        end = start + pd.offsets.MonthEnd(0)
        n_days = len(pd.bdate_range(start, end))
        print(f"Warning: Календарь для {period.strftime('%Y-%m')} не найден, используется pd.bdate_range ({n_days} дней).")

    return float(n_days) * hours_per_day


def generate_hierarchical_forecast(
    historical_df: pd.DataFrame,
    *,
    diagnose_outliers: bool = False,
) -> pd.DataFrame:
    """
    Генерирует прогноз количества операций с использованием иерархического подхода.

    :param historical_df: DataFrame с историческими данными, содержащий колонки:
        - 'period': (datetime64[ns]) Месяц, за который предоставлены данные.
        - 'resist_id': (object) Уникальный идентификатор подразделения.
        - 'operation_name': (object) Уникальное наименование операции.
        - 'fact_value': (float64) Фактическое количество выполненных операций.
        - 'norm_value': (float64) Норматив времени (в часах) на выполнение одной операции.
        - 'staff_count': (float64) Количество сотрудников (FTE) в подразделении в данном месяце.
        - 'work_hours_in_month': (float64) Норматив рабочих часов в данном месяце.
    :return: DataFrame с прогнозом, содержащий колонки:
        - 'period', 'resist_id', 'operation_name', 'fact_predict_hierarchical'.
    """
    required_cols = {
        "period",
        "resist_id",
        "operation_name",
        "fact_value",
        "norm_value",
        "staff_count",
        "work_hours_in_month",
    }
    if historical_df.empty:
        return pd.DataFrame(
            columns=["period", "resist_id", "operation_name", "fact_predict_hierarchical"]
        )

    missing = required_cols - set(historical_df.columns)
    if missing:
        raise ValueError(f"Отсутствуют обязательные колонки: {missing}")

    df = historical_df.copy()
    df["period"] = pd.to_datetime(df["period"])
    df = df.sort_values(["resist_id", "operation_name", "period"])

    # --- Этап 1: Прогноз нагрузки (%) по resist_id ---
    # 1.1 Расчёт исторической нагрузки
    df["operation_hours"] = df["fact_value"] * df["norm_value"]
    total_hours = (
        df.groupby(["resist_id", "period"], as_index=False)["operation_hours"]
        .sum()
        .rename(columns={"operation_hours": "total_hours"})
    )
    load_df = df[["resist_id", "period", "staff_count", "work_hours_in_month"]].drop_duplicates()
    load_df = load_df.merge(total_hours, on=["resist_id", "period"])
    load_df["capacity"] = load_df["staff_count"] * load_df["work_hours_in_month"]
    load_df["load_percent"] = np.where(
        load_df["capacity"] > 0,
        (load_df["total_hours"] / load_df["capacity"]) * 100.0,
        np.nan,
    )
    load_df = load_df[["resist_id", "period", "load_percent"]].dropna(subset=["load_percent"])

    # Диагностика выбросов (staff_count=1 искажает load_percent)
    if diagnose_outliers and not load_df.empty:
        print("\n--- Анализ выбросов в исторической нагрузке (load_percent) ---")
        print(load_df["load_percent"].describe(percentiles=[0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]))
        problem = load_df[load_df["load_percent"] > 200]
        if not problem.empty:
            problem_resists = problem["resist_id"].unique()
            print(f"Подразделения с нагрузкой > 200%: {len(problem_resists)} шт. — {problem_resists[:10].tolist()}{'...' if len(problem_resists) > 10 else ''}")

    # Прогноз нагрузки на 4 месяца для каждого resist_id
    load_forecasts: dict[tuple, np.ndarray] = {}
    last_periods: dict = {}
    for rid, grp in load_df.groupby("resist_id"):
        grp = grp.sort_values("period")
        series = grp.set_index("period")["load_percent"]
        last_periods[rid] = series.index.max()
        pred = _forecast_exponential_smoothing(series, steps=FORECAST_STEPS)
        load_forecasts[rid] = pred

    if not load_forecasts:
        return pd.DataFrame(
            columns=["period", "resist_id", "operation_name", "fact_predict_hierarchical"]
        )

    resist_ids = list(load_forecasts.keys())
    last_values = _get_last_values_per_resist(df, resist_ids)

    # --- Этап 2: Прогноз долей операций ---
    # 2.1 Расчёт исторических долей
    df = df.merge(total_hours.rename(columns={"total_hours": "total_resist_hours"}), on=["resist_id", "period"])
    df["share"] = np.where(
        df["total_resist_hours"] > 0,
        df["operation_hours"] / df["total_resist_hours"],
        0.0,
    )

    share_df = df[["resist_id", "operation_name", "period", "share", "norm_value"]].copy()

    # 2.2 Прогноз долей для каждой пары (resist_id, operation_name)
    share_forecasts: dict[tuple, np.ndarray] = {}
    for (rid, op_name), grp in share_df.groupby(["resist_id", "operation_name"]):
        grp = grp.sort_values("period")
        series = grp.set_index("period")["share"]
        pred = _forecast_exponential_smoothing(series, steps=FORECAST_STEPS)
        share_forecasts[(rid, op_name)] = pred

    # 2.3 Нормализация долей: сумма = 1 для каждого (resist_id, период)
    # Список операций по подразделениям и последний norm_value
    op_by_resist = share_df.groupby("resist_id")["operation_name"].unique().to_dict()
    norm_lookup = (
        df.sort_values("period")
        .groupby(["resist_id", "operation_name"], as_index=False)["norm_value"]
        .last()
    )
    norm_lookup = norm_lookup.set_index(["resist_id", "operation_name"])["norm_value"].to_dict()

    # Для каждого resist_id и каждого из 4 прогнозных периодов — нормализовать доли
    forecast_rows: list[dict] = []
    for rid in resist_ids:
        last_period = last_periods[rid]
        future_periods = _generate_future_periods(last_period, FORECAST_STEPS)
        load_pred = load_forecasts[rid]
        last_row = last_values[last_values["resist_id"] == rid]
        if last_row.empty:
            continue
        staff = float(last_row["staff_count"].iloc[0])
        if staff <= 0:
            continue

        operations = op_by_resist.get(rid, [])
        for step_idx, period in enumerate(future_periods):
            work_hours = _work_hours_for_month(period)
            capacity = staff * work_hours
            if capacity <= 0:
                continue

            load_pct = load_pred[step_idx]
            if not np.isfinite(load_pct) or load_pct < 0:
                load_pct = 0.0
            predicted_total_hours = (load_pct / 100.0) * capacity

            # Собираем сырые доли и нормализуем
            raw_shares: dict[str, float] = {}
            for op_name in operations:
                pred_share = share_forecasts.get((rid, op_name), np.full(FORECAST_STEPS, np.nan))
                s = pred_share[step_idx]
                raw_shares[op_name] = float(s) if np.isfinite(s) and s >= 0 else 0.0

            total_raw = sum(raw_shares.values())
            if total_raw > 0:
                norm_shares = {k: v / total_raw for k, v in raw_shares.items()}
            else:
                n_ops = len(raw_shares) or 1
                norm_shares = {k: 1.0 / n_ops for k in raw_shares}

            # Финальный расчёт по каждой операции
            for op_name, norm_share in norm_shares.items():
                norm_val = norm_lookup.get((rid, op_name), np.nan)
                norm_val = float(norm_val) if np.isfinite(norm_val) and norm_val > 0 else np.nan
                if not np.isfinite(norm_val) or norm_val <= 0:
                    fact_pred = np.nan
                else:
                    predicted_operation_hours = predicted_total_hours * norm_share
                    fact_pred = predicted_operation_hours / norm_val

                forecast_rows.append({
                    "period": period,
                    "resist_id": rid,
                    "operation_name": op_name,
                    "fact_predict_hierarchical": fact_pred,
                })

    if not forecast_rows:
        return pd.DataFrame(
            columns=["period", "resist_id", "operation_name", "fact_predict_hierarchical"]
        )

    forecast_df = pd.DataFrame(forecast_rows)
    forecast_df["fact_predict_hierarchical"] = forecast_df["fact_predict_hierarchical"].clip(lower=0.0)
    return forecast_df


if __name__ == "__main__":
    # Проверка на синтетических данных
    np.random.seed(42)
    n_months = 24
    periods = pd.date_range("2022-01-01", periods=n_months, freq="MS")
    rows = []
    for p in periods:
        for rid in [31, 49]:
            for op_name, norm in [("op_a", 0.5), ("op_b", 1.0), ("op_c", 2.0)]:
                fact = np.random.randint(50, 200) if (rid, op_name) != (31, "op_a") else np.random.randint(5, 30)
                rows.append({
                    "period": p,
                    "resist_id": rid,
                    "operation_name": op_name,
                    "fact_value": float(fact),
                    "norm_value": norm,
                    "staff_count": 10.0,
                    "work_hours_in_month": 168.0,
                })
    hist = pd.DataFrame(rows)
    result = generate_hierarchical_forecast(hist)
    print("Прогноз (первые 15 строк):")
    print(result.head(15).to_string())
    print(f"\nВсего строк прогноза: {len(result)}")
    print(f"Колонки: {list(result.columns)}")
