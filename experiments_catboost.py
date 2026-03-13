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

# Список экспериментов CatBoost (True = включить)
EXPERIMENTS = {
    "catboost_rmse": True,
    "catboost_mae": True,
    "catboost_sample_weight_sqrt": True,
    "catboost_sample_weight_log1p": True,
    "catboost_sample_weight_linear": True,
    "catboost_hyperparams": True,
    "catboost_hybrid": True,
}




# load and prepare data

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




# metrics
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




# svodka metric

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



# base pipeline


from sklearn.linear_model import Ridge
from sklearn.preprocessing import LabelEncoder

CAT_COLS = ["operation_id", "division_title", "resist_id"]
NUM_COLS = ["month", "year", "workDayMonth_2", "calculate_minute", "coefficient_fulltime_staff",
            "lag_1", "lag_12", "roll_mean_3", "roll_mean_6", "trend"]
FEATURE_COLS = CAT_COLS + NUM_COLS
TARGET_COL = "fact_value"

def prepare_train_test_catboost(df):
    """Для CatBoost: категориальные остаются строками (cat_features)."""
    last_year = df["year"].max()
    train_df = df[df["year"] < last_year].copy()
    test_df = df[df["year"] == last_year].copy()
    for c in CAT_COLS:
        train_df[c] = train_df[c].astype(str).fillna("")
        test_df[c] = test_df[c].astype(str).fillna("")
    return train_df, test_df, FEATURE_COLS

def train_catboost(X_train, y_train, X_test, y_test, loss_function="MAE", sample_weight=None, **kwargs):
    from catboost import CatBoostRegressor
    cat_idx = [FEATURE_COLS.index(c) for c in CAT_COLS if c in FEATURE_COLS]
    m = CatBoostRegressor(
        iterations=kwargs.get("iterations", 1000),
        depth=kwargs.get("depth", 6),
        learning_rate=kwargs.get("learning_rate", 0.1),
        loss_function=loss_function,
        random_state=42,
        verbose=0,
        cat_features=cat_idx,
    )
    m.fit(X_train, y_train, eval_set=(X_test, y_test), sample_weight=sample_weight)
    return m




 # experiments

 results_all = []

# CatBoost RMSE (baseline)
if EXPERIMENTS.get("catboost_rmse", True):
    train_df, test_df, feats = prepare_train_test_catboost(df)
    X_train, X_test = train_df[feats], test_df[feats]
    y_train, y_test = train_df[TARGET_COL], test_df[TARGET_COL]
    model = train_catboost(X_train, y_train, X_test, y_test, loss_function="RMSE")
    pred = np.maximum(model.predict(X_test), 0)
    r = run_metrics_summary(test_df, y_test.values, pred, "catboost_rmse")
    results_all.append(r)
    print("catboost_rmse: готово")

# CatBoost MAE
if EXPERIMENTS.get("catboost_mae", True):
    train_df, test_df, feats = prepare_train_test_catboost(df)
    X_train, X_test = train_df[feats], test_df[feats]
    y_train, y_test = train_df[TARGET_COL], test_df[TARGET_COL]
    model = train_catboost(X_train, y_train, X_test, y_test, loss_function="MAE")
    pred = np.maximum(model.predict(X_test), 0)
    r = run_metrics_summary(test_df, y_test.values, pred, "catboost_mae")
    results_all.append(r)
    print("catboost_mae: готово")

# CatBoost sample_weight sqrt
if EXPERIMENTS.get("catboost_sample_weight_sqrt", True):
    train_df, test_df, feats = prepare_train_test_catboost(df)
    X_train, X_test = train_df[feats], test_df[feats]
    y_train, y_test = train_df[TARGET_COL], test_df[TARGET_COL]
    cm = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    sw = np.sqrt(np.maximum(cm, 0.1))
    model = train_catboost(X_train, y_train, X_test, y_test, loss_function="MAE", sample_weight=sw)
    pred = np.maximum(model.predict(X_test), 0)
    r = run_metrics_summary(test_df, y_test.values, pred, "catboost_sample_weight_sqrt")
    results_all.append(r)
    print("catboost_sample_weight_sqrt: готово")

# CatBoost sample_weight log1p
if EXPERIMENTS.get("catboost_sample_weight_log1p", True):
    train_df, test_df, feats = prepare_train_test_catboost(df)
    X_train, X_test = train_df[feats], test_df[feats]
    y_train, y_test = train_df[TARGET_COL], test_df[TARGET_COL]
    cm = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    sw = np.log1p(np.maximum(cm, 0.1))
    model = train_catboost(X_train, y_train, X_test, y_test, loss_function="MAE", sample_weight=sw)
    pred = np.maximum(model.predict(X_test), 0)
    r = run_metrics_summary(test_df, y_test.values, pred, "catboost_sample_weight_log1p")
    results_all.append(r)
    print("catboost_sample_weight_log1p: готово")

# CatBoost sample_weight linear
if EXPERIMENTS.get("catboost_sample_weight_linear", True):
    train_df, test_df, feats = prepare_train_test_catboost(df)
    X_train, X_test = train_df[feats], test_df[feats]
    y_train, y_test = train_df[TARGET_COL], test_df[TARGET_COL]
    sw = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    model = train_catboost(X_train, y_train, X_test, y_test, loss_function="MAE", sample_weight=sw)
    pred = np.maximum(model.predict(X_test), 0)
    r = run_metrics_summary(test_df, y_test.values, pred, "catboost_sample_weight_linear")
    results_all.append(r)
    print("catboost_sample_weight_linear: готово")

# CatBoost гиперпараметры (tuned)
if EXPERIMENTS.get("catboost_hyperparams", True):
    train_df, test_df, feats = prepare_train_test_catboost(df)
    X_train, X_test = train_df[feats], test_df[feats]
    y_train, y_test = train_df[TARGET_COL], test_df[TARGET_COL]
    cm = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    sw = np.sqrt(np.maximum(cm, 0.1))
    model = train_catboost(X_train, y_train, X_test, y_test, loss_function="MAE", sample_weight=sw,
                          iterations=1500, depth=8, learning_rate=0.05)
    pred = np.maximum(model.predict(X_test), 0)
    r = run_metrics_summary(test_df, y_test.values, pred, "catboost_hyperparams")
    results_all.append(r)
    print("catboost_hyperparams: готово")

# CatBoost hybrid (sqrt + спецмодель для мелких операций fact<50 по всем resist_id)
if EXPERIMENTS.get("catboost_hybrid", True):
    last_year = df["year"].max()
    train_orig = df[df["year"] < last_year].copy()
    test_orig = df[df["year"] == last_year].copy()
    train_df, test_df, feats = prepare_train_test_catboost(df)
    X_train, X_test = train_df[feats], test_df[feats]
    y_train, y_test = train_df[TARGET_COL], test_df[TARGET_COL]
    cm = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    sw = np.sqrt(np.maximum(cm, 0.1))
    model_base = train_catboost(X_train, y_train, X_test, y_test, loss_function="MAE", sample_weight=sw)
    pred_base = np.maximum(model_base.predict(X_test), 0)
    mask_small_train = (train_df[TARGET_COL].values < 50)
    if np.sum(mask_small_train) >= 5:
        X_small = train_df.loc[mask_small_train, feats]
        y_small = train_df.loc[mask_small_train, TARGET_COL]
        cm_small = train_df.loc[mask_small_train, "calculate_minute"].fillna(cm.mean())
        sw_small = np.sqrt(np.maximum(cm_small, 0.1))
        model_small = train_catboost(X_small, y_small, X_test, y_test, loss_function="MAE", sample_weight=sw_small)
        pred_small = np.maximum(model_small.predict(X_test), 0)
    else:
        pred_small = pred_base.copy()
    mask_use_small = (test_orig["lag_1"].values < 50)
    pred_final = pred_base.copy()
    pred_final[mask_use_small] = pred_small[mask_use_small]
    test_for_summary = test_df.copy()
    test_for_summary["resist_id"] = test_orig["resist_id"].values
    r = run_metrics_summary(test_for_summary, y_test.values, pred_final, "catboost_hybrid")
    results_all.append(r)
    print("catboost_hybrid: готово")





# Блок 5: Иерархическая модель (по operation_id, где достаточно истории)
if EXPERIMENTS.get("block5_hierarchical", False):
    last_year = df["year"].max()
    test_df = df[df["year"] == last_year].copy()
    train_df = df[df["year"] < last_year]
    ops_with_history = train_df.groupby("operation_id").size()
    ops_ok = ops_with_history[ops_with_history >= 12].index
    preds, y_vals, idx_list = [], [], []
    for op in ops_ok:
        tr = train_df[train_df["operation_id"] == op]
        te = test_df[test_df["operation_id"] == op]
        if te.empty:
            continue
        tr = tr.copy()
        te = te.copy()
        for c in CAT_COLS:
            le = LabelEncoder()
            all_v = pd.concat([tr[c], te[c]], ignore_index=True).astype(str)
            le.fit(all_v)
            tr[c], te[c] = le.transform(tr[c].astype(str)), le.transform(te[c].astype(str))
        m = Ridge(alpha=1.0, random_state=42)
        m.fit(tr[FEATURE_COLS], tr[TARGET_COL])
        p = np.maximum(m.predict(te[FEATURE_COLS]), 0)
        preds.extend(p)
        y_vals.extend(te[TARGET_COL].values)
        idx_list.extend(te.index)
    if preds:
        te_sub = test_df.loc[idx_list].copy()
        r = run_metrics_summary(te_sub, y_vals, preds, "block5_hierarchical")
        results_all.append(r)
        print("block5_hierarchical: готово")
    else:
        print("block5_hierarchical: пропущено (нет операций с достаточной историей)")




# Блок 6: Стратификация по объёму
if EXPERIMENTS.get("block6_stratify", False):
    train_df, test_df, feats = prepare_train_test(df, extra_features=True)
    X_train, X_test = train_df[feats], test_df[feats]
    y_train, y_test = train_df[TARGET_COL], test_df[TARGET_COL]
    model = train_ridge(X_train, y_train, alpha=1.0)
    pred = np.maximum(model.predict(X_test), 0)
    r = run_metrics_summary(test_df, y_test.values, pred, "block6_stratify")
    results_all.append(r)
    print("block6_stratify: готово")





# Блок 8: Ансамбль Ridge + XGBoost
if EXPERIMENTS.get("block8_ensemble", False):
    train_df, test_df, feats = prepare_train_test(df, extra_features=False)
    X_train, X_test = train_df[feats], test_df[feats]
    y_train, y_test = train_df[TARGET_COL], test_df[TARGET_COL]
    sw = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    m1 = train_ridge(X_train, y_train)
    m2 = train_xgb(X_train, y_train, X_test, y_test, objective="reg:absoluteerror", sample_weight=sw)
    pred = np.maximum((m1.predict(X_test) + m2.predict(X_test)) / 2, 0)
    r = run_metrics_summary(test_df, y_test.values, pred, "block8_ensemble")
    results_all.append(r)
    print("block8_ensemble: готово")




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





# Сравнение: fact_predict vs CatBoost по resist_id (показатель Качество)
# pred — от последнего выполненного эксперимента (обычно catboost_hybrid)

if not results_all:
    print("Сначала запустите эксперименты (секция 5).")
else:
    comp = test_df.copy()
    comp["pred_catboost"] = pred
    comp["fact_predict"] = comp["fact_predict"].fillna(0)

    def quality_by_resist_id(g):
        return calc_quality(g["fact_value"].values, g["pred_catboost"].values)

    def quality_fp_by_resist_id(g):
        return calc_quality(g["fact_value"].values, g["fact_predict"].values)

    q_cb = comp.groupby("resist_id").apply(quality_by_resist_id)
    q_fp = comp.groupby("resist_id").apply(quality_fp_by_resist_id)

    common = q_fp.index.intersection(q_cb.index)
    better_mask = q_cb.loc[common] > q_fp.loc[common]
    diff = pd.DataFrame({"Качество fact_predict": q_fp, "Качество CatBoost": q_cb})
    diff["Δ Качество"] = diff["Качество CatBoost"] - diff["Качество fact_predict"]
    diff = diff.sort_values("Δ Качество", ascending=False)

    better_diff = diff.loc[common][better_mask].sort_values("Δ Качество", ascending=False)
    better_resist_ids = better_diff.index.tolist()

    print("resist_id, по которым CatBoost лучше (качество выше):", better_resist_ids)
    print("\nΔ Качество (CatBoost - текущий) по каждому:")
    for rid in better_resist_ids:
        d = better_diff.loc[rid, "Δ Качество"]
        print(f"  {rid}: Δ = +{d:.2f}")
    print(f"\nВсего: {len(better_resist_ids)} из {len(common)} resist_id")
    display(diff)