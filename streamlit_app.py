import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
import plotly.express as px


DATA_PATH = Path("data/processed/operations_from_history.csv")
WORKLOAD_PATH = Path("data/processed/workload_from_history.csv")
EXCEL_SVOD_CSV = Path("data/processed/excel_svod_workload.csv")
CATBOOST_PRED_CSV = Path("data/processed/model_predictions_catboost_v1.csv")


@st.cache_data
def load_data(path: Path) -> pd.DataFrame:
    """Загрузка данных (data loading) из подготовленного CSV."""
    df = pd.read_csv(path, parse_dates=["period"])
    df = df.rename(
        columns={
            "operation_fact_value": "fact",
            "operation_forecast_value": "ai_pred",
        }
    )
    df["month"] = df["period"].dt.to_period("M").dt.to_timestamp()
    return df


def add_baseline(df: pd.DataFrame) -> pd.DataFrame:
    """Построение baseline (baseline model): факт год назад по той же операции."""
    key = ["resist_id", "operation_id"]
    df = df.copy()
    df["month_prev"] = df["month"] - pd.DateOffset(months=12)

    prev = (
        df[key + ["month", "fact"]]
        .rename(columns={"month": "month_prev", "fact": "fact_prev"})
    )

    df = df.merge(prev, on=key + ["month_prev"], how="left")
    df["baseline_pred"] = df["fact_prev"]
    return df


def add_hybrid_baseline(
    df: pd.DataFrame,
    group_keys: list[str],
    window: int = 6,
    min_periods: int = 3,
) -> pd.DataFrame:
    """Гибридный baseline (hybrid baseline) с fallback (fallback ladder).

    Приоритет:
    1) year_ago: факт год назад (t-12)
    2) rolling_median: медиана последних N месяцев (без текущего), если есть >= min_periods
    3) last_value: факт прошлого месяца
    4) global_median: медиана по всей истории в группе
    """
    df = df.copy()
    df = df.sort_values(group_keys + ["month"])

    # year_ago (year-over-year)
    df["month_prev"] = df["month"] - pd.DateOffset(months=12)
    prev = (
        df[group_keys + ["month", "fact"]]
        .rename(columns={"month": "month_prev", "fact": "fact_prev"})
    )
    df = df.merge(prev, on=group_keys + ["month_prev"], how="left")
    year_ago = df["fact_prev"]

    # rolling median (rolling median)
    rolling_med = (
        df.groupby(group_keys, dropna=False)["fact"]
        .transform(lambda s: s.shift(1).rolling(window=window, min_periods=min_periods).median())
    )

    # last value (last observation)
    last_val = df.groupby(group_keys, dropna=False)["fact"].transform(lambda s: s.shift(1))

    # global median (global median)
    global_med = df.groupby(group_keys, dropna=False)["fact"].transform("median")

    baseline = year_ago.copy()
    baseline_rule = np.where(~year_ago.isna(), "year_ago", None)

    mask = baseline.isna()
    baseline.loc[mask] = rolling_med.loc[mask]
    baseline_rule = np.where(mask & ~rolling_med.isna(), "rolling_median", baseline_rule)

    mask = baseline.isna()
    baseline.loc[mask] = last_val.loc[mask]
    baseline_rule = np.where(mask & ~last_val.isna(), "last_value", baseline_rule)

    mask = baseline.isna()
    baseline.loc[mask] = global_med.loc[mask]
    baseline_rule = np.where(mask & ~global_med.isna(), "global_median", baseline_rule)

    df["baseline_pred"] = baseline.clip(lower=0)
    df["baseline_rule"] = baseline_rule
    return df


@st.cache_data
def load_workload_data(path: Path) -> pd.DataFrame:
    """Загрузка датасета по нагрузке (workload dataset)."""
    df = pd.read_csv(path, parse_dates=["period"])
    df = df.rename(
        columns={
            "workload_fact": "fact",
            "workload_ai": "ai_pred",
        }
    )
    df["month"] = df["period"].dt.to_period("M").dt.to_timestamp()
    return df


@st.cache_data
def load_catboost_predictions(path: Path) -> pd.DataFrame:
    """Загрузка предсказаний (predictions) CatBoost (CatBoost)."""
    df = pd.read_csv(path, parse_dates=["period", "cutoff"])
    # Если есть несколько прогнозов на один месяц, берём последний cutoff (latest cutoff).
    df = df.sort_values(["resist_id", "period", "cutoff"]).drop_duplicates(
        ["resist_id", "period"], keep="last"
    )
    df = df.rename(columns={"y_pred": "catboost_pred"})
    df["month"] = df["period"].dt.to_period("M").dt.to_timestamp()
    return df


def compute_metrics(y_true, y_pred, large_abs=100, large_pct=0.3):
    """Расчёт базовых метрик (metrics) ошибки прогноза."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    y_true = y_true[mask]
    y_pred = y_pred[mask]

    if len(y_true) == 0:
        return {"MAE": np.nan, "RMSE": np.nan, "MAPE_%": np.nan, "large_error_share": np.nan}

    error = y_pred - y_true
    abs_error = np.abs(error)

    mae = abs_error.mean()
    rmse = np.sqrt((error ** 2).mean())

    mape = np.nan
    nonzero = y_true != 0
    if nonzero.any():
        mape = (abs_error[nonzero] / np.abs(y_true[nonzero]) * 100).mean()

    large_mask = (abs_error > large_abs) | (abs_error > np.abs(y_true) * large_pct)
    large_share = large_mask.mean()

    return {
        "MAE": mae,
        "RMSE": rmse,
        "MAPE_%": mape,
        "large_error_share": large_share,
    }


mode = st.sidebar.selectbox(
    "Режим (mode)",
    options=["Operations (кол-во операций)", "Workload (нагрузка, %)"],
    index=0,
)

if mode.startswith("Workload"):
    df = load_workload_data(WORKLOAD_PATH)
    # baseline по нагрузке строим на уровне resist_id
    df = add_hybrid_baseline(df, group_keys=["resist_id"], window=6, min_periods=3)

    if CATBOOST_PRED_CSV.exists():
        df_cb = load_catboost_predictions(CATBOOST_PRED_CSV)
        df = df.merge(
            df_cb[["resist_id", "period", "catboost_pred"]],
            on=["resist_id", "period"],
            how="left",
        )
    else:
        st.caption("Нет CSV (CSV) с CatBoost (CatBoost): data/processed/model_predictions_catboost_v1.csv")

    if EXCEL_SVOD_CSV.exists():
        st.subheader("Excel (Excel): сводный отчёт (summary report) по нагрузке (workload)")
        df_excel = pd.read_csv(EXCEL_SVOD_CSV, parse_dates=["month"])
        excel_divs = sorted(df_excel["division_title"].dropna().unique().tolist())
        excel_div_sel = st.selectbox("Подразделение из Excel (division from Excel)", excel_divs)
        df_excel_div = df_excel[df_excel["division_title"] == excel_div_sel].sort_values("month")

        st.dataframe(df_excel_div)

        chart = df_excel_div.set_index("month")[["workload_ml_pct", "workload_manual_pct"]]
        st.line_chart(chart)

        # --- Сопоставление (mapping) Excel ↔ БД (DB) по месяцам (month) ---
        st.subheader("Сравнение Excel (Excel) и БД (DB) по месяцам (month)")

        db_divs = sorted(df["division_title"].dropna().unique().tolist())
        default_db_div = excel_div_sel if excel_div_sel in db_divs else "(не найдено)"
        db_div_options = ["(не найдено)"] + db_divs
        db_div_sel = st.selectbox(
            "Подразделение в БД (division in DB) для сравнения",
            options=db_div_options,
            index=db_div_options.index(default_db_div) if default_db_div in db_div_options else 0,
        )

        if db_div_sel == "(не найдено)":
            st.warning(
                "Не нашёл точного совпадения названия подразделения (division title) между Excel и БД. "
                "Выбери подразделение в БД вручную."
            )
        else:
            # В БД (DB) в режиме Workload строки на уровне resist_id,
            # поэтому агрегируем по месяцу (month) средним (mean).
            agg_map = {
                "db_fact": ("fact", "mean"),
                "db_ai": ("ai_pred", "mean"),
                "db_baseline": ("baseline_pred", "mean"),
            }
            if "catboost_pred" in df.columns:
                agg_map["db_catboost"] = ("catboost_pred", "mean")

            df_db_div = (
                df[df["division_title"] == db_div_sel]
                .groupby("month", as_index=False)
                .agg(**agg_map)
            )

            df_excel_cmp = (
                df_excel_div.rename(
                    columns={
                        "workload_ml_pct": "excel_ml",
                        "workload_manual_pct": "excel_manual",
                    }
                )[["month", "excel_ml", "excel_manual"]]
            )

            df_cmp = df_db_div.merge(df_excel_cmp, on="month", how="outer").sort_values("month")
            st.dataframe(df_cmp)

            st.subheader("График (chart): DB vs Excel")
            chart_cols = ["db_fact", "db_ai", "db_baseline", "excel_ml", "excel_manual"]
            if "db_catboost" in df_cmp.columns:
                chart_cols.insert(3, "db_catboost")
            chart2 = df_cmp.set_index("month")[chart_cols]
            st.line_chart(chart2)

            st.subheader("Метрики (metrics) относительно DB fact (fact)")
            rows_m = []
            sources_db = [("db_ai", "db_ai"), ("db_baseline", "db_baseline")]
            if "db_catboost" in df_cmp.columns:
                sources_db.insert(1, ("db_catboost", "db_catboost"))
            sources_db += [("excel_ml", "excel_ml"), ("excel_manual", "excel_manual")]
            for src, col in sources_db:
                m = compute_metrics(df_cmp["db_fact"], df_cmp[col])
                m["source"] = src
                rows_m.append(m)
            st.dataframe(pd.DataFrame(rows_m).set_index("source").style.format("{:.2f}"))

            st.subheader("Метрики (metrics) относительно Excel manual (manual)")
            rows_m2 = []
            sources_m = [("db_ai", "db_ai"), ("db_baseline", "db_baseline")]
            if "db_catboost" in df_cmp.columns:
                sources_m.insert(1, ("db_catboost", "db_catboost"))
            sources_m += [("excel_ml", "excel_ml")]
            for src, col in sources_m:
                m = compute_metrics(df_cmp["excel_manual"], df_cmp[col])
                m["source"] = src
                rows_m2.append(m)
            st.dataframe(pd.DataFrame(rows_m2).set_index("source").style.format("{:.2f}"))
    else:
        st.caption("Нет Excel CSV: data/processed/excel_svod_workload.csv (сначала запусти notebooks/export_svod_to_csv.ipynb)")
else:
    df = load_data(DATA_PATH)
    # baseline по операциям строим на уровне resist_id + operation_id
    df = add_hybrid_baseline(df, group_keys=["resist_id", "operation_id"], window=6, min_periods=3)


st.sidebar.header("Фильтры (filters)")

min_month = df["month"].min()
max_month = df["month"].max()

period_range = st.sidebar.slider(
    "Период (month range)",
    min_value=min_month.to_pydatetime(),
    max_value=max_month.to_pydatetime(),
    value=(min_month.to_pydatetime(), max_month.to_pydatetime()),
)

divisions = ["(все)"] + sorted(df["division_title"].dropna().unique().tolist())
division_sel = st.sidebar.selectbox("Подразделение (division)", divisions)


mask = (df["month"] >= period_range[0]) & (df["month"] <= period_range[1])
if division_sel != "(все)":
    mask &= df["division_title"] == division_sel

df_filt = df[mask].copy()


if mode.startswith("Workload"):
    st.title("Оценка качества прогноза нагрузки (workload, %)")
else:
    st.title("Оценка качества прогноза количества операций (operations)")
st.write(f"Строк после фильтрации: {len(df_filt):,}")


sources = {
    "ai": df_filt["ai_pred"],
    "baseline": df_filt["baseline_pred"],
}
if "catboost_pred" in df_filt.columns:
    sources["catboost_v1"] = df_filt["catboost_pred"]

df_common = df_filt[df_filt["baseline_pred"].notna()].copy()
coverage = (len(df_common) / len(df_filt)) if len(df_filt) else np.nan

rows = []

# AI на всех данных (ai_all)
m_ai_all = compute_metrics(df_filt["fact"], df_filt["ai_pred"])
m_ai_all["source"] = "ai_all"
rows.append(m_ai_all)

# CatBoost на всех данных (catboost_all)
if "catboost_pred" in df_filt.columns:
    df_cb = df_filt[df_filt["catboost_pred"].notna()]
    m_cb_all = compute_metrics(df_cb["fact"], df_cb["catboost_pred"])
    m_cb_all["source"] = "catboost_v1"
    rows.append(m_cb_all)

# AI на общем пересечении с baseline (ai_common)
m_ai_common = compute_metrics(df_common["fact"], df_common["ai_pred"])
m_ai_common["source"] = "ai_common"
rows.append(m_ai_common)

# baseline на общем пересечении (baseline_common)
m_bl_common = compute_metrics(df_common["fact"], df_common["baseline_pred"])
m_bl_common["source"] = "baseline_common"
rows.append(m_bl_common)

df_sources = pd.DataFrame(rows).set_index("source")

st.subheader("Глобальные метрики по источникам (sources)")
st.dataframe(df_sources.style.format("{:.2f}"))
st.caption(f"Покрытие baseline (coverage): {coverage:.2%}" if not np.isnan(coverage) else "Покрытие baseline (coverage): n/a")
if "catboost_pred" in df_filt.columns:
    cb_cov = (df_filt["catboost_pred"].notna().mean()) if len(df_filt) else np.nan
    st.caption(f"Покрытие catboost (coverage): {cb_cov:.2%}" if not np.isnan(cb_cov) else "Покрытие catboost (coverage): n/a")

if "baseline_rule" in df_filt.columns:
    st.subheader("Как часто сработало правило baseline (baseline rule distribution)")
    st.dataframe(df_filt["baseline_rule"].value_counts(dropna=False).to_frame("count"))


st.subheader("Метрики по подразделениям (divisions)")

rows = []
for div, grp in df_filt.groupby("division_title"):
    grp_common = grp[grp["baseline_pred"].notna()]

    m_ai = compute_metrics(grp_common["fact"], grp_common["ai_pred"])
    m_ai["division_title"] = div
    m_ai["source"] = "ai"
    rows.append(m_ai)

    m_bl = compute_metrics(grp_common["fact"], grp_common["baseline_pred"])
    m_bl["division_title"] = div
    m_bl["source"] = "baseline"
    rows.append(m_bl)

    if "catboost_pred" in grp.columns:
        grp_cb = grp[grp["catboost_pred"].notna()]
        if len(grp_cb):
            m_cb = compute_metrics(grp_cb["fact"], grp_cb["catboost_pred"])
            m_cb["division_title"] = div
            m_cb["source"] = "catboost_v1"
            rows.append(m_cb)

df_div = pd.DataFrame(rows)

pivot_div = df_div.pivot_table(
    index="division_title",
    columns="source",
    values=["MAE", "MAPE_%"],
)

st.dataframe(pivot_div.style.format("{:.2f}"))


st.subheader("Динамика MAE по месяцам (months)")

rows = []
for month, grp in df_filt.groupby("month"):
    grp_common = grp[grp["baseline_pred"].notna()]
    for name, col in [("ai", "ai_pred"), ("baseline", "baseline_pred")]:
        m = compute_metrics(grp_common["fact"], grp_common[col])
        m["month"] = month
        m["source"] = name
        rows.append(m)
    if "catboost_pred" in grp.columns:
        grp_cb = grp[grp["catboost_pred"].notna()]
        if len(grp_cb):
            m = compute_metrics(grp_cb["fact"], grp_cb["catboost_pred"])
            m["month"] = month
            m["source"] = "catboost_v1"
            rows.append(m)

df_month = pd.DataFrame(rows)

if not df_month.empty:
    chart_data = df_month.pivot(index="month", columns="source", values="MAE")
    st.line_chart(chart_data)
else:
    st.write("Недостаточно данных для построения графика.")


st.subheader("Тепловая карта (heatmap) ошибок по разрезам")

metric_sel = st.selectbox(
    "Метрика (metric)",
    options=["MAE", "RMSE", "MAPE_%", "large_error_share"],
    index=0,
)

source_sel = st.selectbox(
    "Источник прогноза (source)",
    options=["ai", "baseline"] + (["catboost_v1"] if "catboost_pred" in df_filt.columns else []),
    index=0,
)

slice_sel = st.selectbox(
    "Разрез (slice)",
    options=["Подразделение × месяц", "Модель (resist_id) × месяц"],
    index=0,
)

if source_sel == "ai":
    pred_col = "ai_pred"
    df_h_base = df_filt
elif source_sel == "baseline":
    pred_col = "baseline_pred"
    df_h_base = df_common
else:
    pred_col = "catboost_pred"
    df_h_base = df_filt[df_filt["catboost_pred"].notna()]

if slice_sel.startswith("Подразделение"):
    group_keys = ["division_title", "month"]
    row_key = "division_title"
else:
    group_keys = ["resist_id", "month"]
    row_key = "resist_id"

rows = []
for keys, grp in df_h_base.groupby(group_keys):
    m = compute_metrics(grp["fact"], grp[pred_col])
    rows.append(
        {
            row_key: keys[0],
            "month": keys[1],
            metric_sel: m[metric_sel],
        }
    )

df_h = pd.DataFrame(rows)

if df_h.empty:
    st.write("Недостаточно данных для построения тепловой карты.")
else:
    pivot = df_h.pivot(index=row_key, columns="month", values=metric_sel)
    pivot.columns = pivot.columns.astype(str)

    fig = px.imshow(
        pivot,
        aspect="auto",
        color_continuous_scale="RdYlGn_r",
        labels={"color": metric_sel},
    )
    fig.update_layout(xaxis_title="Месяц (month)", yaxis_title=row_key)
    st.plotly_chart(fig, use_container_width=True)



