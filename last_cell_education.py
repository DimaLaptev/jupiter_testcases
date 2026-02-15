from catboost import CatBoostRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

# признаки и цель
cat_cols = ["operation_id", "division_title", "resist_id"]
num_cols = [
    "month",
    "year",
    "workDayMonth_2",
    "calculate_minute",
    "coefficient_fulltime_staff",
    "lag_1",
    "lag_12",
    "roll_mean_3",
    "roll_mean_6",
    "trend",
]

feature_cols = cat_cols + num_cols

target_col = "fact_value"

# простое разделение train/test по времени (последний год — тест)

df_model39 = df_model39.sort_values(["year", "month"]).copy()

# CatBoost ожидает категориальные признаки в виде строк

df_model39[cat_cols] = df_model39[cat_cols].astype(str)

last_year = df_model39["year"].max()
train_df = df_model39[df_model39["year"] < last_year]
test_df = df_model39[df_model39["year"] == last_year]

X_train = train_df[feature_cols]
y_train = train_df[target_col]
X_test = test_df[feature_cols]
y_test = test_df[target_col]

cat_feature_indices = [feature_cols.index(c) for c in cat_cols]

model = CatBoostRegressor(
    iterations=1000,
    depth=6,
    learning_rate=0.1,
    loss_function="RMSE",
    random_seed=42,
    verbose=100,
    early_stopping_rounds=50,
)

# Используем тест (2025) как eval_set для early stopping
# Веса: чем больше норматив времени, тем важнее строка
train_weight = train_df["calculate_minute"].astype(float)
train_weight = train_weight.fillna(train_weight.mean())

model.fit(
    X_train,
    y_train,
    cat_features=cat_feature_indices,
    eval_set=(X_test, y_test),
    sample_weight=train_weight,
)

pred = model.predict(X_test)

# Пост-обработка: отсечка отрицательных прогнозов
pred = np.maximum(pred, 0)

mae = mean_absolute_error(y_test, pred)
rmse = np.sqrt(mean_squared_error(y_test, pred))

# MAPE для CatBoost (pred vs fact)
mape_model = (y_test - pred).abs() / y_test.abs()
# правила для fact_value == 0
mask_zero = y_test == 0
mape_model[mask_zero & (pred == 0)] = 0.0
mape_model[mask_zero & (pred != 0)] = 1.0
mape_model = mape_model.replace([float("inf"), float("-inf")], pd.NA)
mape_model = mape_model.dropna().mean() * 100

# MAPE для текущего прогноза fact_predict на той же тестовой выборке
fact_pred_test = test_df["fact_predict"].astype(float)
mape_fact_pred = (y_test - fact_pred_test).abs() / y_test.abs()
mape_fact_pred[mask_zero & (fact_pred_test == 0)] = 0.0
mape_fact_pred[mask_zero & (fact_pred_test != 0)] = 1.0
mape_fact_pred = mape_fact_pred.replace([float("inf"), float("-inf")], pd.NA)
mape_fact_pred = mape_fact_pred.dropna().mean() * 100

# WMAPE считаем как sum(abs(actual - predicted)) / sum(abs(actual)) * 100.
def calc_wmape(actual: pd.Series, predicted) -> float:
    actual_num = pd.to_numeric(actual, errors="coerce")
    pred_num = pd.to_numeric(pd.Series(predicted, index=actual.index), errors="coerce")
    valid = actual_num.notna() & pred_num.notna()

    if valid.sum() == 0:
        return float("nan")

    numerator = (actual_num[valid] - pred_num[valid]).abs().sum()
    denominator = actual_num[valid].abs().sum()

    if denominator == 0:
        return float("nan")

    return float(numerator / denominator * 100)

wmape_model = calc_wmape(y_test, pred)
wmape_fact_pred = calc_wmape(y_test, fact_pred_test)

print(f"Test MAE: {mae:.2f}")
print(f"Test RMSE: {rmse:.2f}")
print(f"Test MAPE (CatBoost): {mape_model:.2f}%")
print(f"Test MAPE (fact_predict): {mape_fact_pred:.2f}%")
print(f"Test WMAPE (CatBoost): {wmape_model:.2f}%")
print(f"Test WMAPE (fact_predict): {wmape_fact_pred:.2f}%")

# Сохраняем прогноз в Excel (тестовый год)

df_pred = test_df.copy()
df_pred["predict_catboost_ver1"] = pred
# WMAPE — агрегатная метрика по тесту, сохраняем как служебное поле версии.
df_pred["wmape_catboost_ver1"] = wmape_model

coef = df_pred["coefficient_fulltime_staff"]
df_pred["predict_catboost_ver1_fts"] = df_pred["predict_catboost_ver1"] * coef

# MAPE для CatBoost по строкам теста (в штуках)
mape_cat = (df_pred["fact_value"] - df_pred["predict_catboost_ver1"]).abs() / df_pred["fact_value"].abs()
mask_zero_pred = df_pred["fact_value"] == 0
mape_cat[mask_zero_pred & (df_pred["predict_catboost_ver1"] == 0)] = 0.0
mape_cat[mask_zero_pred & (df_pred["predict_catboost_ver1"] != 0)] = 1.0
mape_cat = mape_cat.replace([float("inf"), float("-inf")], pd.NA)

df_pred["mape_catboost_ver1"] = mape_cat * 100

# MAPE для CatBoost по строкам теста в FTE:
# |fact_fts - predict_catboost_ver1_fts| / |fact_fts| * 100
# Для fact_fts == 0: если predict == 0 -> 0%, иначе -> 100%.
mape_cat_fts = (df_pred["fact_fts"] - df_pred["predict_catboost_ver1_fts"]).abs() / df_pred["fact_fts"].abs()
mask_zero_fts = df_pred["fact_fts"] == 0
mape_cat_fts[mask_zero_fts & (df_pred["predict_catboost_ver1_fts"] == 0)] = 0.0
mape_cat_fts[mask_zero_fts & (df_pred["predict_catboost_ver1_fts"] != 0)] = 1.0
mape_cat_fts = mape_cat_fts.replace([float("inf"), float("-inf")], pd.NA)

df_pred["mape_catboost_ver1_fts"] = mape_cat_fts * 100

# large_error_share для CatBoost (на уровне строки)
df_pred["large_error_share_catboost_ver1"] = df_pred["mape_catboost_ver1"] > 30

# square_error для CatBoost (в FTE)
df_pred["square_error_catboost_ver1"] = (
    (df_pred["fact_value"] * coef) - (df_pred["predict_catboost_ver1"] * coef)
).abs() ** 2

out_xlsx = "../data/processed/predictions_catboost_v2.xlsx"
df_pred.to_excel(out_xlsx, index=False)

print("Файл сохранен:", out_xlsx)

# История прогонов: добавляем новые колонки с версией

history_xlsx = "../data/processed/predictions_history.xlsx"

# Базовые ключи для склейки

key_cols = ["resist_id", "division_title", "operation_id", "date", "id", "month", "year"]

# Текущие метрики для этой версии

# гарантируем, что столбцы CatBoost-метрик существуют и заполнены
if "mape_catboost_ver1" not in df_pred.columns or df_pred["mape_catboost_ver1"].isna().all():
    mape_cat = (df_pred["fact_value"] - df_pred["predict_catboost_ver1"]).abs() / df_pred["fact_value"].abs()
    mask_zero_pred = df_pred["fact_value"] == 0
    mape_cat[mask_zero_pred & (df_pred["predict_catboost_ver1"] == 0)] = 0.0
    mape_cat[mask_zero_pred & (df_pred["predict_catboost_ver1"] != 0)] = 1.0
    mape_cat = mape_cat.replace([float("inf"), float("-inf")], pd.NA)
    df_pred["mape_catboost_ver1"] = mape_cat * 100

if "predict_catboost_ver1_fts" not in df_pred.columns or df_pred["predict_catboost_ver1_fts"].isna().all():
    coef = df_pred["coefficient_fulltime_staff"]
    df_pred["predict_catboost_ver1_fts"] = df_pred["predict_catboost_ver1"] * coef

if "mape_catboost_ver1_fts" not in df_pred.columns or df_pred["mape_catboost_ver1_fts"].isna().all():
    mape_cat_fts = (df_pred["fact_fts"] - df_pred["predict_catboost_ver1_fts"]).abs() / df_pred["fact_fts"].abs()
    mask_zero_fts = df_pred["fact_fts"] == 0
    mape_cat_fts[mask_zero_fts & (df_pred["predict_catboost_ver1_fts"] == 0)] = 0.0
    mape_cat_fts[mask_zero_fts & (df_pred["predict_catboost_ver1_fts"] != 0)] = 1.0
    mape_cat_fts = mape_cat_fts.replace([float("inf"), float("-inf")], pd.NA)
    df_pred["mape_catboost_ver1_fts"] = mape_cat_fts * 100

if "mape_fact_predict_fts" not in df_pred.columns or df_pred["mape_fact_predict_fts"].isna().all():
    mape_fact_pred_fts = (df_pred["fact_fts"] - df_pred["predict_fts"]).abs() / df_pred["fact_fts"].abs()
    mask_zero_fts = df_pred["fact_fts"] == 0
    mape_fact_pred_fts[mask_zero_fts & (df_pred["predict_fts"] == 0)] = 0.0
    mape_fact_pred_fts[mask_zero_fts & (df_pred["predict_fts"] != 0)] = 1.0
    mape_fact_pred_fts = mape_fact_pred_fts.replace([float("inf"), float("-inf")], pd.NA)
    df_pred["mape_fact_predict_fts"] = mape_fact_pred_fts * 100

if "large_error_share_catboost_ver1" not in df_pred.columns or df_pred["large_error_share_catboost_ver1"].isna().all():
    df_pred["large_error_share_catboost_ver1"] = (df_pred["mape_catboost_ver1"] > 30).fillna(False)

if "square_error_catboost_ver1" not in df_pred.columns or df_pred["square_error_catboost_ver1"].isna().all():
    coef = df_pred["coefficient_fulltime_staff"]
    df_pred["square_error_catboost_ver1"] = (
        (df_pred["fact_value"] * coef) - (df_pred["predict_catboost_ver1"] * coef)
    ).abs() ** 2
    df_pred["square_error_catboost_ver1"] = df_pred["square_error_catboost_ver1"].fillna(0)

base_pred = df_pred.copy()
base_pred = base_pred[key_cols + [
    "fact_value",
    "fact_fts",
    "fact_predict",
    "predict_fts",
    "mape_fact_predict_fts",
    "predict_catboost_ver1",
    "predict_catboost_ver1_fts",
    "mape_catboost_ver1",
    "mape_catboost_ver1_fts",
    "large_error_share_catboost_ver1",
    "square_error_catboost_ver1",
]].copy()

# Переименуем метрики под версионный формат

base_pred = base_pred.rename(columns={
    "predict_catboost_ver1": "predict_catboost_verX",
    "predict_catboost_ver1_fts": "predict_catboost_verX_fts",
    "mape_catboost_ver1": "mape_catboost_verX",
    "mape_catboost_ver1_fts": "mape_catboost_verX_fts",
    "large_error_share_catboost_ver1": "large_error_share_catboost_verX",
    "square_error_catboost_ver1": "square_error_catboost_verX",
})

df_hist = None
try:
    df_hist = pd.read_excel(history_xlsx)
    if df_hist.empty or not set(key_cols).issubset(df_hist.columns):
        df_hist = None
except (FileNotFoundError, ValueError):
    df_hist = None

if df_hist is None:
    # первая версия в истории — начинаем с ver3
    next_ver = 3
    print("History not found or empty. Start version:", next_ver)
    df_hist = base_pred.rename(columns={
        "predict_catboost_verX": f"predict_catboost_ver{next_ver}",
        "predict_catboost_verX_fts": f"predict_catboost_ver{next_ver}_fts",
        "mape_catboost_verX": f"mape_catboost_ver{next_ver}",
        "mape_catboost_verX_fts": f"mape_catboost_ver{next_ver}_fts",
        "large_error_share_catboost_verX": f"large_error_share_catboost_ver{next_ver}",
        "square_error_catboost_verX": f"square_error_catboost_ver{next_ver}",
    })
else:
    # определить следующий номер версии по существующим колонкам
    ver_cols = [c for c in df_hist.columns if c.startswith("predict_catboost_ver")]
    if ver_cols:
        max_ver = max(int(c.replace("predict_catboost_ver", "")) for c in ver_cols)
    else:
        max_ver = 2
    next_ver = max_ver + 1
    print("Next version:", next_ver)

    df_new = base_pred.rename(columns={
        "predict_catboost_verX": f"predict_catboost_ver{next_ver}",
        "predict_catboost_verX_fts": f"predict_catboost_ver{next_ver}_fts",
        "mape_catboost_verX": f"mape_catboost_ver{next_ver}",
        "mape_catboost_verX_fts": f"mape_catboost_ver{next_ver}_fts",
        "large_error_share_catboost_verX": f"large_error_share_catboost_ver{next_ver}",
        "square_error_catboost_verX": f"square_error_catboost_ver{next_ver}",
    })

    # приведение типов ключей перед merge
    for c in ["resist_id", "id", "month", "year"]:
        if c in df_hist.columns:
            df_hist[c] = pd.to_numeric(df_hist[c], errors="coerce").astype("Int64")
        if c in df_new.columns:
            df_new[c] = pd.to_numeric(df_new[c], errors="coerce").astype("Int64")

    # operation_id как строка (в JSON часто строковый ключ)
    if "operation_id" in df_hist.columns:
        df_hist["operation_id"] = df_hist["operation_id"].astype(str)
    if "operation_id" in df_new.columns:
        df_new["operation_id"] = df_new["operation_id"].astype(str)

    if "date" in df_hist.columns:
        df_hist["date"] = pd.to_datetime(df_hist["date"], errors="coerce").dt.date
    if "date" in df_new.columns:
        df_new["date"] = pd.to_datetime(df_new["date"], errors="coerce").dt.date

    # Для не-версионных колонок обновляем значения без конфликтных суффиксов.
    non_versioned_cols = [
        "fact_value",
        "fact_fts",
        "fact_predict",
        "predict_fts",
        "mape_fact_predict_fts",
    ]
    cols_to_drop_before_merge = [
        c for c in non_versioned_cols
        if c in df_hist.columns and c in df_new.columns
    ]
    if cols_to_drop_before_merge:
        df_hist = df_hist.drop(columns=cols_to_drop_before_merge)

    # left-merge к истории по ключам
    df_hist = df_hist.merge(df_new, on=key_cols, how="left")

# сохраняем

wmape_hist_cols = [c for c in df_hist.columns if c.startswith("wmape_catboost_ver")]
if wmape_hist_cols:
    df_hist = df_hist.drop(columns=wmape_hist_cols)

# Kolonki WAPE po operacijam dlja kazhdogo prognoza na Sheet1 (povtoreno po strokam)
def _forecast_ver(col):
    if col == "fact_predict":
        return 0
    s = col.replace("predict_catboost_ver", "").split("_")[0]
    return int(s) if s.isdigit() else 0
forecast_ops_cols = ["fact_predict"] + [
    c for c in df_hist.columns
    if c.startswith("predict_catboost_ver") and not c.endswith("_fts")
    and c.replace("predict_catboost_ver", "").split("_")[0].isdigit()
]
forecast_ops_cols = sorted(set(forecast_ops_cols), key=_forecast_ver)
for pred_col in forecast_ops_cols:
    if pred_col not in df_hist.columns:
        continue
    wape_val = calc_wmape(df_hist["fact_value"], df_hist[pred_col])
    wape_col = "wape_fact_predict_ops" if pred_col == "fact_predict" else f"wape_{pred_col}_ops"
    df_hist[wape_col] = wape_val

df_hist.to_excel(history_xlsx, index=False)
print("История сохранена:", history_xlsx)

# --- Metriki: svodnyj list + listy po resist_id (raschety v Python, bez formul Excel) ---
from openpyxl import load_workbook


def _get_forecast_specs(df_hist_local: pd.DataFrame):
    specs = [{"forecast_name": "fact_predict", "pred_ops_col": "fact_predict", "mape_fts_col": "mape_fact_predict_fts"}]
    cat_ops = [c for c in df_hist_local.columns if c.startswith("predict_catboost_ver") and not c.endswith("_fts")
               and c.replace("predict_catboost_ver", "").split("_")[0].isdigit()]
    cat_ops = sorted(cat_ops, key=lambda c: int(c.replace("predict_catboost_ver", "").split("_")[0]))
    for ops_col in cat_ops:
        mape_col = f"mape_catboost_ver{ops_col.replace('predict_catboost_ver', '').split('_')[0]}_fts"
        if mape_col in df_hist_local.columns:
            specs.append({"forecast_name": ops_col, "pred_ops_col": ops_col, "mape_fts_col": mape_col})
    return specs


df_hist_num = df_hist.copy()
df_hist_num["year"] = pd.to_numeric(df_hist_num["year"], errors="coerce")
df_hist_num["month"] = pd.to_numeric(df_hist_num["month"], errors="coerce")
df_hist_num = df_hist_num.dropna(subset=["year", "month"])
df_hist_num["year"] = df_hist_num["year"].astype(int)
df_hist_num["month"] = df_hist_num["month"].astype(int)

required_cols = {"year", "month", "resist_id", "fact_value", "fact_fts", "fact_predict", "predict_fts"}
missing = [c for c in required_cols if c not in df_hist.columns]
if missing:
    print("Vnimanie: net kolonok dlja metrik:", missing)
else:
    specs = _get_forecast_specs(df_hist)
    if not specs:
        print("Vnimanie: ne najdeno ni odnogo prognoza dlja metrik")
    else:
        summary_rows = []
        resist_ids = sorted(pd.to_numeric(df_hist_num["resist_id"], errors="coerce").dropna().astype(int).unique().tolist())
        years = sorted(df_hist_num["year"].unique().tolist())
        for rid in resist_ids + ["ALL"]:
            mask_resist = df_hist_num["resist_id"] == rid if rid != "ALL" else pd.Series(True, index=df_hist_num.index)
            df_r = df_hist_num.loc[mask_resist]
            if df_r.empty:
                continue
            months_in_data = sorted(df_r["month"].unique().tolist())
            for period_type, month_val in [("MONTH", m) for m in months_in_data] + [("YEAR", "YEAR")]:
                if period_type == "YEAR":
                    df_slice = df_r
                else:
                    df_slice = df_r[df_r["month"] == month_val]
                if df_slice.empty:
                    continue
                for s in specs:
                    pred_col = s["pred_ops_col"]
                    mape_col = s["mape_fts_col"]
                    if pred_col not in df_slice.columns or mape_col not in df_slice.columns:
                        continue
                    wape = calc_wmape(df_slice["fact_value"], df_slice[pred_col])
                    mape_fts = df_slice[mape_col].mean()
                    summary_rows.append({
                        "resist_id": rid,
                        "month": month_val if period_type == "MONTH" else "YEAR",
                        "forecast_name": s["forecast_name"],
                        "wape_ops": round(wape, 2) if pd.notna(wape) else "",
                        "mape_fts": round(mape_fts, 2) if pd.notna(mape_fts) else "",
                    })
        summary_df = pd.DataFrame(summary_rows)

        wb = load_workbook(history_xlsx)
        for name in list(wb.sheetnames):
            if name == "metrics" or (name.startswith("resist_") and name[7:].isdigit()):
                wb.remove(wb[name])
        if "Metriki_svod" in wb.sheetnames:
            wb.remove(wb["Metriki_svod"])

        ws_svod = wb.create_sheet("Metriki_svod", 1)
        ws_svod.append(["resist_id", "month", "forecast_name", "wape_ops", "mape_fts"])
        for _, r in summary_df.iterrows():
            ws_svod.append([r["resist_id"], r["month"], r["forecast_name"], r["wape_ops"], r["mape_fts"]])

        for rid in resist_ids:
            df_r = df_hist_num[df_hist_num["resist_id"] == rid]
            if df_r.empty:
                continue
            rows_r = []
            months_in_data = sorted(df_r["month"].unique().tolist())
            for period_type, month_val in [("MONTH", m) for m in months_in_data] + [("YEAR", "YEAR")]:
                if period_type == "YEAR":
                    df_slice = df_r
                else:
                    df_slice = df_r[df_r["month"] == month_val]
                if df_slice.empty:
                    continue
                for s in specs:
                    pred_col = s["pred_ops_col"]
                    mape_col = s["mape_fts_col"]
                    if pred_col not in df_slice.columns or mape_col not in df_slice.columns:
                        continue
                    wape = calc_wmape(df_slice["fact_value"], df_slice[pred_col])
                    mape_fts = df_slice[mape_col].mean()
                    rows_r.append({"month": month_val if period_type == "MONTH" else "YEAR", "forecast_name": s["forecast_name"], "wape_ops": round(wape, 2) if pd.notna(wape) else "", "mape_fts": round(mape_fts, 2) if pd.notna(mape_fts) else ""})
            if rows_r:
                ws_res = wb.create_sheet(f"resist_{rid}")
                ws_res.append(["month", "forecast_name", "wape_ops", "mape_fts"])
                for r in rows_r:
                    ws_res.append([r["month"], r["forecast_name"], r["wape_ops"], r["mape_fts"]])

        wb.save(history_xlsx)
        print("Listy Metriki_svod i resist_* sozdany (metriki poschitany v Python):", history_xlsx)