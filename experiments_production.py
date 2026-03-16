# config
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path("../").resolve()))

# --- Конфиг ---
RAW_DIR = Path("../data/raw")
RAW_FILES = [
    RAW_DIR / "data-2022.csv",
    RAW_DIR / "data-2023.csv",
    RAW_DIR / "data-2024.csv",
    RAW_DIR / "data-2025.csv",
]
FILTER_YEAR = 2025

# Топ-10 худших resist_id (для отдельной сводки метрик)
TOP_WORST_RESIST_IDS = [31, 47, 49, 59, 84, 88, 128, 159, 161, 195]

# Список экспериментов production-логики (True = включить)
EXPERIMENTS = {
    "production_vanilla": True,
    "production_prophet_always": True,
    "production_ets_more": True,
}





# load data
PREDICT_COMMENT = "first_predict_value_record"
EXCLUDED_RESIST_IDS = [
    25, 26, 27, 29, 54, 57, 61, 63, 66, 68, 80, 81, 82, 83, 100, 101, 102, 103,
    104, 105, 106, 109, 112, 113, 115, 116, 119, 120, 121, 122, 123, 125, 126,
    129, 131, 132, 134, 135, 136, 137, 138, 140, 141, 143, 144, 146, 147, 148,
    149, 150, 151, 152, 153, 154, 156, 157, 158, 162, 165, 169, 170, 171, 172,
    173, 174, 175, 176, 177, 178, 179, 181, 196, 51, 65, 139,
]

def to_bool(series):
    return series.astype(str).str.lower().isin(["true", "t", "1"])

def to_bool_value(value):
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return None
    return str(value).strip().lower() in ["true", "t", "1"]

def parse_division_title(div_json):
    if pd.isna(div_json):
        return None
    try:
        obj = json.loads(div_json)
    except Exception:
        return None
    return obj.get("name")

def parse_calculate_param(calc_json):
    if pd.isna(calc_json):
        return {}
    try:
        return json.loads(calc_json)
    except Exception:
        return {}

def get_calc_value(calc_obj, key):
    val = calc_obj.get(key)
    if isinstance(val, dict):
        return val.get("value")
    return val

# Загрузка CSV
dfs = []
for p in RAW_FILES:
    if p.exists():
        dfs.append(pd.read_csv(p, dtype=str))
if not dfs:
    raise FileNotFoundError("Нет CSV-файлов для загрузки.")

df_raw = pd.concat(dfs, ignore_index=True)
df_raw["period"] = pd.to_datetime(df_raw["period"], errors="coerce")
df_raw["resist_id"] = pd.to_numeric(df_raw["resist_id"], errors="coerce").astype("Int64")

if "cancel_approve" in df_raw.columns:
    df_raw["cancel_approve"] = to_bool(df_raw["cancel_approve"])
else:
    df_raw["cancel_approve"] = False
if "comment" in df_raw.columns:
    df_raw["comment"] = df_raw["comment"].fillna("")
    mask_predict = df_raw["comment"] == PREDICT_COMMENT
else:
    mask_predict = pd.Series(False, index=df_raw.index)
mask_ok = ~df_raw["cancel_approve"] & ~mask_predict & ~df_raw["resist_id"].isin(EXCLUDED_RESIST_IDS)
df_ok = df_raw[mask_ok].copy()

records = []
for _, row in df_ok.iterrows():
    calc_obj = parse_calculate_param(row.get("calculate_parameter"))
    workday = get_calc_value(calc_obj, "workDayMonth_2")
    op_raw = row.get("operation_parameter")
    if pd.isna(op_raw):
        continue
    try:
        op_data = json.loads(op_raw)
    except Exception:
        continue
    period = row.get("period")
    if pd.isna(period):
        continue
    for op_id, payload in op_data.items():
        if not isinstance(payload, dict):
            continue
        active = to_bool_value(payload.get("operation_active", payload.get("active")))
        if active is False:
            continue
        records.append({
            "resist_id": row.get("resist_id"),
            "division_title": parse_division_title(row.get("division_name")),
            "id": row.get("id"),
            "month": int(period.month),
            "year": int(period.year),
            "operation_id": op_id,
            "fact_value": payload.get("fact_value"),
            "fact_predict": payload.get("fact_predict"),
            "workDayMonth_2": workday,
            "calculate_minute": payload.get("calculate_minute"),
        })

df = pd.DataFrame(records)
df["fact_value"] = pd.to_numeric(df["fact_value"], errors="coerce")
df["fact_predict"] = pd.to_numeric(df["fact_predict"], errors="coerce")
df["workDayMonth_2"] = pd.to_numeric(df["workDayMonth_2"], errors="coerce")
df["calculate_minute"] = pd.to_numeric(df["calculate_minute"], errors="coerce")

df["coefficient_fulltime_staff"] = df["calculate_minute"] / 60 / 148.3
df["fact_fts"] = df["fact_value"] * df["coefficient_fulltime_staff"]
df["date"] = pd.to_datetime(dict(year=df["year"], month=df["month"], day=1), errors="coerce").dt.date
df = df.dropna(subset=["fact_value"])

df["_grp"] = df["resist_id"].astype(str) + "|" + df["division_title"].astype(str) + "|" + df["operation_id"].astype(str)
yr_mask = df["year"] == FILTER_YEAR
drop_idx = set()
for g in df["_grp"].unique():
    grp = df[(df["_grp"] == g) & yr_mask].sort_values("month")
    for idx in grp.index:
        fv, fp = df.at[idx, "fact_value"], df.at[idx, "fact_predict"]
        if (pd.isna(fv) or float(fv) == 0) and (pd.isna(fp) or float(fp) == 0):
            drop_idx.add(idx)
        else:
            break
df = df.drop(index=list(drop_idx)).drop(columns=["_grp"]).reset_index(drop=True)
df = df.sort_values(["operation_id", "year", "month"]).reset_index(drop=True)

group = df.groupby("operation_id")
df["lag_1"] = group["fact_value"].shift(1)
df["lag_12"] = group["fact_value"].shift(12)
df["roll_mean_3"] = group["fact_value"].transform(lambda s: s.shift(1).rolling(3, min_periods=3).mean())
df["roll_mean_6"] = group["fact_value"].transform(lambda s: s.shift(1).rolling(6, min_periods=6).mean())
df["trend"] = df["lag_1"] / df["roll_mean_3"]
df["trend"] = df["trend"].replace([np.inf, -np.inf], 0)
num_cols = df.select_dtypes(include=["number"]).columns
df[num_cols] = df[num_cols].fillna(0)
df = df.infer_objects(copy=False)

print(f"Данных: {len(df)} строк")





# Экспресс-анализ: топ-10 худших resist_id
focus = df[df["resist_id"].isin(TOP_WORST_RESIST_IDS)]
for rid in TOP_WORST_RESIST_IDS:
    sub = focus[focus["resist_id"] == rid]
    if sub.empty:
        print(f"resist_id={rid}: нет данных")
        continue
    n_ops = sub["operation_id"].nunique()
    n_rows = len(sub)
    n_small = (sub["fact_value"] < 50).sum()
    n_large = (sub["fact_value"] >= 50).sum()
    mean_fact = sub["fact_value"].mean()
    pct_zero = (sub["fact_value"] == 0).mean() * 100
    # lag_12 != 0 означает что была история (fillna(0) в пайплайне — 0 ставится вместо NaN)
    has_lag12 = (sub["lag_12"] != 0).sum()
    pct_has_history = has_lag12 / len(sub) * 100 if len(sub) > 0 else 0
    print(f"resist_id={rid}: n_rows={n_rows}, n_operations={n_ops}, "
          f"мелкие(<50)={n_small} ({n_small/len(sub)*100:.1f}%), крупные={n_large}, "
          f"mean_fact={mean_fact:.1f}, нули={pct_zero:.1f}%, есть_lag12={pct_has_history:.1f}%")






# function metrics
def calc_mae(y_true, y_pred):
    return np.mean(np.abs(np.array(y_true) - np.array(y_pred)))

def calc_rmse(y_true, y_pred):
    return np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2))

def calc_mape(y_true, y_pred):
    y_true, y_pred = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    err = np.empty_like(y_true)
    mask_zero = y_true == 0
    err[mask_zero] = np.where(y_pred[mask_zero] == 0, 0.0, 100.0)
    mask_ok = ~mask_zero
    if np.any(mask_ok):
        err[mask_ok] = np.abs(y_true[mask_ok] - y_pred[mask_ok]) / np.abs(y_true[mask_ok]) * 100
    return float(np.mean(err))

def calc_wmape(y_true, y_pred):
    y_true, y_pred = np.array(y_true), np.array(y_pred)
    s_abs_err = np.sum(np.abs(y_true - y_pred))
    s_fact = np.sum(np.abs(y_true))
    if s_fact == 0:
        return 0.0
    return s_abs_err / s_fact * 100

def calc_smape(y_true, y_pred):
    y_true, y_pred = np.array(y_true), np.array(y_pred)
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2
    mask = denom != 0
    if not np.any(mask):
        return 0.0
    return np.mean(np.where(mask, np.abs(y_true - y_pred) / denom * 100, 0))

def calc_accuracy_pct(y_true, y_pred):
    y_true, y_pred = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    acc = np.empty_like(y_true)
    mask_zero = y_true == 0
    acc[mask_zero] = np.where(y_pred[mask_zero] == 0, 100.0, 0.0)
    mask_ok = ~mask_zero
    if np.any(mask_ok):
        acc[mask_ok] = np.clip(100.0 - np.abs(y_true[mask_ok] - y_pred[mask_ok]) / np.abs(y_true[mask_ok]) * 100.0, 0, 100)
    return acc

def calc_mean_accuracy(y_true, y_pred):
    acc = calc_accuracy_pct(y_true, y_pred)
    return float(np.mean(acc))

def calc_stability(y_true, y_pred):
    acc = calc_accuracy_pct(y_true, y_pred)
    mean_acc = np.mean(acc)
    if mean_acc == 0:
        return 0.0
    cv = np.std(acc, ddof=0) / mean_acc
    return max(0.0, (1 - cv)) * 100

def calc_quality(y_true, y_pred):
    acc = calc_mean_accuracy(y_true, y_pred)
    stab = calc_stability(y_true, y_pred)
    if acc + stab == 0:
        return 0.0
    return 2 * acc * stab / (acc + stab)

def compute_all_metrics(y_true, y_pred, subset_name=""):
    prefix = f"[{subset_name}] " if subset_name else ""
    mae = calc_mae(y_true, y_pred)
    rmse = calc_rmse(y_true, y_pred)
    mape = calc_mape(y_true, y_pred)
    wmape = calc_wmape(y_true, y_pred)
    acc = calc_mean_accuracy(y_true, y_pred)
    stab = calc_stability(y_true, y_pred)
    qi = calc_quality(y_true, y_pred)
    return {"MAE": mae, "RMSE": rmse, "MAPE": mape, "WMAPE": wmape, "Точность": acc, "Стабильность": stab, "Качество": qi}






# metrics more
def run_metrics_summary(df_test, y_true, y_pred, experiment_name):
    """Сводка метрик: всего, по strata (мелкие/крупные), по TOP_WORST_RESIST_IDS."""
    df_test = df_test.copy()
    df_test["_y_true"] = y_true
    df_test["_y_pred"] = y_pred
    df_test["_acc"] = calc_accuracy_pct(y_true, y_pred)

    rows = []

    # Всего
    m_all = compute_all_metrics(y_true, y_pred)
    acc_arr = calc_accuracy_pct(y_true, y_pred)
    m_all["acc_min"] = float(np.min(acc_arr))
    m_all["acc_max"] = float(np.max(acc_arr))
    m_all["acc_median"] = float(np.median(acc_arr))
    m_all["acc_std"] = float(np.std(acc_arr))
    rows.append({"experiment": experiment_name, "subset": "всего", "n": len(y_true), **m_all})

    # По стратам: мелкие (fact < 50), крупные (fact >= 50)
    mask_small = np.array(y_true) < 50
    mask_large = np.array(y_true) >= 50
    if np.sum(mask_small) > 0:
        m_small = compute_all_metrics(np.array(y_true)[mask_small], np.array(y_pred)[mask_small])
        rows.append({"experiment": experiment_name, "subset": "мелкие (fact<50)", "n": int(np.sum(mask_small)), **m_small})
    if np.sum(mask_large) > 0:
        m_large = compute_all_metrics(np.array(y_true)[mask_large], np.array(y_pred)[mask_large])
        rows.append({"experiment": experiment_name, "subset": "крупные (fact>=50)", "n": int(np.sum(mask_large)), **m_large})

    # По resist_id in TOP_WORST_RESIST_IDS
    mask_top = df_test["resist_id"].isin(TOP_WORST_RESIST_IDS)
    if np.sum(mask_top) > 0:
        yt = df_test.loc[mask_top, "_y_true"].values
        yp = df_test.loc[mask_top, "_y_pred"].values
        m_top = compute_all_metrics(yt, yp)
        rows.append({"experiment": experiment_name, "subset": "resist_id топ-10 худших", "n": int(np.sum(mask_top)), **m_top})

    return pd.DataFrame(rows)






# Импорт production-прогноза (Prophet, ETS, MA, среднее)
from production_forecast import run_production_experiment

# variant: "vanilla" | "prophet_always" | "ets_more"
EXPERIMENT_VARIANTS = {
    "production_vanilla": "vanilla",
    "production_prophet_always": "prophet_always",
    "production_ets_more": "ets_more",
}




# experiments

results_all = []
last_year = int(df["year"].max())
test_df = df[df["year"] == last_year].copy().reset_index(drop=True)
y_test = test_df["fact_value"].values

pred = np.array([])
for exp_name, variant in EXPERIMENT_VARIANTS.items():
    if not EXPERIMENTS.get(exp_name, False):
        continue
    pred = run_production_experiment(df, last_year, variant=variant)
    r = run_metrics_summary(test_df, y_test, pred, exp_name)
    results_all.append(r)
    print(f"{exp_name}: готово")







# svod table

from IPython.display import display
if results_all:
    summary = pd.concat(results_all, ignore_index=True)
    base_cols = ["experiment", "subset", "n", "MAE", "RMSE", "MAPE", "WMAPE", "Точность", "Стабильность", "Качество"]
    extra_cols = ["acc_min", "acc_max", "acc_median", "acc_std"]
    display_cols = base_cols + [c for c in extra_cols if c in summary.columns]
    summary = summary[[c for c in display_cols if c in summary.columns]]
    display(summary)
else:
    print("Нет результатов. Проверьте: 1) Запустите ячейки 11–19 (эксперименты). 2) Нет ли ошибок в ячейках выше.")







# Сводка по ключевым подмножествам
if results_all:
    s = summary[summary["subset"].isin(["всего", "resist_id топ-10 худших", "мелкие (fact<50)", "крупные (fact>=50)"])]
    display(s)
else:
    print("Нет результатов. Сначала запустите ячейки с экспериментами (секция 5).")






# Сравнение: fact_predict vs Production по resist_id (показатель Качество)
# pred — от последнего выполненного эксперимента

if not results_all:
    print("Сначала запустите эксперименты (секция 5).")
else:
    comp = test_df.copy()
    comp["pred_production"] = pred
    comp["fact_predict"] = comp["fact_predict"].fillna(0)

    def quality_by_resist_id(g):
        return calc_quality(g["fact_value"].values, g["pred_production"].values)

    def quality_fp_by_resist_id(g):
        return calc_quality(g["fact_value"].values, g["fact_predict"].values)

    q_prod = comp.groupby("resist_id").apply(quality_by_resist_id)
    q_fp = comp.groupby("resist_id").apply(quality_fp_by_resist_id)

    common = q_fp.index.intersection(q_prod.index)
    better_mask = q_prod.loc[common] > q_fp.loc[common]
    diff = pd.DataFrame({"Качество fact_predict": q_fp, "Качество Production": q_prod})
    diff["Δ Качество"] = diff["Качество Production"] - diff["Качество fact_predict"]
    diff = diff.sort_values("Δ Качество", ascending=False)

    better_diff = diff.loc[common][better_mask].sort_values("Δ Качество", ascending=False)
    better_resist_ids = better_diff.index.tolist()

    print("resist_id, по которым Production лучше (качество выше):", better_resist_ids)
    print("\nΔ Качество (Production - fact_predict) по каждому:")
    for rid in better_resist_ids:
        d = better_diff.loc[rid, "Δ Качество"]
        print(f"  {rid}: Δ = +{d:.2f}")
    print(f"\nВсего: {len(better_resist_ids)} из {len(common)} resist_id")
    display(diff)
