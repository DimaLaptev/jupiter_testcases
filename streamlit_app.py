import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
import plotly.express as px


DATA_PATH = Path("data/processed/operations_from_history.csv")


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
    df["month_prev"] = df["month"] - 12

    prev = (
        df[key + ["month", "fact"]]
        .rename(columns={"month": "month_prev", "fact": "fact_prev"})
    )

    df = df.merge(prev, on=key + ["month_prev"], how="left")
    df["baseline_pred"] = df["fact_prev"]
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


df = load_data(DATA_PATH)
df = add_baseline(df)


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


st.title("Оценка качества прогноза количества операций (operations)")
st.write(f"Строк после фильтрации: {len(df_filt):,}")


sources = {
    "ai": df_filt["ai_pred"],
    "baseline": df_filt["baseline_pred"],
}

rows = []
for name, y_pred in sources.items():
    m = compute_metrics(df_filt["fact"], y_pred)
    m["source"] = name
    rows.append(m)

df_sources = pd.DataFrame(rows).set_index("source")

st.subheader("Глобальные метрики по источникам (sources)")
st.dataframe(df_sources.style.format("{:.2f}"))


st.subheader("Метрики по подразделениям (divisions)")

rows = []
for div, grp in df_filt.groupby("division_title"):
    for name, col in [("ai", "ai_pred"), ("baseline", "baseline_pred")]:
        m = compute_metrics(grp["fact"], grp[col])
        m["division_title"] = div
        m["source"] = name
        rows.append(m)

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
    for name, col in [("ai", "ai_pred"), ("baseline", "baseline_pred")]:
        m = compute_metrics(grp["fact"], grp[col])
        m["month"] = month
        m["source"] = name
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
    options=["ai", "baseline"],
    index=0,
)

slice_sel = st.selectbox(
    "Разрез (slice)",
    options=["Подразделение × месяц", "Модель (resist_id) × месяц"],
    index=0,
)

pred_col = "ai_pred" if source_sel == "ai" else "baseline_pred"

if slice_sel.startswith("Подразделение"):
    group_keys = ["division_title", "month"]
    row_key = "division_title"
else:
    group_keys = ["resist_id", "month"]
    row_key = "resist_id"

rows = []
for keys, grp in df_filt.groupby(group_keys):
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



