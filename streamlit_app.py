"""
Streamlit: метрики Точность / Стабильность / Качество по выходным Excel из
build_model_comparison_dashboard.py (лист «Данные», файлы *dashboard*.xlsx в data/processed).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard_dannye_io import (
    discover_dashboard_files,
    division_stats_dual,
    global_metrics_from_acc,
    heatmap_quality_matrix,
    load_dannye_from_file,
)

ROOT = Path(__file__).resolve().parent
PROCESSED_DIR = ROOT / "data" / "processed"


@st.cache_data(show_spinner=True)
def _cached_one_dashboard(path_resolved: str) -> pd.DataFrame:
    p = Path(path_resolved)
    return load_dannye_from_file(p, dashboard_file=p.name)


def main() -> None:
    import plotly.express as px

    st.set_page_config(page_title="Дашборд прогнозов (Excel)", layout="wide")

    st.sidebar.header("Источник данных (data source)")
    if not PROCESSED_DIR.is_dir():
        st.error(f"Каталог не найден: `{PROCESSED_DIR}`")
        st.stop()

    all_files = discover_dashboard_files(PROCESSED_DIR)
    if not all_files:
        st.warning(
            f"В `{PROCESSED_DIR}` нет файлов `*dashboard*.xlsx`. "
            "Соберите дашборд: `python scripts/build_model_comparison_dashboard.py`."
        )
        st.stop()

    names = [p.name for p in all_files]
    name_to_path = {p.name: p for p in all_files}

    selected_names = st.sidebar.multiselect(
        "Файлы Excel (включить в анализ)",
        options=names,
        default=names,
        help="Выбранные файлы объединяются; снимите галочку, чтобы убрать файл из расчётов.",
    )

    if not selected_names:
        st.info("Выберите хотя бы один файл в боковой панели (sidebar).")
        st.stop()

    frames_acc: list[pd.DataFrame] = []
    load_errors: list[str] = []
    for n in selected_names:
        p = name_to_path[n]
        try:
            frames_acc.append(_cached_one_dashboard(str(p.resolve())))
        except Exception as e:
            load_errors.append(f"{n}: {e}")
    for msg in load_errors:
        st.warning(msg)

    try:
        df_all = pd.concat(frames_acc, ignore_index=True) if frames_acc else pd.DataFrame()
    except Exception as e:
        st.error(f"Ошибка объединения (concat): {e}")
        st.stop()

    if df_all.empty:
        st.warning("После фильтрации строк данных нет (проверьте лист «Данные»).")
        st.stop()

    st.sidebar.header("Фильтры (filters)")

    years = sorted(df_all["year"].dropna().astype(int).unique().tolist()) if "year" in df_all.columns else []
    if years:
        y_min, y_max = int(min(years)), int(max(years))
        # Streamlit slider (slider) требует min_value < max_value
        if y_min == y_max:
            year_range = (y_min, y_max)
            st.sidebar.caption(f"Год (year): **{y_min}** — в данных только один год.")
        else:
            year_range = st.sidebar.slider("Год (year range)", y_min, y_max, (y_min, y_max))
    else:
        year_range = None

    months_all = sorted(df_all["month"].dropna().astype(int).unique().tolist())
    month_pick = st.sidebar.multiselect(
        "Месяцы (months)",
        options=months_all,
        default=months_all,
    )

    rids = sorted(
        df_all["resist_id"].dropna().unique().tolist(),
        key=lambda x: (0, x) if isinstance(x, (int, float)) and not pd.isna(x) else (1, str(x)),
    )
    rid_pick = st.sidebar.multiselect(
        "Модель resist_id (опционально)",
        options=rids,
        default=[],
        help="Пусто — все модели.",
    )

    if "division_title" in df_all.columns and df_all["division_title"].notna().any():
        divs = sorted(df_all["division_title"].dropna().astype(str).unique().tolist())
        div_pick = st.sidebar.multiselect("Подразделение (division)", options=divs, default=[])
    else:
        div_pick = []

    df_f = df_all.copy()
    if year_range is not None and "year" in df_f.columns:
        df_f = df_f[df_f["year"].between(year_range[0], year_range[1])]
    if month_pick:
        df_f = df_f[df_f["month"].isin(month_pick)]
    if rid_pick:
        df_f = df_f[df_f["resist_id"].isin(rid_pick)]
    if div_pick:
        df_f = df_f[df_f["division_title"].isin(div_pick)]

    st.title("Сравнение прогнозов: Точность, Стабильность, Качество (quality)")
    st.caption(
        "Данные с листа «Данные» в выходных файлах `*dashboard*.xlsx` "
        f"({PROCESSED_DIR}). Метрики как в build_model_comparison_dashboard / build_metrics_dashboard_simple."
    )
    st.write(f"Строк после фильтров: **{len(df_f):,}** (файлов: {len(selected_names)})")

    with st.expander("Как считаются метрики (metrics)"):
        st.markdown(
            """
- **Построчная точность (forecast accuracy, %):** при `fact_value == 0` — 100 если прогноз 0, иначе 0;
  иначе `clip(100 - |fact - pred| / fact * 100, 0, 100)`.
- **Точность (accuracy):** среднее арифметическое построчной точности по выборке.
- **Стабильность (stability):** `(1 - CV) * 100%`, где `CV = std(accuracy_pct) / mean(accuracy_pct)` (ddof=0).
- **Качество (quality):** гармоническое среднее точности и стабильности: `2 * acc * stab / (acc + stab)`.

**Текущий** — колонки `accuracy_*` для `fact_predict`. **Выбранный лучший** — `accuracy_pct_chosen` / `predict_chosen`.
"""
        )

    m_acc, stab, qi = global_metrics_from_acc(df_f, "accuracy_pct")
    m_acc_c, stab_c, qi_c = global_metrics_from_acc(df_f, "accuracy_pct_chosen")

    kpi_cols = st.columns(6)
    labels_a = ["Точность (Текущий), %", "Стабильность (Текущий), %", "Качество (Текущий), %"]
    labels_b = ["Точность (выбранный), %", "Стабильность (выбранный), %", "Качество (выбранный), %"]
    vals_a = [m_acc, stab, qi]
    vals_b = [m_acc_c, stab_c, qi_c]
    for i in range(3):
        kpi_cols[i].metric(labels_a[i], f"{vals_a[i]:.2f}")
    for i in range(3):
        kpi_cols[i + 3].metric(labels_b[i], f"{vals_b[i]:.2f}")

    sum_fact = int(pd.to_numeric(df_f["fact_value"], errors="coerce").fillna(0).sum())
    sum_pred = int(pd.to_numeric(df_f["fact_predict"], errors="coerce").fillna(0).sum())
    sum_chosen = int(pd.to_numeric(df_f["predict_chosen"], errors="coerce").fillna(0).sum())
    st.caption(
        f"Факт всего: {sum_fact:,} · Прогноз (текущий) всего: {sum_pred:,} · "
        f"Прогноз (выбранный) всего: {sum_chosen:,}"
    )

    st.subheader("По моделям (resist_id)")
    div_stats = division_stats_dual(df_f)
    if not div_stats.empty:
        display_cols = [
            c
            for c in [
                "dashboard_file",
                "resist_id",
                "division_title",
                "mean_accuracy",
                "stability",
                "quality_index",
                "mean_accuracy_new",
                "stability_new",
                "quality_index_new",
                "fact_sum",
                "best_model_name",
            ]
            if c in div_stats.columns
        ]
        st.dataframe(
            div_stats[display_cols].sort_values(
                ["quality_index"] if "quality_index" in div_stats.columns else display_cols[:1],
                ascending=False,
                na_position="last",
            ),
            use_container_width=True,
        )

    st.subheader("Тепловая карта (heatmap): качество (%) по месяцам")
    df_h = df_f.copy()
    if len(selected_names) > 1:
        df_h["_heatmap_row"] = df_h["dashboard_file"].astype(str) + " | " + df_h["resist_id"].astype(str)
        row_key = "_heatmap_row"
    else:
        row_key = "resist_id"

    acc_choice = st.radio(
        "База для ячеек (accuracy column)",
        options=[
            ("accuracy_pct", "Текущий (fact_predict)"),
            ("accuracy_pct_chosen", "Выбранный лучший"),
        ],
        format_func=lambda x: x[1],
        horizontal=True,
    )
    acc_col_h = acc_choice[0]

    mat = heatmap_quality_matrix(df_h, acc_col_h, row_key)
    if mat.empty:
        st.write("Недостаточно данных для тепловой карты.")
    else:
        fig = px.imshow(
            mat,
            aspect="auto",
            color_continuous_scale="RdYlGn",
            zmin=0,
            zmax=100,
            labels=dict(x="Месяц (month)", y=row_key, color="Качество, %"),
        )
        fig.update_layout(xaxis_title="Месяц (month)", yaxis_title="Модель (model)")
        st.plotly_chart(fig, use_container_width=True)

    st.sidebar.markdown("---")
    st.sidebar.caption("Перезагрузите страницу (rerun), если добавили новые xlsx в data/processed.")


if __name__ == "__main__":
    main()
