import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
import plotly.express as px
import re


DATA_PATH = Path("data/processed/operations_from_history.csv")
WORKLOAD_PATH = Path("data/processed/workload_from_history.csv")
EXCEL_SVOD_CSV = Path("data/processed/excel_svod_workload.csv")
CATBOOST_PRED_CSV = Path("data/processed/model_predictions_catboost_v1.csv")
SHOW_EXCEL_BLOCK = False  # вернуть Excel блок -> поставь True


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


def normalize_title(name: str):
    if pd.isna(name):
        return None
    s = str(name).strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[\"'“”«»]", "", s)
    return s


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


st.sidebar.header("Режим (mode)")
mode = st.sidebar.selectbox(
    "Режим (mode)",
    ["Workload (нагрузка, %)", "Operations (операции)"],
    index=0,
)

if mode.startswith("Workload"):
    METRICS_KW = dict(large_abs=10, large_pct=0.1)
    df = load_workload_data(WORKLOAD_PATH)
    # baseline по нагрузке строим на уровне resist_id
    df = add_hybrid_baseline(df, group_keys=["resist_id"], window=6, min_periods=3)
    value_label = "нагрузки (workload, %)"
    fact_col = "fact_pct"
    ai_col = "ai_pct"
    baseline_col = "baseline_pct"
    catboost_col = "catboost_pct"
else:
    METRICS_KW = dict(large_abs=100, large_pct=0.3)
    df = load_data(DATA_PATH)
    # baseline по операциям строим на уровне resist_id + operation_id
    df = add_hybrid_baseline(df, group_keys=["resist_id", "operation_id"], window=6, min_periods=3)
    value_label = "операций (operations)"
    fact_col = "fact"
    ai_col = "ai_pred"
    baseline_col = "baseline_pred"
    catboost_col = "catboost_pred"

# правило (rule): показываем только 2025 (test year)
df = df[df["period"].dt.year == 2025].copy()
st.caption("Режим test (test): данные только за 2025 год (year)")

if mode.startswith("Workload"):
    # приводим DB к процентам (percent) — catboost добавим после merge
    df["fact_pct"] = df["fact"] * 100.0
    df["ai_pct"] = df["ai_pred"] * 100.0
    df["baseline_pct"] = df["baseline_pred"] * 100.0

    with st.expander("Как считается baseline"):
        st.markdown(
            "- **year_ago (year-over-year)**: `baseline(t) = fact(t - 12 months)`\n"
            "- **rolling_median (rolling median)**: `median(fact(t-1)...fact(t-6))` при >=3 значениях\n"
            "- **last_value (last observation)**: `baseline(t) = fact(t-1)`\n"
            "- **global_median (global median)**: `median(fact)` по всей истории (history)\n"
            "\n"
            "Порядок (order): year_ago → rolling_median → last_value → global_median.\n"
        )

    with st.expander("Как считается MAE"):
        st.markdown(
            "**MAE (mean absolute error)** — средняя абсолютная ошибка (absolute error):\n"
            "\n"
            "`MAE = mean(|y_pred - y_true|)`\n"
            "\n"
            "В нашем случае — средняя ошибка в **процентных пунктах (percentage points)**.\n"
        )

    with st.expander("Как считается RMSE"):
        st.markdown(
            "**RMSE (root mean squared error)** — корень из средней квадратичной ошибки (squared error):\n"
            "\n"
            "`RMSE = sqrt(mean((y_pred - y_true)^2))`\n"
            "\n"
            "Чувствительна к большим ошибкам (large errors).\n"
        )

    with st.expander("Как считается MAPE_%"):
        st.markdown(
            "**MAPE_% (mean absolute percentage error)** — средняя относительная ошибка в процентах (percent):\n"
            "\n"
            "`MAPE = mean(|(y_pred - y_true) / y_true|) * 100%`\n"
            "\n"
            "Считается только там, где `y_true != 0`.\n"
        )

    with st.expander("Как считается large_error_share"):
        st.markdown(
            "**large_error_share** — доля больших ошибок (large errors):\n"
            "\n"
            "Ошибка считается большой, если:\n"
            "- `|y_pred - y_true| > 10` **или**\n"
            "- `|y_pred - y_true| > 0.1 * |y_true|`\n"
            "\n"
            "Порог (threshold) сейчас соответствует режиму Workload (workload).\n"
        )

    if CATBOOST_PRED_CSV.exists():
        df_cb = load_catboost_predictions(CATBOOST_PRED_CSV)
        df = df.merge(
            df_cb[["resist_id", "period", "catboost_pred"]],
            on=["resist_id", "period"],
            how="left",
        )
        # теперь можно считать catboost_pct
        df["catboost_pct"] = df["catboost_pred"] * 100.0
    else:
        st.caption("Нет CSV (CSV) с CatBoost (CatBoost): data/processed/model_predictions_catboost_v1.csv")

    if SHOW_EXCEL_BLOCK:
        if EXCEL_SVOD_CSV.exists():
            st.subheader("Excel (Excel): сводный отчёт (summary report) по нагрузке (workload)")
            st.caption("Excel ML/manual временно отключены из‑за парсинга (parsing).")
        else:
            st.caption("Нет Excel CSV: data/processed/excel_svod_workload.csv (сначала запусти notebooks/export_svod_to_csv.ipynb)")
else:
    if CATBOOST_PRED_CSV.exists():
        df_cb = load_catboost_predictions(CATBOOST_PRED_CSV)
        df = df.merge(
            df_cb[["resist_id", "period", "catboost_pred"]],
            on=["resist_id", "period"],
            how="left",
        )
    else:
        st.caption("Нет CSV (CSV) с CatBoost (CatBoost): data/processed/model_predictions_catboost_v1.csv")


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

st.subheader(f"Сравнение значений {value_label} по месяцам (months)")

# агрегируем по месяцу (mean) и показываем 4 ряда: fact/ai/catboost/baseline
df_cmp = (
    df_filt.groupby("month", as_index=False)
    .agg(
        fact=(fact_col, "mean"),
        ai=(ai_col, "mean"),
        baseline=(baseline_col, "mean"),
    )
)
if catboost_col in df_filt.columns:
    df_cb_month = (
        df_filt.groupby("month", as_index=False)
        .agg(catboost=(catboost_col, "mean"))
    )
    df_cmp = df_cmp.merge(df_cb_month, on="month", how="left")

df_cmp_display = df_cmp.copy()
# месяц в формате YYYY-MM
df_cmp_display["month"] = df_cmp_display["month"].dt.strftime("%Y-%m")
# округляем значения до целых
num_cols = [c for c in df_cmp_display.columns if c != "month"]
df_cmp_display[num_cols] = df_cmp_display[num_cols].round(0)
st.dataframe(df_cmp_display)

chart_cols = ["fact", "ai", "baseline"]
if "catboost" in df_cmp.columns:
    chart_cols.insert(2, "catboost")

# подписи месяцев для оси (axis)
df_cmp_chart = df_cmp.copy()
df_cmp_chart["month_label"] = df_cmp_chart["month"].dt.strftime("%b %Y")
st.line_chart(df_cmp_chart.set_index("month_label")[chart_cols])

sources = {
    "ai": df_filt[ai_col],
    "baseline": df_filt[baseline_col],
}
if catboost_col in df_filt.columns:
    sources["catboost_v1"] = df_filt[catboost_col]

df_common = df_filt[df_filt["baseline_pred"].notna()].copy()
coverage = (len(df_common) / len(df_filt)) if len(df_filt) else np.nan

rows = []

# AI на всех данных (ai)
m_ai_all = compute_metrics(df_filt[fact_col], df_filt[ai_col], **METRICS_KW)
m_ai_all["source"] = "ai"
rows.append(m_ai_all)

# CatBoost на всех данных (catboost_all)
if catboost_col in df_filt.columns:
    df_cb = df_filt[df_filt[catboost_col].notna()]
    m_cb_all = compute_metrics(df_cb[fact_col], df_cb[catboost_col], **METRICS_KW)
    m_cb_all["source"] = "catboost_v1"
    rows.append(m_cb_all)

# AI на общем пересечении с baseline (ai_common) — убираем из отображения

# baseline на общем пересечении (baseline_common)
m_bl_common = compute_metrics(df_common[fact_col], df_common[baseline_col], **METRICS_KW)
m_bl_common["source"] = "baseline_common"
rows.append(m_bl_common)

df_sources = pd.DataFrame(rows).set_index("source")

st.subheader("Глобальные метрики по источникам (sources)")
st.dataframe(df_sources.style.format("{:.2f}"))
st.caption(f"Покрытие baseline (coverage): {coverage:.2%}" if not np.isnan(coverage) else "Покрытие baseline (coverage): n/a")
if catboost_col in df_filt.columns:
    cb_cov = (df_filt[catboost_col].notna().mean()) if len(df_filt) else np.nan
    st.caption(f"Покрытие catboost (coverage): {cb_cov:.2%}" if not np.isnan(cb_cov) else "Покрытие catboost (coverage): n/a")

if "baseline_rule" in df_filt.columns:
    st.subheader("Как часто сработало правило baseline (baseline rule distribution)")
    st.dataframe(df_filt["baseline_rule"].value_counts(dropna=False).to_frame("count"))


st.subheader("Метрики по подразделениям (divisions)")

rows = []
for div, grp in df_filt.groupby("division_title"):
    grp_common = grp[grp["baseline_pred"].notna()]

    m_ai = compute_metrics(grp_common[fact_col], grp_common[ai_col], **METRICS_KW)
    m_ai["division_title"] = div
    m_ai["source"] = "ai"
    rows.append(m_ai)

    m_bl = compute_metrics(grp_common[fact_col], grp_common[baseline_col], **METRICS_KW)
    m_bl["division_title"] = div
    m_bl["source"] = "baseline"
    rows.append(m_bl)

    if catboost_col in grp.columns:
        grp_cb = grp[grp[catboost_col].notna()]
        if len(grp_cb):
            m_cb = compute_metrics(grp_cb[fact_col], grp_cb[catboost_col], **METRICS_KW)
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
    for name, col in [("ai", ai_col), ("baseline", baseline_col)]:
        m = compute_metrics(grp_common[fact_col], grp_common[col], **METRICS_KW)
        m["month"] = month
        m["source"] = name
        rows.append(m)
    if catboost_col in grp.columns:
        grp_cb = grp[grp[catboost_col].notna()]
        if len(grp_cb):
            m = compute_metrics(grp_cb[fact_col], grp_cb[catboost_col], **METRICS_KW)
            m["month"] = month
            m["source"] = "catboost_v1"
            rows.append(m)

df_month = pd.DataFrame(rows)

if not df_month.empty:
    chart_data = df_month.pivot(index="month", columns="source", values="MAE")
    st.line_chart(chart_data)
else:
    st.write("Недостаточно данных для построения графика.")


st.subheader("Тепловая карта (heatmap) ошибок по разрезам: Модель (resist_id) × месяц")

metric_sel = st.selectbox(
    "Метрика (metric)",
    options=["MAE", "RMSE", "MAPE_%", "large_error_share"],
    index=0,
)

source_sel = st.selectbox(
    "Источник прогноза (source)",
    options=["ai", "baseline"] + (["catboost_v1"] if catboost_col in df_filt.columns else []),
    index=0,
)

if source_sel == "ai":
    pred_col = ai_col
elif source_sel == "baseline":
    pred_col = baseline_col
else:
    pred_col = catboost_col

# общий набор (common set) для всех источников
common_cols = [fact_col, ai_col, baseline_col]
if catboost_col in df_filt.columns:
    common_cols.append(catboost_col)
df_h_base = df_filt.dropna(subset=common_cols).copy()

# фиксированный разрез: resist_id × month
group_keys = ["resist_id", "month"]
row_key = "resist_id"

rows = []
for keys, grp in df_h_base.groupby(group_keys):
    m = compute_metrics(grp[fact_col], grp[pred_col], **METRICS_KW)
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



