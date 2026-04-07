from pandas.errors import PerformanceWarning

warnings.filterwarnings("ignore", category=PerformanceWarning)

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
    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
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
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                fit = model.fit(**_fit_kw)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            with warnings.catch_warnings(record=True) as w_fc:
                warnings.simplefilter("always")
                fc = fit.forecast(n_fc)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="forecast",
                n_train_points=n_tr,
                caught=w_fc,
            )
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


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
    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
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
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                res = tm.fit()
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            with warnings.catch_warnings(record=True) as w_fc:
                warnings.simplefilter("always")
                fc = res.forecast(n_fc)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="forecast",
                n_train_points=n_tr,
                caught=w_fc,
            )
            fc = np.asarray(fc, dtype=float).ravel()
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


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
    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
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
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                fit = model.fit(**_sfk)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            with warnings.catch_warnings(record=True) as w_fc:
                warnings.simplefilter("always")
                fc = fit.forecast(n_fc)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="forecast",
                n_train_points=n_tr,
                caught=w_fc,
            )
            fc = np.asarray(fc, dtype=float).ravel()
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


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
    from pmdarima import auto_arima

    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
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
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            if len(y_hist) < 8:
                raise ValueError("too short")
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                aa = auto_arima(y_hist, **base_kw)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            with warnings.catch_warnings(record=True) as w_pred:
                warnings.simplefilter("always")
                fc = aa.predict(n_periods=n_fc)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="predict",
                n_train_points=n_tr,
                caught=w_pred,
            )
            fc = np.asarray(fc, dtype=float).ravel()
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


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


def _sf_build_model_list(sf_model_name: str, season_len: int, sf_window_size=None, tsb_kwargs=None):
    from statsforecast.models import (
        ADIDA,
        AutoARIMA,
        AutoCES,
        AutoETS,
        AutoTheta,
        CrostonSBA,
        CrostonClassic,
        DynamicOptimizedTheta,
        HistoricAverage,
        Holt,
        HoltWinters,
        IMAPA,
        MSTL,
        Naive,
        OptimizedTheta,
        RandomWalkWithDrift,
        SeasonalNaive,
        SimpleExponentialSmoothingOptimized,
        TSB,
        WindowAverage,
    )

    m = sf_model_name
    if m == "AutoETS":
        return [AutoETS(season_length=season_len)]
    if m == "AutoTheta":
        return [AutoTheta(season_length=season_len)]
    if m == "AutoCES":
        return [AutoCES(season_length=season_len)]
    if m == "AutoARIMA":
        return [AutoARIMA(season_length=season_len)]
    if m == "Naive":
        return [Naive()]
    if m == "SeasonalNaive":
        return [SeasonalNaive(season_length=season_len)]
    if m == "HistoricAverage":
        return [HistoricAverage()]
    if m == "RandomWalkWithDrift":
        return [RandomWalkWithDrift()]
    if m == "OptimizedTheta":
        return [OptimizedTheta(season_length=season_len)]
    if m == "DynamicOptimizedTheta":
        return [DynamicOptimizedTheta(season_length=season_len)]
    if m == "MSTL":
        return [MSTL(season_length=season_len)]
    if m == "Holt":
        return [Holt()]
    if m == "HoltWinters":
        return [HoltWinters(season_length=season_len)]
    if m == "SimpleExponentialSmoothingOptimized":
        return [SimpleExponentialSmoothingOptimized()]
    if m == "CrostonSBA":
        return [CrostonSBA()]
    if m == "CrostonClassic":
        return [CrostonClassic()]
    if m == "TSB":
        kw = {"alpha_d": 0.3, "alpha_p": 0.3}
        if tsb_kwargs:
            kw.update(tsb_kwargs)
        return [TSB(**kw)]
    if m == "ADIDA":
        return [ADIDA()]
    if m == "IMAPA":
        return [IMAPA()]
    if m == "WindowAverage":
        ws = int(sf_window_size) if sf_window_size is not None else 3
        ws = max(1, ws)
        return [WindowAverage(window_size=ws)]
    raise ValueError(f"Неизвестная модель StatsForecast: {sf_model_name}")


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
    from statsforecast import StatsForecast

    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            if n_tr < 2:
                raise ValueError("too short")
            sf_df = _sf_train_df(train_part)
            models = _sf_build_model_list(sf_model_name, season_len, sf_window_size, tsb_kwargs=sf_tsb_kwargs)
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                sf = StatsForecast(models=models, freq=STATSFORECAST_FREQ, n_jobs=1)
                sf.fit(sf_df)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            with warnings.catch_warnings(record=True) as w_pred:
                warnings.simplefilter("always")
                fc_df = sf.predict(h=n_fc)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="predict",
                n_train_points=n_tr,
                caught=w_pred,
            )
            fc = _sf_forecast_column(fc_df)
            if fc.shape[0] != n_fc:
                fc = fc[:n_fc] if fc.shape[0] > n_fc else np.resize(fc, n_fc)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


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
    from statsforecast import StatsForecast

    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        zero_frac = float(np.mean(y_hist == 0)) if n_tr else 0.0
        use_intermittent = zero_frac >= INTERMITTENT_ZERO_MIN_FRACTION
        try:
            if n_tr < 2:
                raise ValueError("too short")
            sf_df = _sf_train_df(train_part)
            if use_intermittent:
                models = _sf_build_model_list(sf_model_name, season_len, None, tsb_kwargs=sf_tsb_kwargs)
            else:
                models = _sf_build_model_list("HistoricAverage", season_len, None)
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                sf = StatsForecast(models=models, freq=STATSFORECAST_FREQ, n_jobs=1)
                sf.fit(sf_df)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            with warnings.catch_warnings(record=True) as w_pred:
                warnings.simplefilter("always")
                fc_df = sf.predict(h=n_fc)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="predict",
                n_train_points=n_tr,
                caught=w_pred,
            )
            fc = _sf_forecast_column(fc_df)
            if fc.shape[0] != n_fc:
                fc = fc[:n_fc] if fc.shape[0] > n_fc else np.resize(fc, n_fc)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


def train_prophet_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    prophet_params=None,
):
    from prophet import Prophet

    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    p_base = {} if not prophet_params else dict(prophet_params)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            if n_tr < 4:
                raise ValueError("too short")
            p_kw = dict(p_base)
            df_p = pd.DataFrame(
                {"ds": pd.to_datetime(train_part["date"]), "y": y_hist}
            )
            use_cap_floor = bool(p_kw.pop("use_train_cap_floor", False))
            cap_v = floor_v = None
            if use_cap_floor or p_kw.get("growth") == "logistic":
                if p_kw.get("growth") != "logistic":
                    p_kw["growth"] = "logistic"
                ymax, ymin = float(np.max(y_hist)), float(np.min(y_hist))
                cap_v = ymax * 1.05 if ymax > 0 else 1.0
                floor_v = max(0.0, ymin * 0.95)
                if cap_v <= floor_v:
                    cap_v = floor_v + 1.0
                df_p = df_p.assign(cap=cap_v, floor=floor_v)
            m = Prophet(**p_kw)
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                m.fit(df_p)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            future = pd.DataFrame({"ds": pd.to_datetime(test_part["date"])})
            if cap_v is not None:
                future = future.assign(cap=cap_v, floor=floor_v)
            with warnings.catch_warnings(record=True) as w_pred:
                warnings.simplefilter("always")
                fcst = m.predict(future)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="predict",
                n_train_points=n_tr,
                caught=w_pred,
            )
            fc = fcst["yhat"].values.astype(float)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


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
    from statsmodels.tsa.statespace.structural import UnobservedComponents

    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            if n_tr < 2 * MONTHLY_SEASON_LENGTH:
                raise ValueError("too short for seasonal UCM")
            _uk = {"level": ucm_level, "seasonal": MONTHLY_SEASON_LENGTH}
            if ucm_stochastic_level is not None:
                _uk["stochastic_level"] = ucm_stochastic_level
            if ucm_stochastic_seasonal is not None:
                _uk["stochastic_seasonal"] = ucm_stochastic_seasonal
            mod = UnobservedComponents(y_hist, **_uk)
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                res = mod.fit(disp=False)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            with warnings.catch_warnings(record=True) as w_fc:
                warnings.simplefilter("always")
                fc = res.forecast(n_fc)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="forecast",
                n_train_points=n_tr,
                caught=w_fc,
            )
            fc = np.asarray(fc, dtype=float).ravel()
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


def train_tbats_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    tbats_use_box_cox=None,
    tbats_use_arma_errors=None,
    tbats_seasonal_periods=None,
):
    from tbats import TBATS

    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            if n_tr < 2 * MONTHLY_SEASON_LENGTH:
                raise ValueError("too short for TBATS")
            tb_kw = {"seasonal_periods": list(tbats_seasonal_periods) if tbats_seasonal_periods is not None else [MONTHLY_SEASON_LENGTH]}
            if tbats_use_box_cox is not None:
                tb_kw["use_box_cox"] = tbats_use_box_cox
            if tbats_use_arma_errors is not None:
                tb_kw["use_arma_errors"] = tbats_use_arma_errors
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                estimator = TBATS(**tb_kw)
                fitted = estimator.fit(y_hist)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            with warnings.catch_warnings(record=True) as w_fc:
                warnings.simplefilter("always")
                fc = fitted.forecast(steps=n_fc)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="forecast",
                n_train_points=n_tr,
                caught=w_fc,
            )
            fc = np.asarray(fc, dtype=float).ravel()
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


def train_neuralforecast_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    nf_model_name: str,
    nf_max_steps=None,
    nf_learning_rate=None,
):
    from neuralforecast import NeuralForecast
    from neuralforecast.models import NBEATS, NHITS

    max_steps = (
        int(nf_max_steps)
        if nf_max_steps is not None
        else NEURALFORECAST_MAX_STEPS
    )
    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            if n_tr < max(8, n_fc + 2):
                raise ValueError("too short for neural forecast")
            sf_df = _sf_train_df(train_part)
            inp = min(24, max(2, n_tr - n_fc - 1))
            inp = max(inp, 2)
            _nkw = {
                "h": n_fc,
                "input_size": inp,
                "max_steps": max_steps,
                "accelerator": "cpu",
                "devices": 1,
            }
            if nf_learning_rate is not None:
                _nkw["learning_rate"] = float(nf_learning_rate)
            if nf_model_name == "NHITS":
                model = NHITS(**_nkw)
            else:
                model = NBEATS(**_nkw)
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                nf = NeuralForecast(models=[model], freq=STATSFORECAST_FREQ)
                nf.fit(df=sf_df)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            with warnings.catch_warnings(record=True) as w_pred:
                warnings.simplefilter("always")
                fc_df = nf.predict()
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="predict",
                n_train_points=n_tr,
                caught=w_pred,
            )
            fc = _sf_forecast_column(fc_df)
            if fc.shape[0] != n_fc:
                fc = fc[:n_fc] if fc.shape[0] > n_fc else np.resize(fc, n_fc)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values



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
    from sklearn.linear_model import Ridge, Lasso, ElasticNet
    from sklearn.svm import SVR
    from sklearn.neighbors import KNeighborsRegressor
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.preprocessing import StandardScaler

    if max_lag is None:
        max_lag = LOCAL_MAX_LAG
    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        L = _local_effective_max_lag(n_tr, max_lag)
        use_scaler = sk_model in ("svr", "knn")
        try:
            X, y_tgt = _local_build_xy(y_hist, L)
            if X.shape[0] < 2:
                raise ValueError("too few supervised rows")
            scaler = StandardScaler() if use_scaler else None
            X_fit = scaler.fit_transform(X) if use_scaler else X
            _p = dict(local_sk_params or {})
            if sk_model == "ridge":
                model = Ridge(alpha=float(_p.get("alpha", 1.0)))
            elif sk_model == "lasso":
                model = Lasso(
                    alpha=float(_p.get("alpha", 0.15)),
                    random_state=int(_p.get("random_state", 42)),
                    max_iter=int(_p.get("max_iter", 8000)),
                )
            elif sk_model == "elasticnet":
                model = ElasticNet(
                    alpha=float(_p.get("alpha", 0.15)),
                    l1_ratio=float(_p.get("l1_ratio", 0.5)),
                    random_state=int(_p.get("random_state", 42)),
                    max_iter=int(_p.get("max_iter", 8000)),
                )
            elif sk_model == "svr":
                model = SVR(
                    kernel=_p.get("kernel", "rbf"),
                    C=float(_p.get("C", 1.0)),
                    epsilon=float(_p.get("epsilon", 0.1)),
                    gamma=_p.get("gamma", "scale"),
                )
            elif sk_model == "knn":
                nn = int(_p.get("n_neighbors", max(1, min(5, max(1, X_fit.shape[0] // 3)))))
                model = KNeighborsRegressor(
                    n_neighbors=max(1, nn),
                    weights=_p.get("weights", "distance"),
                )
            elif sk_model == "rf":
                model = RandomForestRegressor(
                    n_estimators=int(_p.get("n_estimators", min(200, max(50, n_tr * 5)))),
                    max_depth=int(_p.get("max_depth", min(6, max(2, max(1, n_tr // 3))))),
                    min_samples_leaf=int(_p.get("min_samples_leaf", max(1, min(3, max(1, n_tr // 5))))),
                    random_state=int(_p.get("random_state", 42)),
                    n_jobs=int(_p.get("n_jobs", -1)),
                )
            else:
                raise ValueError(sk_model)
            with warnings.catch_warnings(record=True) as w_fit:
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
                caught=w_fit,
            )
            fc = _local_recursive_forecast(model, scaler, y_hist, n_fc, L, use_scaler)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


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
    from statsmodels.genmod.generalized_linear_model import GLM
    from statsmodels.genmod import families

    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    fam = families.Poisson() if family_name == "poisson" else families.NegativeBinomial()
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            if n_tr < 4:
                raise ValueError("too short")
            exog_tr, endog_tr = _glm_build_xy_count(y_hist)
            if exog_tr.shape[0] < 3:
                raise ValueError("too few glm rows")
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                glm = GLM(endog_tr, exog_tr, family=fam)
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
                caught=w_fit,
            )
            history = list(np.maximum(np.round(y_hist), 0).astype(float))
            fc = []
            for _ in range(n_fc):
                x1 = np.array([[1.0, history[-1]]])
                mu = float(np.squeeze(res.predict(x1)))
                pred = max(0.0, mu)
                fc.append(pred)
                history.append(float(max(0, round(pred))))
            fc = np.array(fc, dtype=float)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


def train_zip_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    zip_fit_kwargs=None,
    zip_model_kind="zip",
    zip_exog_infl_mode="same",
):
    from statsmodels.discrete.count_model import (
        ZeroInflatedPoisson,
        ZeroInflatedNegativeBinomialP,
        ZeroInflatedGeneralizedPoisson,
    )

    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            if n_tr < 6:
                raise ValueError("too short for zip")
            y_int = np.maximum(np.round(y_hist), 0).astype(int)
            exog_rows = []
            endog_tr = []
            for t in range(1, len(y_int)):
                exog_rows.append([1.0, float(y_int[t - 1])])
                endog_tr.append(float(y_int[t]))
            exog_tr = np.array(exog_rows, dtype=float)
            endog_tr = np.array(endog_tr, dtype=float)
            if exog_tr.shape[0] < 4:
                raise ValueError("too few zip rows")
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                exog_infl_tr = exog_tr if zip_exog_infl_mode == "same" else np.ones((exog_tr.shape[0], 1))
                if zip_model_kind == "zinb":
                    ModelCls = ZeroInflatedNegativeBinomialP
                elif zip_model_kind == "zigp":
                    ModelCls = ZeroInflatedGeneralizedPoisson
                else:
                    ModelCls = ZeroInflatedPoisson
                z = ModelCls(endog_tr, exog_tr, exog_infl=exog_infl_tr)
                _zkw = {"disp": False, "maxiter": 200}
                if zip_fit_kwargs:
                    _zkw.update(zip_fit_kwargs)
                zres = z.fit(**_zkw)
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            history = list(y_int.astype(float))
            fc = []
            for _ in range(n_fc):
                x1 = np.array([[1.0, history[-1]]])
                infl1 = x1 if zip_exog_infl_mode == "same" else np.array([[1.0]])
                mu = float(np.squeeze(zres.predict(exog=x1, exog_infl=infl1)))
                pred = max(0.0, mu)
                fc.append(pred)
                history.append(float(max(0, round(pred))))
            fc = np.array(fc, dtype=float)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


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
    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        history = list(y_hist)
        fc = []
        for _ in range(n_fc):
            tail = history[-window_size:] if len(history) >= window_size else history
            if len(tail) == 0:
                fc.append(0.0)
            else:
                fc.append(float(np.median(tail)))
            history.append(fc[-1])
        fc = np.array(fc, dtype=float)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values


def train_greykite_per_series(
    df_full,
    mask_train,
    mask_test,
    resist_id,
    series_config_name,
    warning_rows,
    *,
    greykite_coverage=0.95,
    greykite_model_template=None,
    greykite_mcp_dict=None,
    greykite_extra_pred_col=False,
    greykite_forecast_one_by_one=None,
):
    from greykite.framework.templates.forecaster import Forecaster
    from greykite.framework.templates.autogen.forecast_config import (
        ForecastConfig,
        MetadataParam,
        ModelComponentsParam,
    )
    from greykite.framework.templates.model_templates import ModelTemplateEnum

    test_idx = df_full.loc[mask_test].index
    preds = pd.Series(0.0, index=test_idx)
    for op_id, grp in df_full.groupby("operation_id"):
        train_part = grp[mask_train.reindex(grp.index, fill_value=False)].sort_values("date")
        test_part = grp[mask_test.reindex(grp.index, fill_value=False)].sort_values("date")
        if test_part.empty:
            continue
        y_hist = train_part["fact_value"].values.astype(float)
        n_fc = len(test_part)
        n_tr = len(y_hist)
        try:
            if n_tr < 8:
                raise ValueError("too short for greykite")
            df_gk = pd.DataFrame({
                "ts": pd.to_datetime(train_part["date"]),
                "y": train_part["fact_value"].astype(float).values,
            })
            forecaster = Forecaster()
            try:
                tpl = ModelTemplateEnum.SILVERKITE.name
            except Exception:
                tpl = ModelTemplateEnum.AUTO.name
            metadata = MetadataParam(
                time_col="ts",
                value_col="y",
                freq=STATSFORECAST_FREQ,
            )
            with warnings.catch_warnings(record=True) as w_fit:
                warnings.simplefilter("always")
                result = forecaster.run_forecast_config(
                    df=df_gk,
                    config=ForecastConfig(
                        model_template=tpl,
                        forecast_horizon=int(n_fc),
                        coverage=0.95,
                        metadata_param=metadata,
                    ),
                )
            append_warning_rows(
                warning_rows,
                resist_id=resist_id,
                operation_id=op_id,
                model_kind="per_series",
                model_label=series_config_name,
                phase="fit",
                n_train_points=n_tr,
                caught=w_fit,
            )
            fdf = result.forecast.df
            fc_col = None
            for cand in ("forecast", "fcst", "yhat", "y"):
                if cand in fdf.columns:
                    fc_col = cand
                    break
            if fc_col is None:
                num_cols = [c for c in fdf.select_dtypes(include=[np.number]).columns]
                fc_col = num_cols[0] if num_cols else None
            if fc_col is None:
                raise ValueError("greykite: no forecast column")
            fc = fdf[fc_col].values.astype(float).ravel()[:n_fc]
            if fc.shape[0] < n_fc:
                fc = np.resize(fc, n_fc)
        except Exception:
            fc = np.full(n_fc, np.mean(y_hist) if len(y_hist) > 0 else 0)
        preds.loc[test_part.index] = np.maximum(fc, 0)
    return preds.values



# Расширенный набор per-series: время прогона (runtime) и число warnings существенно растут.
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
    "Theta-no-deseason": {"fn": "theta", "theta_deseasonalize": False},
    "Theta-mult-method": {"fn": "theta", "theta_method": "multiplicative"},
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
            "SF-HistoricAverage": {"fn": "statsforecast", "sf_model": "HistoricAverage", "season_len": _sl},
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

if HAS_PROPHET:
    SERIES_CONFIGS["Prophet-default"] = {"fn": "prophet", "prophet_params": {}}
    SERIES_CONFIGS["Prophet-yearly"] = {
        "fn": "prophet",
        "prophet_params": {
            "yearly_seasonality": True,
            "weekly_seasonality": False,
            "daily_seasonality": False,
        },
    }
    SERIES_CONFIGS["Prophet-tuned"] = {
        "fn": "prophet",
        "prophet_params": {
            "seasonality_mode": "multiplicative",
            "changepoint_prior_scale": 0.05,
            "n_changepoints": 5,
        },
    }

SERIES_CONFIGS["UCM-local-linear-seasonal"] = {"fn": "ucm"}
SERIES_CONFIGS["UCM-local-level-seasonal"] = {
    "fn": "ucm",
    "ucm_level": "local level",
}

if HAS_TBATS:
    SERIES_CONFIGS["TBATS"] = {"fn": "tbats"}
    SERIES_CONFIGS["TBATS-no-boxcox"] = {"fn": "tbats", "tbats_use_box_cox": False}
    SERIES_CONFIGS["TBATS-no-arma"] = {"fn": "tbats", "tbats_use_arma_errors": False}

if HAS_NEURALFORECAST:
    SERIES_CONFIGS["NF-NHITS"] = {"fn": "neuralforecast", "nf_model": "NHITS"}
    SERIES_CONFIGS["NF-NBEATS"] = {"fn": "neuralforecast", "nf_model": "NBEATS"}
    SERIES_CONFIGS["NF-NHITS-moresteps"] = {
        "fn": "neuralforecast",
        "nf_model": "NHITS",
        "nf_max_steps": 45,
    }
    SERIES_CONFIGS["NF-NBEATS-fewersteps"] = {
        "fn": "neuralforecast",
        "nf_model": "NBEATS",
        "nf_max_steps": 15,
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
        "GLM-NegativeBinomial": {"fn": "glm_count", "family": "negbin"},
        "ZIP": {"fn": "zip"},
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

if HAS_GREYKITE:
    SERIES_CONFIGS["Greykite-Silverkite"] = {"fn": "greykite"}


# -*- coding: utf-8 -*-
"""Дополнительные конфигурации по семействам fn для ноутбука 25.

Каждый ключ SERIES_CONFIGS — уникальное человекочитаемое имя (для Excel и метрик).
"""

def _register_fn_family_extras(sc: dict, ctx: dict) -> None:
    """ctx: MONTHLY_SEASON_LENGTH, HAS_PMDARIMA, HAS_STATSFORECAST, … из ячейки ноутбука."""
    sl = ctx["MONTHLY_SEASON_LENGTH"]
    # База как у ETS-add в ноутбуке 24; частичные пресеты (только ets_fit_kwargs) мержатся поверх.
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
        (
            "ETS-damped-add-no-season-no-brute",
            {
                "trend": "add",
                "damped_trend": True,
                "seasonal": None,
                "seasonal_periods": None,
                "ets_fit_kwargs": {"use_brute": False},
            },
        ),
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
        (
            "ETS-add-tight-fit-tol",
            {
                "trend": "add",
                "damped_trend": False,
                "seasonal": None,
                "seasonal_periods": None,
                "ets_fit_kwargs": {"atol": 1e-8, "rtol": 1e-6},
            },
        ),
    ]:
        sc[name] = {**_ets_base, **cfg}

    for name, cfg in [
        ("Theta-period-6-deseason-auto", {"theta_period": 6}),
        ("Theta-period-4-deseason-auto", {"theta_period": 4}),
        ("Theta-period-3-deseason-auto", {"theta_period": 3}),
        ("Theta-method-additive-deseason", {"theta_method": "additive"}),
        ("Theta-additive-no-deseason", {"theta_deseasonalize": False, "theta_method": "additive"}),
        ("Theta-period-12-additive-deseason", {"theta_period": 12, "theta_method": "additive"}),
        ("Theta-period-12-no-deseason", {"theta_period": 12, "theta_deseasonalize": False}),
        ("Theta-period-6-multiplicative-deseason", {"theta_period": 6, "theta_method": "multiplicative"}),
        ("Theta-period-8-deseason-auto", {"theta_period": 8}),
        ("Theta-period-24-deseason-auto", {"theta_period": 24}),
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
        ("SARIMAX-default-fit-lbfgs", {"sarimax_fit_kwargs": {"method": "lbfgs"}}),
        ("SARIMAX-default-robust-cov", {"sarimax_fit_kwargs": {"cov_type": "robust"}}),
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

    if ctx["HAS_PROPHET"]:
        for name, pp in [
            ("Prophet-seasonality-prior-low", {"seasonality_prior_scale": 0.01}),
            ("Prophet-seasonality-prior-high", {"seasonality_prior_scale": 10.0}),
            ("Prophet-changepoint-prior-tight", {"changepoint_prior_scale": 0.001}),
            ("Prophet-changepoint-prior-loose", {"changepoint_prior_scale": 0.5}),
            ("Prophet-holidays-prior-low", {"holidays_prior_scale": 0.01}),
            (
                "Prophet-logistic-train-cap-floor",
                {"growth": "logistic", "use_train_cap_floor": True},
            ),
            ("Prophet-changepoints-25", {"n_changepoints": 25}),
            ("Prophet-seasonality-additive-mode", {"seasonality_mode": "additive"}),
            ("Prophet-yearly-fourier-order-20", {"yearly_seasonality": 20}),
            ("Prophet-mcmc-samples-zero", {"mcmc_samples": 0}),
        ]:
            sc[name] = {"fn": "prophet", "prophet_params": pp}

    for name, cfg in [
        ("UCM-stochastic-level", {"ucm_stochastic_level": True}),
        ("UCM-stochastic-seasonal", {"ucm_stochastic_seasonal": True}),
        ("UCM-stochastic-level-and-seasonal", {"ucm_stochastic_level": True, "ucm_stochastic_seasonal": True}),
        ("UCM-spec-local-linear-trend", {"ucm_level": "local linear trend"}),
        ("UCM-spec-local-level", {"ucm_level": "local level"}),
        ("UCM-spec-random-walk", {"ucm_level": "random walk"}),
        ("UCM-deterministic-level", {"ucm_stochastic_level": False}),
        ("UCM-spec-fixed-intercept", {"ucm_level": "fixed intercept"}),
        (
            "UCM-local-linear-trend-stochastic-level",
            {"ucm_level": "local linear trend", "ucm_stochastic_level": True},
        ),
        (
            "UCM-local-level-stochastic-seasonal",
            {"ucm_level": "local level", "ucm_stochastic_seasonal": True},
        ),
    ]:
        sc[name] = {"fn": "ucm", **cfg}

    if ctx["HAS_TBATS"]:
        for name, cfg in [
            ("TBATS-seasons-6-12", {"tbats_seasonal_periods": [6, 12]}),
            ("TBATS-seasons-12-only", {"tbats_seasonal_periods": [12]}),
            ("TBATS-boxcox-and-arma-errors", {"tbats_use_box_cox": True, "tbats_use_arma_errors": True}),
            ("TBATS-arma-errors-no-boxcox", {"tbats_use_box_cox": False, "tbats_use_arma_errors": True}),
            ("TBATS-seasons-3-12", {"tbats_seasonal_periods": [3, 12]}),
            ("TBATS-seasons-4-12", {"tbats_seasonal_periods": [4, 12]}),
            ("TBATS-no-arma-errors", {"tbats_use_arma_errors": False}),
            ("TBATS-boxcox-only-default-arma", {"tbats_use_box_cox": True}),
            ("TBATS-seasons-12-24", {"tbats_seasonal_periods": [12, 24]}),
            ("TBATS-seasons-2-12", {"tbats_seasonal_periods": [2, 12]}),
        ]:
            sc[name] = {"fn": "tbats", **cfg}

    if ctx["HAS_NEURALFORECAST"]:
        for name, cfg in [
            ("NF-NHITS-steps10-lr01", {"nf_model": "NHITS", "nf_max_steps": 10, "nf_learning_rate": 0.01}),
            ("NF-NBEATS-steps60-lr001", {"nf_model": "NBEATS", "nf_max_steps": 60, "nf_learning_rate": 0.001}),
            ("NF-NHITS-steps20-lr05", {"nf_model": "NHITS", "nf_max_steps": 20, "nf_learning_rate": 0.05}),
            ("NF-NBEATS-steps40-lr02", {"nf_model": "NBEATS", "nf_max_steps": 40, "nf_learning_rate": 0.02}),
            ("NF-NHITS-steps25-lr03", {"nf_model": "NHITS", "nf_max_steps": 25, "nf_learning_rate": 0.03}),
            ("NF-NBEATS-steps35-lr015", {"nf_model": "NBEATS", "nf_max_steps": 35, "nf_learning_rate": 0.015}),
            ("NF-NHITS-steps50-lr008", {"nf_model": "NHITS", "nf_max_steps": 50, "nf_learning_rate": 0.008}),
            ("NF-NBEATS-steps15-lr1", {"nf_model": "NBEATS", "nf_max_steps": 15, "nf_learning_rate": 0.1}),
            ("NF-NHITS-steps55-lr012", {"nf_model": "NHITS", "nf_max_steps": 55, "nf_learning_rate": 0.012}),
            ("NF-NBEATS-steps22-lr04", {"nf_model": "NBEATS", "nf_max_steps": 22, "nf_learning_rate": 0.04}),
        ]:
            sc[name] = {"fn": "neuralforecast", **cfg}

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
        ("GLM-Poisson-maxiter-100", {"family": "poisson", "glm_fit_kwargs": {"maxiter": 100}}),
        ("GLM-Poisson-atol-1e-10", {"family": "poisson", "glm_fit_kwargs": {"atol": 1e-10}}),
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
        ("GLM-Poisson-tol-criterion-deviance", {"family": "poisson", "glm_fit_kwargs": {"tol_criterion": "deviance"}}),
        ("GLM-Poisson-wls-pinv", {"family": "poisson", "glm_fit_kwargs": {"wls_method": "pinv"}}),
        ("GLM-NegBin-atol-1e-9", {"family": "negbin", "glm_fit_kwargs": {"atol": 1e-9}}),
        ("GLM-Poisson-maxiter-300", {"family": "poisson", "glm_fit_kwargs": {"maxiter": 300}}),
    ]:
        sc[name] = {"fn": "glm_count", **cfg}

    for name, cfg in [
        (
            "ZIP-Poisson-exog-same",
            {"zip_model_kind": "zip", "zip_exog_infl_mode": "same", "zip_fit_kwargs": {"maxiter": 200}},
        ),
        (
            "ZIP-Poisson-infl-intercept",
            {"zip_model_kind": "zip", "zip_exog_infl_mode": "intercept", "zip_fit_kwargs": {"maxiter": 200}},
        ),
        (
            "ZIP-ZINB-exog-same",
            {"zip_model_kind": "zinb", "zip_exog_infl_mode": "same", "zip_fit_kwargs": {"maxiter": 300}},
        ),
        (
            "ZIP-ZINB-infl-intercept",
            {"zip_model_kind": "zinb", "zip_exog_infl_mode": "intercept", "zip_fit_kwargs": {"maxiter": 300}},
        ),
        (
            "ZIP-ZIGP-exog-same",
            {"zip_model_kind": "zigp", "zip_exog_infl_mode": "same", "zip_fit_kwargs": {"maxiter": 300}},
        ),
        (
            "ZIP-ZIGP-infl-intercept",
            {"zip_model_kind": "zigp", "zip_exog_infl_mode": "intercept", "zip_fit_kwargs": {"maxiter": 300}},
        ),
        (
            "ZIP-Poisson-bfgs",
            {"zip_model_kind": "zip", "zip_exog_infl_mode": "same", "zip_fit_kwargs": {"method": "bfgs", "maxiter": 200}},
        ),
        (
            "ZIP-ZINB-newton",
            {"zip_model_kind": "zinb", "zip_exog_infl_mode": "same", "zip_fit_kwargs": {"method": "newton", "maxiter": 200}},
        ),
        (
            "ZIP-ZIGP-bfgs",
            {"zip_model_kind": "zigp", "zip_exog_infl_mode": "intercept", "zip_fit_kwargs": {"method": "bfgs", "maxiter": 250}},
        ),
        (
            "ZIP-Poisson-high-maxiter",
            {"zip_model_kind": "zip", "zip_exog_infl_mode": "same", "zip_fit_kwargs": {"maxiter": 500}},
        ),
    ]:
        sc[name] = {"fn": "zip", **cfg}

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

    if ctx["HAS_GREYKITE"]:

        def _gk_mcp(fit_algorithm: str):
            return {"custom": {"fit_algorithm_dict": {"fit_algorithm": fit_algorithm}}}

        for name, cfg in [
            ("Greykite-template-auto", {"greykite_model_template": "AUTO"}),
            ("Greykite-template-prophet", {"greykite_model_template": "PROPHET"}),
            ("Greykite-silverkite-lasso", {"greykite_mcp_dict": _gk_mcp("lasso")}),
            ("Greykite-silverkite-ridge", {"greykite_mcp_dict": _gk_mcp("ridge")}),
            ("Greykite-silverkite-elastic_net", {"greykite_mcp_dict": _gk_mcp("elastic_net")}),
            ("Greykite-silverkite-gb", {"greykite_mcp_dict": _gk_mcp("gradient_boosting")}),
            ("Greykite-silverkite-linear", {"greykite_mcp_dict": _gk_mcp("linear")}),
            ("Greykite-silverkite-sgd", {"greykite_mcp_dict": _gk_mcp("sgd")}),
            ("Greykite-extra-pred-col-gk-t", {"greykite_extra_pred_col": True}),
            ("Greykite-forecast-one-by-one", {"greykite_forecast_one_by_one": 1}),
        ]:
            sc[name] = {"fn": "greykite", "greykite_coverage": 0.95, **cfg}

_register_fn_family_extras(
    SERIES_CONFIGS,
    {
        "MONTHLY_SEASON_LENGTH": MONTHLY_SEASON_LENGTH,
        "HAS_PMDARIMA": HAS_PMDARIMA,
        "HAS_STATSFORECAST": HAS_STATSFORECAST,
        "HAS_PROPHET": HAS_PROPHET,
        "HAS_TBATS": HAS_TBATS,
        "HAS_NEURALFORECAST": HAS_NEURALFORECAST,
        "HAS_GREYKITE": HAS_GREYKITE,
    },
)


def _build_model_configs() -> dict:
    """Фабрика: каждый вызов создаёт свежие (не обученные) экземпляры моделей."""
    return {
        "LinearRegression": LinearRegression(),
        "DT-shallow": DecisionTreeRegressor(max_depth=6, min_samples_leaf=5, random_state=42),
        "DT-deep": DecisionTreeRegressor(max_depth=12, min_samples_leaf=2, random_state=42),
        "DT-mid": DecisionTreeRegressor(max_depth=8, min_samples_leaf=4, random_state=42),
        "DT-conservative": DecisionTreeRegressor(
            max_depth=5, min_samples_leaf=10, min_samples_split=15, random_state=42,
        ),
        "DT-ccp": DecisionTreeRegressor(
            max_depth=15, min_samples_leaf=2, ccp_alpha=0.02, random_state=42,
        ),
        "LGBM-default": LGBMRegressor(
            n_estimators=500, max_depth=6, learning_rate=0.1,
            verbose=-1, random_state=42,
        ),
        "LGBM-tuned": LGBMRegressor(
            n_estimators=800, max_depth=8, learning_rate=0.05,
            num_leaves=63, min_child_samples=10, verbose=-1, random_state=42,
        ),
        "XGB-default": XGBRegressor(
            n_estimators=500, max_depth=6, learning_rate=0.1,
            verbosity=0, random_state=42,
        ),
        "XGB-regularized": XGBRegressor(
            n_estimators=800, max_depth=8, learning_rate=0.05,
            reg_alpha=0.1, reg_lambda=5, verbosity=0, random_state=42,
        ),
        "RF-default": RandomForestRegressor(
            n_estimators=300, max_depth=12, min_samples_leaf=2,
            random_state=42, n_jobs=-1,
        ),
        "ET-default": ExtraTreesRegressor(
            n_estimators=300, max_depth=12, min_samples_leaf=2,
            random_state=42, n_jobs=-1,
        ),
        "HistGBM-default": HistGradientBoostingRegressor(
            max_iter=500, max_depth=6, learning_rate=0.1,
            random_state=42,
        ),
        "GBR-default": GradientBoostingRegressor(
            n_estimators=300, max_depth=6, learning_rate=0.1,
            random_state=42,
        ),
    }

all_results: list = []
all_predictions: dict = {}
df_by_rid: dict = {}
mask_test_by_rid: dict = {}
summary_parts: list[str] = []
warning_rows: list[dict] = []

import logging
for _lg in ("cmdstanpy", "prophet"):
    logging.getLogger(_lg).setLevel(logging.WARNING)
try:
    import cmdstanpy

    if hasattr(cmdstanpy, "disable_logging"):
        cmdstanpy.disable_logging()
    _cu = getattr(cmdstanpy, "utils", None)
    if _cu is not None and callable(getattr(_cu, "get_logger", None)):
        _cu.get_logger().setLevel(logging.WARNING)
except Exception:
    pass
_cs = logging.getLogger("cmdstanpy")
_cs.propagate = False
for _h in list(_cs.handlers):
    _cs.removeHandler(_h)
_cs.addHandler(logging.NullHandler())
_cs.setLevel(logging.ERROR)

for rid in RESIST_IDS:
    df = df_model39[df_model39["resist_id"] == rid].copy()
    df["op_code"] = df["operation_id"].astype("category").cat.codes

    group = df.groupby("operation_id")
    df["lag_1"] = group["fact_value"].shift(1)
    df["lag_12"] = group["fact_value"].shift(12)
    df["rolling_mean_3"] = group["fact_value"].transform(
        lambda s: s.shift(1).rolling(window=3, min_periods=1).mean()
    )
    num_cols = df.select_dtypes(include=["number"]).columns
    df[num_cols] = df[num_cols].fillna(0)
    df = df.infer_objects(copy=False)

    miss = df.isnull().sum()
    miss = miss[miss > 0]
    if len(miss) > 0:
        df = df.fillna(0)

    mask_test = (df["year"] == TEST_YEAR) & (df["month"].isin(TEST_MONTHS))
    mask_train = ~mask_test
    y_train = df.loc[mask_train, "fact_value"]
    y_test = df.loc[mask_test, "fact_value"]

    df_by_rid[rid] = df
    mask_test_by_rid[rid] = mask_test

    results_rid: list = []
    preds_rid: dict = {}

    n_test = int(mask_test.sum())
    t_fp, s_fp, q_fp = calc_metrics(y_test.values, df.loc[mask_test, "fact_predict"].values)

    if mask_train.sum() == 0:
        y_zero = np.zeros(n_test)
        t_z, s_z, q_z = calc_metrics(y_test.values, y_zero)

        for config_name in SERIES_CONFIGS:
            results_rid.append({
                "resist_id": rid,
                "Конфигурация": config_name,
                "Набор признаков": "—",
                "Тип": "per-series",
                "Точность, %": t_z,
                "Стабильность, %": s_z,
                "Качество, %": q_z,
                "Время, сек": 0.0,
                "Точн. fact_predict, %": t_fp,
                "Стаб. fact_predict, %": s_fp,
                "Кач. fact_predict, %": q_fp,
            })
            preds_rid[config_name] = y_zero

        all_results.extend(results_rid)
        all_predictions[rid] = preds_rid
        q_best = max(r["Качество, %"] for r in results_rid)
        summary_parts.append(
            f"{rid} baseline:{q_fp:.0f}%  forecast:{q_best:.0f}%"
        )
        print(", ".join(summary_parts))
        continue

    for config_name, cfg in SERIES_CONFIGS.items():
        t0 = time.perf_counter()
        if cfg["fn"] == "ets":
            y_pred = train_ets_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                trend=cfg["trend"],
                damped_trend=cfg["damped_trend"],
                seasonal=cfg.get("seasonal"),
                seasonal_periods=cfg.get("seasonal_periods"),
                ets_fit_kwargs=cfg.get("ets_fit_kwargs"),
            )
        elif cfg["fn"] == "theta":
            y_pred = train_theta_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                theta_deseasonalize=cfg.get("theta_deseasonalize", True),
                theta_method=cfg.get("theta_method", "auto"),
                theta_period=cfg.get("theta_period", 12),
            )
        elif cfg["fn"] == "sarimax":
            y_pred = train_sarimax_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                sarimax_preset=cfg.get("sarimax_preset", "default"),
                sarimax_order=cfg.get("sarimax_order"),
                sarimax_seasonal_order=cfg.get("sarimax_seasonal_order"),
                sarimax_fit_kwargs=cfg.get("sarimax_fit_kwargs"),
            )
        elif cfg["fn"] == "auto_arima":
            y_pred = train_auto_arima_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                auto_arima_kwargs=cfg.get("auto_arima_kwargs"),
            )
        elif cfg["fn"] == "statsforecast":
            y_pred = train_statsforecast_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                sf_model_name=cfg["sf_model"],
                season_len=cfg["season_len"],
                sf_window_size=cfg.get("sf_window_size"),
                sf_tsb_kwargs=cfg.get("sf_tsb_kwargs"),
            )
        elif cfg["fn"] == "statsforecast_intermittent":
            y_pred = train_statsforecast_intermittent_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                sf_model_name=cfg["sf_model"],
                season_len=cfg["season_len"],
                sf_tsb_kwargs=cfg.get("sf_tsb_kwargs"),
            )
        elif cfg["fn"] == "prophet":
            y_pred = train_prophet_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                prophet_params=cfg.get("prophet_params"),
            )
        elif cfg["fn"] == "ucm":
            y_pred = train_ucm_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                ucm_level=cfg.get("ucm_level", "local linear trend"),
                ucm_stochastic_level=cfg.get("ucm_stochastic_level"),
                ucm_stochastic_seasonal=cfg.get("ucm_stochastic_seasonal"),
            )
        elif cfg["fn"] == "tbats":
            y_pred = train_tbats_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                tbats_use_box_cox=cfg.get("tbats_use_box_cox"),
                tbats_use_arma_errors=cfg.get("tbats_use_arma_errors"),
                tbats_seasonal_periods=cfg.get("tbats_seasonal_periods"),
            )
        elif cfg["fn"] == "neuralforecast":
            y_pred = train_neuralforecast_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                nf_model_name=cfg["nf_model"],
                nf_max_steps=cfg.get("nf_max_steps"),
                nf_learning_rate=cfg.get("nf_learning_rate"),
            )
        elif cfg["fn"] == "local_supervised":
            y_pred = train_local_supervised_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                sk_model=cfg["sk_model"],
                local_sk_params=cfg.get("local_sk_params"),
            )
        elif cfg["fn"] == "glm_count":
            y_pred = train_glm_count_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                family_name=cfg["family"],
                glm_fit_kwargs=cfg.get("glm_fit_kwargs"),
                glm_use_regularized=cfg.get("glm_use_regularized", False),
                glm_reg_alpha=cfg.get("glm_reg_alpha", 0.1),
                glm_reg_l1_wt=cfg.get("glm_reg_l1_wt", 0.0),
            )
        elif cfg["fn"] == "zip":
            y_pred = train_zip_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                zip_fit_kwargs=cfg.get("zip_fit_kwargs"),
                zip_model_kind=cfg.get("zip_model_kind", "zip"),
                zip_exog_infl_mode=cfg.get("zip_exog_infl_mode", "same"),
            )
        elif cfg["fn"] == "window_median":
            y_pred = train_window_median_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                window_size=int(cfg["window_size"]),
            )
        elif cfg["fn"] == "greykite":
            y_pred = train_greykite_per_series(
                df,
                mask_train,
                mask_test,
                rid,
                config_name,
                warning_rows,
                greykite_coverage=cfg.get("greykite_coverage", 0.95),
                greykite_model_template=cfg.get("greykite_model_template"),
                greykite_mcp_dict=cfg.get("greykite_mcp_dict"),
                greykite_extra_pred_col=cfg.get("greykite_extra_pred_col", False),
                greykite_forecast_one_by_one=cfg.get("greykite_forecast_one_by_one"),
            )
        else:
            continue

        elapsed = round(time.perf_counter() - t0, 2)
        tochnost, stab, kachestvo = calc_metrics(y_test.values, y_pred)
        results_rid.append({
            "resist_id": rid,
            "Конфигурация": config_name,
            "Набор признаков": "—",
            "Тип": "per-series",
            "Точность, %": tochnost,
            "Стабильность, %": stab,
            "Качество, %": kachestvo,
            "Время, сек": elapsed,
            "Точн. fact_predict, %": t_fp,
            "Стаб. fact_predict, %": s_fp,
            "Кач. fact_predict, %": q_fp,
        })
        preds_rid[config_name] = y_pred

    all_results.extend(results_rid)
    all_predictions[rid] = preds_rid
    q_best = max(r["Качество, %"] for r in results_rid)
    summary_parts.append(
        f"{rid} baseline:{q_fp:.0f}%  forecast:{q_best:.0f}%"
    )
    print(", ".join(summary_parts))

results = all_results
