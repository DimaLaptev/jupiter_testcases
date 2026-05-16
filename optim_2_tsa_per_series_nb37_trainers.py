"""Per-series тренеры (trainers) и реестр конфигураций ``SERIES_CONFIGS``.

Модуль предоставляет production-набор тренеров per ``operation_id``
для прогноза количества операций. Используется через
``optim_2_predict_operation_count_v2`` (копия без семейства ``neuralforecast``).

Семейства моделей (model families):

- ``ets`` — Exponential Smoothing (statsmodels)
- ``theta`` — Theta-model (statsmodels)
- ``sarimax`` — SARIMAX (statsmodels)
- ``auto_arima`` — AutoARIMA (опционально, optional dependency: ``pmdarima``)
- ``statsforecast`` / ``statsforecast_intermittent`` — StatsForecast (опционально)
- ``ucm`` — Unobserved Components Model (statsmodels)
- ``local_supervised`` — sklearn-регрессоры на лагах (lag features)
- ``glm_count`` — GLM Poisson/NegBin
- ``window_median`` — медиана окна (window median, baseline)
"""

from __future__ import annotations

import logging
import warnings
from pandas.errors import PerformanceWarning

warnings.filterwarnings("ignore", category=PerformanceWarning)

import gc
import numpy as np
import pandas as pd

from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.forecasting.theta import ThetaModel
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.statespace.structural import UnobservedComponents as _UnobservedComponents
from statsmodels.genmod.generalized_linear_model import GLM as _GLM
from statsmodels.genmod import families as _glm_families

logger = logging.getLogger(__name__)

HAS_PMDARIMA = True
try:
    import pmdarima
    from pmdarima import auto_arima as _pmdarima_auto_arima
except ImportError:
    HAS_PMDARIMA = False
    _pmdarima_auto_arima = None

HAS_STATSFORECAST = False
_StatsForecast = None
_SF_MODELS: dict = {}
try:
    import statsforecast
    from statsforecast import StatsForecast as _StatsForecast
    from statsforecast.models import (
        ADIDA as _SFM_ADIDA,
        AutoARIMA as _SFM_AutoARIMA,
        AutoCES as _SFM_AutoCES,
        AutoETS as _SFM_AutoETS,
        AutoTheta as _SFM_AutoTheta,
        CrostonSBA as _SFM_CrostonSBA,
        CrostonClassic as _SFM_CrostonClassic,
        DynamicOptimizedTheta as _SFM_DynamicOptimizedTheta,
        HistoricAverage as _SFM_HistoricAverage,
        Holt as _SFM_Holt,
        HoltWinters as _SFM_HoltWinters,
        IMAPA as _SFM_IMAPA,
        MSTL as _SFM_MSTL,
        Naive as _SFM_Naive,
        OptimizedTheta as _SFM_OptimizedTheta,
        RandomWalkWithDrift as _SFM_RandomWalkWithDrift,
        SeasonalNaive as _SFM_SeasonalNaive,
        SimpleExponentialSmoothingOptimized as _SFM_SES_Optimized,
        TSB as _SFM_TSB,
        WindowAverage as _SFM_WindowAverage,
    )
    _SF_MODELS = {
        "AutoETS": _SFM_AutoETS,
        "AutoTheta": _SFM_AutoTheta,
        "AutoCES": _SFM_AutoCES,
        "AutoARIMA": _SFM_AutoARIMA,
        "Naive": _SFM_Naive,
        "SeasonalNaive": _SFM_SeasonalNaive,
        "HistoricAverage": _SFM_HistoricAverage,
        "RandomWalkWithDrift": _SFM_RandomWalkWithDrift,
        "OptimizedTheta": _SFM_OptimizedTheta,
        "DynamicOptimizedTheta": _SFM_DynamicOptimizedTheta,
        "MSTL": _SFM_MSTL,
        "Holt": _SFM_Holt,
        "HoltWinters": _SFM_HoltWinters,
        "SimpleExponentialSmoothingOptimized": _SFM_SES_Optimized,
        "CrostonSBA": _SFM_CrostonSBA,
        "CrostonClassic": _SFM_CrostonClassic,
        "TSB": _SFM_TSB,
        "ADIDA": _SFM_ADIDA,
        "IMAPA": _SFM_IMAPA,
        "WindowAverage": _SFM_WindowAverage,
    }
    HAS_STATSFORECAST = True
except Exception:
    pass

HAS_SKLEARN = False
try:
    from sklearn.linear_model import Ridge as _SK_Ridge, Lasso as _SK_Lasso, ElasticNet as _SK_ElasticNet
    from sklearn.svm import SVR as _SK_SVR
    from sklearn.neighbors import KNeighborsRegressor as _SK_KNN
    from sklearn.ensemble import RandomForestRegressor as _SK_RF
    from sklearn.preprocessing import StandardScaler as _SK_StandardScaler
    HAS_SKLEARN = True
except ImportError:
    _SK_Ridge = _SK_Lasso = _SK_ElasticNet = None
    _SK_SVR = _SK_KNN = _SK_RF = None
    _SK_StandardScaler = None

STATSFORECAST_FREQ = "MS"
MONTHLY_SEASON_LENGTH = 12
INTERMITTENT_ZERO_MIN_FRACTION = 0.15
LOCAL_MAX_LAG = 6


def _statsmodels_module_tag(warning) -> str:
    fn = (getattr(warning, "filename", None) or "").lower()
    if not fn:
        return ""
    if "holtwinters" in fn:
        return "holtwinters"
    if "kalman_filter" in fn:
        return "kalman_filter"
    if "sarimax" in fn:
        return "sarimax"
    if "statespace" in fn:
        return "statespace"
    if "theta" in fn and "forecasting" in fn:
        return "theta"
    return ""


def interpret_warning(msg: str, category) -> str:
    cname = getattr(category, "__name__", str(category))
    s = str(msg).lower()
    if "maximum likelihood optimization failed" in s or "convergence" in cname.lower():
        return (
            "Оптимизация MLE не сошлась: возможны короткая история, экстремальные значения ряда, "
            "плохая масштабируемость или неудачная спецификация модели."
        )
    if "invalid value encountered in scalar add" in s or "aicc" in s:
        return (
            "Численная нестабильность при расчёте AICc; часто следствие плохого фита или NaN/Inf."
        )
    if "overflow encountered in matmul" in s:
        return (
            "Переполнение при оценке ошибок (Holt-Winters): расходимость или экстремальные уровни ряда."
        )
    if "too few observations" in s and "seasonal" in s:
        return "Недостаточно наблюдений для стартовых параметров сезонной части SARIMAX."
    if "invalid value encountered in divide" in s:
        return "Некорректное деление: ноль или NaN; вырожденная дисперсия / нестабильная модель."
    if "runtime" in cname.lower():
        return "RuntimeWarning: деление на ноль, переполнение или NaN в вычислениях."
    if "sklearn" in (getattr(category, "__module__", "") or ""):
        return "Sklearn: не сходимость итераций или плохо обусловленные признаки."
    return (
        "См. текст сообщения; типично: короткий или нестабильный ряд, экстремальные значения, "
        "численная неустойчивость."
    )


def append_warning_rows(
    rows: list,
    *,
    resist_id,
    operation_id,
    model_kind: str,
    model_label: str,
    phase: str,
    n_train_points,
    caught,
):
    for w in caught:
        msg = str(w.message)
        cat = w.category
        if issubclass(cat, PerformanceWarning):
            continue
        fn = (getattr(w, "filename", None) or "").lower()
        interp = interpret_warning(msg, cat)
        if "invalid value encountered in divide" in str(msg).lower() and "kalman" in fn:
            interp = (
                "Некорректное деление в фильтре Калмана: вырожденная дисперсия / NaN в state space."
            )
        rows.append(
            {
                "resist_id": resist_id,
                "operation_id": operation_id,
                "model_kind": model_kind,
                "model_label": model_label,
                "phase": phase,
                "warning_category": getattr(cat, "__name__", str(cat)),
                "message": msg,
                "interpretation": interp,
                "n_train_points": n_train_points if model_kind == "per_series" else "",
                "statsmodels_module": _statsmodels_module_tag(w),
            }
        )


def cleanup_memory() -> None:
    """Очистка памяти после обучения модели для предотвращения утечек."""
    gc.collect()


def _is_single_op(df_full: pd.DataFrame) -> bool:
    """Fast-path predicate: ровно один ``operation_id`` в ``df_full``."""
    op_col = df_full["operation_id"].to_numpy()
    if op_col.size == 0:
        return False
    return pd.unique(op_col).size == 1


def _single_op_inputs(
    df_full: pd.DataFrame,
    mask_train: pd.Series,
    mask_test: pd.Series,
):
    """Подготовка single-op данных.

    Возвращает кортеж ``(op_id, y_hist, n_fc, n_tr)``. Сортирует по ``date`` только
    если ряд (series) ещё не отсортирован — production-вызов уже передаёт
    sorted-данные.
    """
    if df_full["date"].is_monotonic_increasing:
        df = df_full
        mt = mask_train
        mts = mask_test
    else:
        df = df_full.sort_values("date")
        mt = mask_train.reindex(df.index, fill_value=False)
        mts = mask_test.reindex(df.index, fill_value=False)
    op_id = df["operation_id"].iat[0]
    y_hist = df.loc[mt, "fact_value"].astype(float).to_numpy()
    n_fc = int(np.asarray(mts, dtype=bool).sum())
    n_tr = int(y_hist.shape[0])
    return op_id, y_hist, n_fc, n_tr


def _empty_test_arr(mask_test: pd.Series) -> np.ndarray:
    """Возврат для случая ``n_fc == 0``: длина = ``mask_test.sum()`` (обычно 0)."""
    return np.zeros(int(np.asarray(mask_test, dtype=bool).sum()), dtype=float)


def _run_per_series_dispatch(
    df_full: pd.DataFrame,
    mask_train: pd.Series,
    mask_test: pd.Series,
    fit_predict,
) -> np.ndarray:
    """Универсальная диспетчеризация (universal dispatch) single-op vs multi-op.

    ``fit_predict`` принимает ``(y_hist, n_fc, op_id, n_tr)`` и возвращает массив
    прогноза длиной ``n_fc``. Исключения внутри ``fit_predict`` падают в fallback
    «среднее по истории» — поведение совместимо со старой реализацией.
    """
    if _is_single_op(df_full):
        op_id, y_hist, n_fc, n_tr = _single_op_inputs(df_full, mask_train, mask_test)
        if n_fc == 0:
            return _empty_test_arr(mask_test)
        try:
            fc = fit_predict(y_hist, n_fc, op_id, n_tr)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        return np.maximum(np.asarray(fc, dtype=float).ravel(), 0)

    test_idx = df_full.loc[mask_test].index
    preds = np.zeros(len(test_idx), dtype=float)
    if len(test_idx) == 0:
        return preds
    pos_map = {idx: i for i, idx in enumerate(test_idx)}
    for op_id, grp in df_full.groupby("operation_id", sort=False):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].astype(float).to_numpy()
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            fc = fit_predict(y_hist, n_fc, op_id, n_tr)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        fc_clamped = np.maximum(np.asarray(fc, dtype=float).ravel(), 0)
        for i, idx in enumerate(test_part.index):
            preds[pos_map[idx]] = fc_clamped[i]
    return preds


def _append_split_warnings(
    warning_rows,
    *,
    resist_id,
    operation_id,
    series_config_name,
    n_tr,
    wlog,
    n_first,
    phase_first: str,
    phase_second: str,
) -> None:
    """Разделяет один общий ``catch_warnings`` лог на две фазы."""
    if n_first > 0:
        append_warning_rows(
            warning_rows,
            resist_id=resist_id,
            operation_id=operation_id,
            model_kind="per_series",
            model_label=series_config_name,
            phase=phase_first,
            n_train_points=n_tr,
            caught=wlog[:n_first],
        )
    rest = wlog[n_first:]
    if rest:
        append_warning_rows(
            warning_rows,
            resist_id=resist_id,
            operation_id=operation_id,
            model_kind="per_series",
            model_label=series_config_name,
            phase=phase_second,
            n_train_points=n_tr,
            caught=rest,
        )


def train_ets_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    trend="add",
    damped_trend=False,
    seasonal=None,
    seasonal_periods=None,
    ets_fit_kwargs=None,
):
    def _fit_predict(y_hist, n_fc, op_id, n_tr):
        if seasonal is not None and seasonal_periods is not None:
            min_hist = max(4, 2 * int(seasonal_periods))
            if len(y_hist) < min_hist:
                raise ValueError("too short for seasonal")
        elif len(y_hist) < 4:
            raise ValueError("too short")
        if trend == "mul" and np.any(y_hist <= 0):
            raise ValueError("mul trend requires positive series")
        if seasonal == "mul" and np.any(y_hist <= 0):
            raise ValueError("mul seasonal requires positive series")
        model = ExponentialSmoothing(
            y_hist,
            trend=trend,
            damped_trend=damped_trend,
            seasonal=seasonal,
            seasonal_periods=seasonal_periods if seasonal is not None else None,
        )
        _fit_kw = {"optimized": True, "use_brute": False}
        if ets_fit_kwargs:
            _fit_kw.update(ets_fit_kwargs)
        with warnings.catch_warnings(record=True) as wlog:
            warnings.simplefilter("always")
            fit = model.fit(**_fit_kw)
            n_fit = len(wlog)
            fc = fit.forecast(n_fc)
        _append_split_warnings(
            warning_rows,
            resist_id=resist_id,
            operation_id=op_id,
            series_config_name=series_config_name,
            n_tr=n_tr,
            wlog=wlog,
            n_first=n_fit,
            phase_first="fit",
            phase_second="forecast",
        )
        return np.asarray(fc, dtype=float).ravel()

    return _run_per_series_dispatch(df_full, mask_train, mask_test, _fit_predict)


def train_theta_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    theta_deseasonalize=True,
    theta_method="auto",
    theta_period=12,
):
    def _fit_predict(y_hist, n_fc, op_id, n_tr):
        if len(y_hist) < 4:
            raise ValueError("too short")
        if theta_method == "multiplicative" and np.any(y_hist <= 0):
            raise ValueError("theta multiplicative requires positive series")
        tm = ThetaModel(
            y_hist,
            period=int(theta_period),
            deseasonalize=theta_deseasonalize,
            method=theta_method,
        )
        with warnings.catch_warnings(record=True) as wlog:
            warnings.simplefilter("always")
            res = tm.fit()
            n_fit = len(wlog)
            fc = res.forecast(n_fc)
        _append_split_warnings(
            warning_rows,
            resist_id=resist_id,
            operation_id=op_id,
            series_config_name=series_config_name,
            n_tr=n_tr,
            wlog=wlog,
            n_first=n_fit,
            phase_first="fit",
            phase_second="forecast",
        )
        return np.asarray(fc, dtype=float).ravel()

    return _run_per_series_dispatch(df_full, mask_train, mask_test, _fit_predict)


def train_sarimax_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    sarimax_preset="default",
    sarimax_order=None,
    sarimax_seasonal_order=None,
    sarimax_fit_kwargs=None,
):
    def _fit_predict(y_hist, n_fc, op_id, n_tr):
        if len(y_hist) < 8:
            raise ValueError("too short")
        if sarimax_order is not None and sarimax_seasonal_order is not None:
            order = tuple(sarimax_order)
            seasonal_order = tuple(sarimax_seasonal_order)
        elif len(y_hist) >= 24:
            if sarimax_preset == "airline":
                order = (0, 1, 1)
                seasonal_order = (0, 1, 1, 12)
            else:
                order = (1, 1, 1)
                seasonal_order = (1, 1, 1, 12)
        else:
            order = (1, 1, 1)
            seasonal_order = (0, 0, 0, 0)
        model = SARIMAX(
            y_hist,
            order=order,
            seasonal_order=seasonal_order,
            enforce_stationarity=False,
            enforce_invertibility=False,
        )
        _sfk = {"disp": False}
        if sarimax_fit_kwargs:
            _sfk.update(sarimax_fit_kwargs)
        with warnings.catch_warnings(record=True) as wlog:
            warnings.simplefilter("always")
            fit = model.fit(**_sfk)
            n_fit = len(wlog)
            fc = fit.forecast(n_fc)
        _append_split_warnings(
            warning_rows,
            resist_id=resist_id,
            operation_id=op_id,
            series_config_name=series_config_name,
            n_tr=n_tr,
            wlog=wlog,
            n_first=n_fit,
            phase_first="fit",
            phase_second="forecast",
        )
        return np.asarray(fc, dtype=float).ravel()

    return _run_per_series_dispatch(df_full, mask_train, mask_test, _fit_predict)


def train_auto_arima_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    auto_arima_kwargs=None,
):
    if _pmdarima_auto_arima is None:
        raise ImportError("pmdarima не установлен")
    base_kw = dict(
        seasonal=True,
        m=12,
        suppress_warnings=False,
        error_action="ignore",
        stepwise=True,
        max_p=3,
        max_q=3,
        max_P=2,
        max_Q=2,
    )
    if auto_arima_kwargs:
        base_kw.update(auto_arima_kwargs)

    def _fit_predict(y_hist, n_fc, op_id, n_tr):
        if len(y_hist) < 8:
            raise ValueError("too short")
        with warnings.catch_warnings(record=True) as wlog:
            warnings.simplefilter("always")
            aa = _pmdarima_auto_arima(y_hist, **base_kw)
            n_fit = len(wlog)
            fc = aa.predict(n_periods=n_fc)
        _append_split_warnings(
            warning_rows,
            resist_id=resist_id,
            operation_id=op_id,
            series_config_name=series_config_name,
            n_tr=n_tr,
            wlog=wlog,
            n_first=n_fit,
            phase_first="fit",
            phase_second="predict",
        )
        return np.asarray(fc, dtype=float).ravel()

    return _run_per_series_dispatch(df_full, mask_train, mask_test, _fit_predict)


def _sf_train_df(train_part: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "unique_id": "s0",
            "ds": pd.to_datetime(train_part["date"]),
            "y": train_part["fact_value"].values.astype(float),
        }
    )


def _sf_forecast_column(fc_df: pd.DataFrame) -> np.ndarray:
    meta = {"unique_id", "ds"}
    num_cols = [c for c in fc_df.columns if c not in meta]
    if not num_cols:
        raise ValueError("statsforecast: нет колонки прогноза")
    return fc_df[num_cols[0]].values.astype(float)


_SF_NO_SEASON = {
    "Naive", "HistoricAverage", "RandomWalkWithDrift", "Holt",
    "SimpleExponentialSmoothingOptimized", "CrostonSBA", "CrostonClassic",
    "ADIDA", "IMAPA",
}


def _sf_build_model_list(sf_model_name: str, season_len: int, sf_window_size=None, tsb_kwargs=None):
    """Конструктор моделей StatsForecast.

    Импорты подняты в module-scope; ошибка `ImportError` при отсутствии
    ``statsforecast`` поднимается отдельно во внешних трейнерах.
    """
    cls = _SF_MODELS.get(sf_model_name)
    if cls is None:
        raise ValueError(f"Неизвестная модель StatsForecast: {sf_model_name}")
    if sf_model_name == "TSB":
        kw = {"alpha_d": 0.3, "alpha_p": 0.3}
        if tsb_kwargs:
            kw.update(tsb_kwargs)
        return [cls(**kw)]
    if sf_model_name == "WindowAverage":
        ws = int(sf_window_size) if sf_window_size is not None else 3
        ws = max(1, ws)
        return [cls(window_size=ws)]
    if sf_model_name in _SF_NO_SEASON:
        return [cls()]
    return [cls(season_length=season_len)]


def _sf_train_df_from_arrays(y_hist: np.ndarray, dates_ms) -> pd.DataFrame:
    """Сборка DataFrame под `StatsForecast.fit` из numpy/Index без копирования."""
    return pd.DataFrame(
        {
            "unique_id": "s0",
            "ds": pd.to_datetime(dates_ms),
            "y": y_hist.astype(float, copy=False),
        }
    )


def train_statsforecast_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    sf_model_name: str,
    season_len: int,
    sf_window_size=None,
    sf_tsb_kwargs=None,
):
    if _StatsForecast is None:
        raise ImportError("statsforecast не установлен")

    def _fit_predict_with_dates(y_hist, n_fc, op_id, n_tr, dates_ms):
        if n_tr < 2:
            raise ValueError("too short")
        sf_df = _sf_train_df_from_arrays(y_hist, dates_ms)
        models = _sf_build_model_list(sf_model_name, season_len, sf_window_size, tsb_kwargs=sf_tsb_kwargs)
        with warnings.catch_warnings(record=True) as wlog:
            warnings.simplefilter("always")
            sf = _StatsForecast(models=models, freq=STATSFORECAST_FREQ, n_jobs=1)
            sf.fit(sf_df)
            n_fit = len(wlog)
            fc_df = sf.predict(h=n_fc)
        _append_split_warnings(
            warning_rows,
            resist_id=resist_id,
            operation_id=op_id,
            series_config_name=series_config_name,
            n_tr=n_tr,
            wlog=wlog,
            n_first=n_fit,
            phase_first="fit",
            phase_second="predict",
        )
        fc = _sf_forecast_column(fc_df)
        if fc.shape[0] != n_fc:
            fc = fc[:n_fc] if fc.shape[0] > n_fc else np.resize(fc, n_fc)
        return fc

    if _is_single_op(df_full):
        op_id, y_hist, n_fc, n_tr = _single_op_inputs(df_full, mask_train, mask_test)
        if n_fc == 0:
            return _empty_test_arr(mask_test)
        if df_full["date"].is_monotonic_increasing:
            dates = df_full.loc[mask_train, "date"].to_numpy()
        else:
            df_sorted = df_full.sort_values("date")
            mt = mask_train.reindex(df_sorted.index, fill_value=False)
            dates = df_sorted.loc[mt, "date"].to_numpy()
        try:
            fc = _fit_predict_with_dates(y_hist, n_fc, op_id, n_tr, dates)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        return np.maximum(np.asarray(fc, dtype=float).ravel(), 0)

    test_idx = df_full.loc[mask_test].index
    preds = np.zeros(len(test_idx), dtype=float)
    if len(test_idx) == 0:
        return preds
    pos_map = {idx: i for i, idx in enumerate(test_idx)}
    for op_id, grp in df_full.groupby("operation_id", sort=False):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].astype(float).to_numpy()
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            fc = _fit_predict_with_dates(y_hist, n_fc, op_id, n_tr, train_part["date"].to_numpy())
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        fc_clamped = np.maximum(np.asarray(fc, dtype=float).ravel(), 0)
        for i, idx in enumerate(test_part.index):
            preds[pos_map[idx]] = fc_clamped[i]
    return preds


def train_statsforecast_intermittent_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    sf_model_name: str,
    season_len: int,
    sf_tsb_kwargs=None,
):
    if _StatsForecast is None:
        raise ImportError("statsforecast не установлен")

    def _fit_predict_with_dates(y_hist, n_fc, op_id, n_tr, dates_ms):
        if n_tr < 2:
            raise ValueError("too short")
        zero_frac = float(np.mean(y_hist == 0)) if n_tr else 0.0
        use_intermittent = zero_frac >= INTERMITTENT_ZERO_MIN_FRACTION
        sf_df = _sf_train_df_from_arrays(y_hist, dates_ms)
        if use_intermittent:
            models = _sf_build_model_list(sf_model_name, season_len, None, tsb_kwargs=sf_tsb_kwargs)
        else:
            models = _sf_build_model_list("HistoricAverage", season_len, None)
        with warnings.catch_warnings(record=True) as wlog:
            warnings.simplefilter("always")
            sf = _StatsForecast(models=models, freq=STATSFORECAST_FREQ, n_jobs=1)
            sf.fit(sf_df)
            n_fit = len(wlog)
            fc_df = sf.predict(h=n_fc)
        _append_split_warnings(
            warning_rows,
            resist_id=resist_id,
            operation_id=op_id,
            series_config_name=series_config_name,
            n_tr=n_tr,
            wlog=wlog,
            n_first=n_fit,
            phase_first="fit",
            phase_second="predict",
        )
        fc = _sf_forecast_column(fc_df)
        if fc.shape[0] != n_fc:
            fc = fc[:n_fc] if fc.shape[0] > n_fc else np.resize(fc, n_fc)
        return fc

    if _is_single_op(df_full):
        op_id, y_hist, n_fc, n_tr = _single_op_inputs(df_full, mask_train, mask_test)
        if n_fc == 0:
            return _empty_test_arr(mask_test)
        if df_full["date"].is_monotonic_increasing:
            dates = df_full.loc[mask_train, "date"].to_numpy()
        else:
            df_sorted = df_full.sort_values("date")
            mt = mask_train.reindex(df_sorted.index, fill_value=False)
            dates = df_sorted.loc[mt, "date"].to_numpy()
        try:
            fc = _fit_predict_with_dates(y_hist, n_fc, op_id, n_tr, dates)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        return np.maximum(np.asarray(fc, dtype=float).ravel(), 0)

    test_idx = df_full.loc[mask_test].index
    preds = np.zeros(len(test_idx), dtype=float)
    if len(test_idx) == 0:
        return preds
    pos_map = {idx: i for i, idx in enumerate(test_idx)}
    for op_id, grp in df_full.groupby("operation_id", sort=False):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].astype(float).to_numpy()
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            fc = _fit_predict_with_dates(y_hist, n_fc, op_id, n_tr, train_part["date"].to_numpy())
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        fc_clamped = np.maximum(np.asarray(fc, dtype=float).ravel(), 0)
        for i, idx in enumerate(test_part.index):
            preds[pos_map[idx]] = fc_clamped[i]
    return preds


def train_ucm_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    ucm_level="local linear trend",
    ucm_stochastic_level=None,
    ucm_stochastic_seasonal=None,
):
    def _fit_predict(y_hist, n_fc, op_id, n_tr):
        if n_tr < 2 * MONTHLY_SEASON_LENGTH:
            raise ValueError("too short for seasonal UCM")
        _uk = {"level": ucm_level, "seasonal": MONTHLY_SEASON_LENGTH}
        if ucm_stochastic_level is not None:
            _uk["stochastic_level"] = ucm_stochastic_level
        if ucm_stochastic_seasonal is not None:
            _uk["stochastic_seasonal"] = ucm_stochastic_seasonal
        mod = _UnobservedComponents(y_hist, **_uk)
        with warnings.catch_warnings(record=True) as wlog:
            warnings.simplefilter("always")
            res = mod.fit(disp=False)
            n_fit = len(wlog)
            fc = res.forecast(n_fc)
        _append_split_warnings(
            warning_rows,
            resist_id=resist_id,
            operation_id=op_id,
            series_config_name=series_config_name,
            n_tr=n_tr,
            wlog=wlog,
            n_first=n_fit,
            phase_first="fit",
            phase_second="forecast",
        )
        return np.asarray(fc, dtype=float).ravel()

    return _run_per_series_dispatch(df_full, mask_train, mask_test, _fit_predict)


def _local_effective_max_lag(n_train: int, max_lag: int) -> int:
    if n_train < 3:
        return 1
    return max(1, min(max_lag, n_train - 2))


def _local_build_xy(y_arr: np.ndarray, max_lag: int):
    y_arr = np.asarray(y_arr, dtype=float)
    X, y_t = [], []
    for t in range(max_lag, len(y_arr)):
        X.append([y_arr[t - j] for j in range(1, max_lag + 1)])
        y_t.append(y_arr[t])
    return np.array(X, dtype=float), np.array(y_t, dtype=float)


def _local_recursive_forecast(model, scaler, y_hist: np.ndarray, n_fc: int, max_lag: int, use_scaler: bool):
    history = list(np.asarray(y_hist, dtype=float))
    fc = []
    fallback = float(np.mean(history)) if history else 0.0
    for _ in range(n_fc):
        if len(history) < max_lag:
            pred = fallback
        else:
            xrow = np.array([[history[-j] for j in range(1, max_lag + 1)]])
            if use_scaler and scaler is not None:
                xrow = scaler.transform(xrow)
            pred = float(model.predict(xrow)[0])
        fc.append(pred)
        history.append(pred)
    return np.array(fc, dtype=float)


def train_local_supervised_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    sk_model: str,
    max_lag: int = None,
    local_sk_params=None,
):
    if not HAS_SKLEARN:
        raise ImportError("sklearn не установлен")
    if max_lag is None:
        max_lag = LOCAL_MAX_LAG

    def _fit_predict(y_hist, n_fc, op_id, n_tr):
        L = _local_effective_max_lag(n_tr, max_lag)
        use_scaler = sk_model in ("svr", "knn")
        X, y_tgt = _local_build_xy(y_hist, L)
        if X.shape[0] < 2:
            raise ValueError("too few supervised rows")
        scaler = _SK_StandardScaler() if use_scaler else None
        X_fit = scaler.fit_transform(X) if use_scaler else X
        _p = dict(local_sk_params or {})
        if sk_model == "ridge":
            model = _SK_Ridge(alpha=float(_p.get("alpha", 1.0)))
        elif sk_model == "lasso":
            model = _SK_Lasso(
                alpha=float(_p.get("alpha", 0.15)),
                random_state=int(_p.get("random_state", 42)),
                max_iter=int(_p.get("max_iter", 8000)),
            )
        elif sk_model == "elasticnet":
            model = _SK_ElasticNet(
                alpha=float(_p.get("alpha", 0.15)),
                l1_ratio=float(_p.get("l1_ratio", 0.5)),
                random_state=int(_p.get("random_state", 42)),
                max_iter=int(_p.get("max_iter", 8000)),
            )
        elif sk_model == "svr":
            model = _SK_SVR(
                kernel=_p.get("kernel", "rbf"),
                C=float(_p.get("C", 1.0)),
                epsilon=float(_p.get("epsilon", 0.1)),
                gamma=_p.get("gamma", "scale"),
            )
        elif sk_model == "knn":
            nn = int(_p.get("n_neighbors", max(1, min(5, max(1, X_fit.shape[0] // 3)))))
            model = _SK_KNN(
                n_neighbors=max(1, nn),
                weights=_p.get("weights", "distance"),
            )
        elif sk_model == "rf":
            model = _SK_RF(
                n_estimators=int(_p.get("n_estimators", min(200, max(50, n_tr * 5)))),
                max_depth=int(_p.get("max_depth", min(6, max(2, max(1, n_tr // 3))))),
                min_samples_leaf=int(_p.get("min_samples_leaf", max(1, min(3, max(1, n_tr // 5))))),
                random_state=int(_p.get("random_state", 42)),
                n_jobs=int(_p.get("n_jobs", -1)),
            )
        else:
            raise ValueError(sk_model)
        with warnings.catch_warnings(record=True) as wlog:
            warnings.simplefilter("always")
            model.fit(X_fit, y_tgt)
        append_warning_rows(
            warning_rows,
            resist_id=resist_id,
            operation_id=op_id,
            model_kind="per_series",
            model_label=series_config_name,
            phase="fit",
            n_train_points=n_tr,
            caught=wlog,
        )
        return _local_recursive_forecast(model, scaler, y_hist, n_fc, L, use_scaler)

    return _run_per_series_dispatch(df_full, mask_train, mask_test, _fit_predict)


def _glm_build_xy_count(y_arr: np.ndarray):
    y_arr = np.maximum(np.round(np.asarray(y_arr, dtype=float)), 0)
    exog = []
    endog = []
    for t in range(1, len(y_arr)):
        exog.append([1.0, float(y_arr[t - 1])])
        endog.append(float(y_arr[t]))
    return np.array(exog, dtype=float), np.array(endog, dtype=float)


def train_glm_count_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    family_name: str,
    glm_fit_kwargs=None,
    glm_use_regularized: bool = False,
    glm_reg_alpha: float = 0.1,
    glm_reg_l1_wt: float = 0.0,
):
    fam = _glm_families.Poisson() if family_name == "poisson" else _glm_families.NegativeBinomial()

    def _fit_predict(y_hist, n_fc, op_id, n_tr):
        if n_tr < 4:
            raise ValueError("too short")
        exog_tr, endog_tr = _glm_build_xy_count(y_hist)
        if exog_tr.shape[0] < 3:
            raise ValueError("too few glm rows")
        with warnings.catch_warnings(record=True) as wlog:
            warnings.simplefilter("always")
            glm = _GLM(endog_tr, exog_tr, family=fam)
            if glm_use_regularized:
                res = glm.fit_regularized(
                    alpha=float(glm_reg_alpha),
                    L1_wt=float(glm_reg_l1_wt),
                    maxiter=int((glm_fit_kwargs or {}).get("maxiter", 100)),
                )
            else:
                _gkw = {}
                if glm_fit_kwargs:
                    _gkw.update(glm_fit_kwargs)
                res = glm.fit(**_gkw)
        append_warning_rows(
            warning_rows,
            resist_id=resist_id,
            operation_id=op_id,
            model_kind="per_series",
            model_label=series_config_name,
            phase="fit",
            n_train_points=n_tr,
            caught=wlog,
        )
        history = list(np.maximum(np.round(y_hist), 0).astype(float))
        fc = []
        for _ in range(n_fc):
            x1 = np.array([[1.0, history[-1]]])
            mu = float(np.squeeze(res.predict(x1)))
            pred = max(0.0, mu)
            fc.append(pred)
            history.append(float(max(0, round(pred))))
        return np.array(fc, dtype=float)

    return _run_per_series_dispatch(df_full, mask_train, mask_test, _fit_predict)


def train_window_median_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    window_size: int,
):
    def _fit_predict(y_hist, n_fc, op_id, n_tr):
        history = list(y_hist)
        fc = []
        for _ in range(n_fc):
            tail = history[-window_size:] if len(history) >= window_size else history
            if len(tail) == 0:
                fc.append(0.0)
            else:
                fc.append(float(np.median(tail)))
            history.append(fc[-1])
        return np.array(fc, dtype=float)

    return _run_per_series_dispatch(df_full, mask_train, mask_test, _fit_predict)


# Базовые per-series configs — основной production-набор.
SERIES_CONFIGS = {
    "ETS-add": {"fn": "ets", "trend": "add", "damped_trend": False, "seasonal": None, "seasonal_periods": None},
    "ETS-damped": {"fn": "ets", "trend": "add", "damped_trend": True, "seasonal": None, "seasonal_periods": None},
    "ETS-seasonal-add": {
        "fn": "ets",
        "trend": "add",
        "damped_trend": False,
        "seasonal": "add",
        "seasonal_periods": 12,
    },
    "ETS-seasonal-damped": {
        "fn": "ets",
        "trend": "add",
        "damped_trend": True,
        "seasonal": "add",
        "seasonal_periods": 12,
    },
    "ETS-mul-trend": {"fn": "ets", "trend": "mul", "damped_trend": False, "seasonal": None, "seasonal_periods": None},
    "ETS-seasonal-mul": {
        "fn": "ets",
        "trend": "add",
        "damped_trend": False,
        "seasonal": "mul",
        "seasonal_periods": 12,
    },
    "ETS-mul-trend-mul-seasonal": {
        "fn": "ets",
        "trend": "mul",
        "damped_trend": False,
        "seasonal": "mul",
        "seasonal_periods": 12,
    },
    "ETS-mul-trend-add-seasonal": {
        "fn": "ets",
        "trend": "mul",
        "damped_trend": False,
        "seasonal": "add",
        "seasonal_periods": 12,
    },
    "Theta-default": {"fn": "theta"},
    "SARIMAX-default": {"fn": "sarimax"},
    "SARIMAX-airline": {"fn": "sarimax", "sarimax_preset": "airline"},
}
if HAS_PMDARIMA:
    SERIES_CONFIGS["AutoARIMA"] = {"fn": "auto_arima"}
    SERIES_CONFIGS["AutoARIMA-nonseasonal"] = {
        "fn": "auto_arima",
        "auto_arima_kwargs": {"seasonal": False, "m": 1},
    }
    SERIES_CONFIGS["AutoARIMA-BIC"] = {
        "fn": "auto_arima",
        "auto_arima_kwargs": {"information_criterion": "bic"},
    }

if HAS_STATSFORECAST:
    _sl = MONTHLY_SEASON_LENGTH
    SERIES_CONFIGS.update(
        {
            "SF-AutoETS": {"fn": "statsforecast", "sf_model": "AutoETS", "season_len": _sl},
            "SF-AutoTheta": {"fn": "statsforecast", "sf_model": "AutoTheta", "season_len": _sl},
            "SF-AutoCES": {"fn": "statsforecast", "sf_model": "AutoCES", "season_len": _sl},
            "SF-AutoARIMA": {"fn": "statsforecast", "sf_model": "AutoARIMA", "season_len": _sl},
            "SF-Naive": {"fn": "statsforecast", "sf_model": "Naive", "season_len": _sl},
            "SF-SeasonalNaive": {"fn": "statsforecast", "sf_model": "SeasonalNaive", "season_len": _sl},
            "SF-RandomWalkWithDrift": {"fn": "statsforecast", "sf_model": "RandomWalkWithDrift", "season_len": _sl},
            "SF-OptimizedTheta": {"fn": "statsforecast", "sf_model": "OptimizedTheta", "season_len": _sl},
            "SF-DynamicOptimizedTheta": {"fn": "statsforecast", "sf_model": "DynamicOptimizedTheta", "season_len": _sl},
            "SF-MSTL": {"fn": "statsforecast", "sf_model": "MSTL", "season_len": _sl},
            "SF-Holt": {"fn": "statsforecast", "sf_model": "Holt", "season_len": _sl},
            "SF-HoltWinters": {"fn": "statsforecast", "sf_model": "HoltWinters", "season_len": _sl},
            "SF-SES-Optimized": {
                "fn": "statsforecast",
                "sf_model": "SimpleExponentialSmoothingOptimized",
                "season_len": _sl,
            },
            "SF-CrostonSBA": {"fn": "statsforecast_intermittent", "sf_model": "CrostonSBA", "season_len": _sl},
            "SF-CrostonClassic": {"fn": "statsforecast_intermittent", "sf_model": "CrostonClassic", "season_len": _sl},
            "SF-TSB": {"fn": "statsforecast_intermittent", "sf_model": "TSB", "season_len": _sl},
            "SF-ADIDA": {"fn": "statsforecast_intermittent", "sf_model": "ADIDA", "season_len": _sl},
            "SF-IMAPA": {"fn": "statsforecast_intermittent", "sf_model": "IMAPA", "season_len": _sl},
        }
    )

SERIES_CONFIGS["UCM-local-level-seasonal"] = {
    "fn": "ucm",
    "ucm_level": "local level",
}


SERIES_CONFIGS.update(
    {
        "Local-Ridge": {"fn": "local_supervised", "sk_model": "ridge"},
        "Local-Lasso": {"fn": "local_supervised", "sk_model": "lasso"},
        "Local-ElasticNet": {"fn": "local_supervised", "sk_model": "elasticnet"},
        "Local-SVR": {"fn": "local_supervised", "sk_model": "svr"},
        "Local-KNN": {"fn": "local_supervised", "sk_model": "knn"},
        "Local-RandomForest": {"fn": "local_supervised", "sk_model": "rf"},
        "GLM-Poisson": {"fn": "glm_count", "family": "poisson"},
        "WindowMedian-3": {"fn": "window_median", "window_size": 3},
        "WindowMedian-6": {"fn": "window_median", "window_size": 6},
    }
)
if HAS_STATSFORECAST:
    _sl2 = MONTHLY_SEASON_LENGTH
    SERIES_CONFIGS["SF-WindowAverage-3"] = {
        "fn": "statsforecast",
        "sf_model": "WindowAverage",
        "season_len": _sl2,
        "sf_window_size": 3,
    }
    SERIES_CONFIGS["SF-WindowAverage-6"] = {
        "fn": "statsforecast",
        "sf_model": "WindowAverage",
        "season_len": _sl2,
        "sf_window_size": 6,
    }


# Расширенный набор per-series: ключ ``SERIES_CONFIGS`` — уникальное имя для метрик; регистрация дополнительных конфигов выполняется в
# ``_register_fn_family_extras`` ниже.

def _register_fn_family_extras(sc: dict, ctx: dict) -> None:
    """Register extra per-family configs into ``sc`` (mutates the dict).

    ctx keys: ``MONTHLY_SEASON_LENGTH``, ``HAS_PMDARIMA``, ``HAS_STATSFORECAST`` —
    feature flags для condition-регистрации (conditional registration) опциональных семейств.
    """
    sl = ctx["MONTHLY_SEASON_LENGTH"]
    _ets_base = {
        "fn": "ets",
        "trend": "add",
        "damped_trend": False,
        "seasonal": None,
        "seasonal_periods": None,
    }
    for name, cfg in [
        ("ETS-add-brute-search", {"ets_fit_kwargs": {"use_brute": True}}),
        ("ETS-add-optimizer-lbfgs", {"ets_fit_kwargs": {"method": "lbfgs"}}),
        ("ETS-add-remove-bias", {"ets_fit_kwargs": {"remove_bias": True}}),
        ("ETS-no-trend-no-season", {"trend": None, "damped_trend": False, "seasonal": None, "seasonal_periods": None}),
        ("ETS-add-seasonal-period-6", {"trend": "add", "damped_trend": False, "seasonal": "add", "seasonal_periods": 6}),
        ("ETS-add-seasonal-period-4", {"trend": "add", "damped_trend": False, "seasonal": "add", "seasonal_periods": 4}),
        (
            "ETS-damped-add-seasonal-12-brute",
            {
                "trend": "add",
                "damped_trend": True,
                "seasonal": "add",
                "seasonal_periods": 12,
                "ets_fit_kwargs": {"use_brute": True},
            },
        ),
    ]:
        sc[name] = {**_ets_base, **cfg}

    for name, cfg in [
        ("Theta-period-6-deseason-auto", {"theta_period": 6}),
        ("Theta-period-4-deseason-auto", {"theta_period": 4}),
        ("Theta-period-3-deseason-auto", {"theta_period": 3}),
        ("Theta-additive-no-deseason", {"theta_deseasonalize": False, "theta_method": "additive"}),
        ("Theta-period-8-deseason-auto", {"theta_period": 8}),
    ]:
        base = {"fn": "theta", "theta_deseasonalize": True, "theta_method": "auto", "theta_period": 12}
        base.update(cfg)
        sc[name] = base

    for name, cfg in [
        (
            "SARIMAX-order-011-season-011-m12",
            {"sarimax_order": (0, 1, 1), "sarimax_seasonal_order": (0, 1, 1, 12)},
        ),
        (
            "SARIMAX-order-101-season-101-m12",
            {"sarimax_order": (1, 0, 1), "sarimax_seasonal_order": (1, 0, 1, 12)},
        ),
        (
            "SARIMAX-order-210-nonseasonal",
            {"sarimax_order": (2, 1, 0), "sarimax_seasonal_order": (0, 0, 0, 0)},
        ),
        (
            "SARIMAX-order-110-season-110-m12",
            {"sarimax_order": (1, 1, 0), "sarimax_seasonal_order": (1, 1, 0, 12)},
        ),
        (
            "SARIMAX-order-012-season-011-m12",
            {"sarimax_order": (0, 1, 2), "sarimax_seasonal_order": (0, 1, 1, 12)},
        ),
        (
            "SARIMAX-order-111-nonseasonal",
            {"sarimax_order": (1, 1, 1), "sarimax_seasonal_order": (0, 0, 0, 0)},
        ),
        ("SARIMAX-default-maxiter-200", {"sarimax_fit_kwargs": {"maxiter": 200}}),
        (
            "SARIMAX-order-100-season-100-m12",
            {"sarimax_order": (1, 0, 0), "sarimax_seasonal_order": (1, 0, 0, 12)},
        ),
        (
            "SARIMAX-order-221-nonseasonal",
            {"sarimax_order": (2, 2, 1), "sarimax_seasonal_order": (0, 0, 0, 0)},
        ),
        (
            "SARIMAX-order-011-season-111-m6",
            {"sarimax_order": (0, 1, 1), "sarimax_seasonal_order": (1, 1, 1, 6)},
        ),
    ]:
        base = {"fn": "sarimax", "sarimax_preset": "default"}
        base.update(cfg)
        sc[name] = base

    if ctx["HAS_PMDARIMA"]:
        for name, cfg in [
            ("AutoARIMA-stepwise-off", {"auto_arima_kwargs": {"stepwise": False}}),
            ("AutoARIMA-no-approximation", {"auto_arima_kwargs": {"approximation": False}}),
            ("AutoARIMA-ic-aicc", {"auto_arima_kwargs": {"information_criterion": "aicc"}}),
            ("AutoARIMA-max-p5-q5", {"auto_arima_kwargs": {"max_p": 5, "max_q": 5}}),
            ("AutoARIMA-max-order-10", {"auto_arima_kwargs": {"max_order": 10}}),
            (
                "AutoARIMA-quiet-ignore-errors",
                {"auto_arima_kwargs": {"trace": False, "error_action": "ignore"}},
            ),
            (
                "AutoARIMA-seasonal-m12-cap-PQ1",
                {"auto_arima_kwargs": {"seasonal": True, "m": 12, "max_P": 1, "max_Q": 1}},
            ),
            ("AutoARIMA-n-jobs-all", {"auto_arima_kwargs": {"n_jobs": -1}}),
            ("AutoARIMA-no-intercept", {"auto_arima_kwargs": {"with_intercept": False}}),
            ("AutoARIMA-scoring-mse", {"auto_arima_kwargs": {"scoring": "mse"}}),
        ]:
            sc[name] = {"fn": "auto_arima", **cfg}

    if ctx["HAS_STATSFORECAST"]:
        for name, w in [
            ("SF-WindowAverage-2", 2),
            ("SF-WindowAverage-4", 4),
            ("SF-WindowAverage-5", 5),
            ("SF-WindowAverage-7", 7),
            ("SF-WindowAverage-8", 8),
            ("SF-WindowAverage-9", 9),
            ("SF-WindowAverage-10", 10),
            ("SF-WindowAverage-11", 11),
            ("SF-WindowAverage-12", 12),
            ("SF-WindowAverage-18", 18),
        ]:
            sc[name] = {
                "fn": "statsforecast",
                "sf_model": "WindowAverage",
                "season_len": sl,
                "sf_window_size": w,
            }
        for name, (ad, ap) in [
            ("SF-TSB-alpha-demand01-pool01", (0.1, 0.1)),
            ("SF-TSB-alpha-demand02-pool02", (0.2, 0.2)),
            ("SF-TSB-alpha-demand04-pool04", (0.4, 0.4)),
            ("SF-TSB-alpha-demand05-pool05", (0.5, 0.5)),
            ("SF-TSB-alpha-demand015-pool035", (0.15, 0.35)),
            ("SF-TSB-alpha-demand035-pool015", (0.35, 0.15)),
            ("SF-TSB-alpha-demand025-pool025", (0.25, 0.25)),
            ("SF-TSB-alpha-demand045-pool045", (0.45, 0.45)),
            ("SF-TSB-alpha-demand005-pool05", (0.05, 0.5)),
            ("SF-TSB-alpha-demand05-pool005", (0.5, 0.05)),
        ]:
            sc[name] = {
                "fn": "statsforecast_intermittent",
                "sf_model": "TSB",
                "season_len": sl,
                "sf_tsb_kwargs": {"alpha_d": ad, "alpha_p": ap},
            }

    for name, cfg in [
        ("UCM-spec-random-walk", {"ucm_level": "random walk"}),
        ("UCM-deterministic-level", {"ucm_stochastic_level": False}),
        ("UCM-spec-fixed-intercept", {"ucm_level": "fixed intercept"}),
    ]:
        sc[name] = {"fn": "ucm", **cfg}

    for name, cfg in [
        ("Local-Ridge-alpha-001", {"sk_model": "ridge", "local_sk_params": {"alpha": 0.01}}),
        ("Local-Ridge-alpha-10", {"sk_model": "ridge", "local_sk_params": {"alpha": 10.0}}),
        ("Local-Lasso-alpha-005", {"sk_model": "lasso", "local_sk_params": {"alpha": 0.05}}),
        ("Local-Lasso-alpha-1", {"sk_model": "lasso", "local_sk_params": {"alpha": 1.0}}),
        (
            "Local-ElasticNet-alpha-02-l1ratio-02",
            {"sk_model": "elasticnet", "local_sk_params": {"alpha": 0.2, "l1_ratio": 0.2}},
        ),
        ("Local-SVR-RBF-C10-eps005", {"sk_model": "svr", "local_sk_params": {"C": 10.0, "epsilon": 0.05}}),
        ("Local-SVR-linear-C05", {"sk_model": "svr", "local_sk_params": {"kernel": "linear", "C": 0.5}}),
        ("Local-KNN-3-uniform", {"sk_model": "knn", "local_sk_params": {"n_neighbors": 3, "weights": "uniform"}}),
        ("Local-RF-depth4-estimators100", {"sk_model": "rf", "local_sk_params": {"max_depth": 4, "n_estimators": 100}}),
        ("Local-RF-depth8-minleaf1", {"sk_model": "rf", "local_sk_params": {"max_depth": 8, "min_samples_leaf": 1}}),
    ]:
        sc[name] = {"fn": "local_supervised", **cfg}

    for name, cfg in [
        ("GLM-NegBin-maxiter-150", {"family": "negbin", "glm_fit_kwargs": {"maxiter": 150}}),
        (
            "GLM-Poisson-ridge-alpha-005",
            {"family": "poisson", "glm_use_regularized": True, "glm_reg_alpha": 0.05, "glm_reg_l1_wt": 0.0},
        ),
        (
            "GLM-Poisson-elastic-alpha-05-l1wt-05",
            {"family": "poisson", "glm_use_regularized": True, "glm_reg_alpha": 0.5, "glm_reg_l1_wt": 0.5},
        ),
        (
            "GLM-NegBin-ridge-alpha-01",
            {"family": "negbin", "glm_use_regularized": True, "glm_reg_alpha": 0.1, "glm_reg_l1_wt": 0.0},
        ),
        ("GLM-NegBin-atol-1e-9", {"family": "negbin", "glm_fit_kwargs": {"atol": 1e-9}}),
    ]:
        sc[name] = {"fn": "glm_count", **cfg}

    for name, ws in [
        ("WindowMedian-2", 2),
        ("WindowMedian-4", 4),
        ("WindowMedian-5", 5),
        ("WindowMedian-7", 7),
        ("WindowMedian-8", 8),
        ("WindowMedian-9", 9),
        ("WindowMedian-10", 10),
        ("WindowMedian-11", 11),
        ("WindowMedian-12", 12),
        ("WindowMedian-18", 18),
    ]:
        sc[name] = {"fn": "window_median", "window_size": ws}


_register_fn_family_extras(
    SERIES_CONFIGS,
    {
        "MONTHLY_SEASON_LENGTH": MONTHLY_SEASON_LENGTH,
        "HAS_PMDARIMA": HAS_PMDARIMA,
        "HAS_STATSFORECAST": HAS_STATSFORECAST,
    },
)
