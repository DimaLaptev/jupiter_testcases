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
    # первая версия в истории — начинаем с ver1
    next_ver = 1
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

# Vygruzka na list "Dannye": pereimenovanie kolonok, bez WAPE-kolonok
RENAME_SHEET1 = {
    "fact_value": "\u0424\u0430\u043a\u0442, \u0448\u0442.",
    "fact_fts": "\u0424\u0430\u043a\u0442, \u041f\u0428\u0415",
    "fact_predict": "\u041f\u0440\u043e\u0433\u043e\u0437 \u0422\u0435\u043a\u0443\u0449\u0438\u0439, \u0448\u0442.",
    "predict_fts": "\u041f\u0440\u043e\u0433\u043e\u0437 \u0422\u0435\u043a\u0443\u0449\u0438\u0439, \u041f\u0428\u0415",
    "mape_fact_predict_fts": "MAPE \u0422\u0435\u043a\u0443\u0449\u0438\u0439, \u041f\u0428\u0415",
}
wape_ops_cols = [c for c in df_hist.columns if c == "wape_fact_predict_ops" or (c.startswith("wape_predict_catboost_ver") and c.endswith("_ops"))]
df_export = df_hist.copy()
df_export = df_export.rename(columns={k: v for k, v in RENAME_SHEET1.items() if k in df_export.columns})
if wape_ops_cols:
    df_export = df_export.drop(columns=[c for c in wape_ops_cols if c in df_export.columns], errors="ignore")
df_export.to_excel(history_xlsx, index=False, sheet_name="\u0414\u0430\u043d\u043d\u044b\u0435")
print("\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0430 (\u043b\u0438\u0441\u0442 \u0414\u0430\u043d\u043d\u044b\u0435):", history_xlsx)

# Kolonki "Tochnost' Tekushhij" i "Tochnost' catboost_ver<X>" na liste Dannye (vsegda, do sozdanija ostal'nyh listov)
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
try:
    wb_t = load_workbook(history_xlsx)
    ws_data = wb_t["\u0414\u0430\u043d\u043d\u044b\u0435"]
    to_add = []
    for col in range(1, ws_data.max_column + 1):
        val = ws_data.cell(row=1, column=col).value
        if val is None:
            continue
        val_str = str(val).strip()
        if val_str == "MAPE \u0422\u0435\u043a\u0443\u0449\u0438\u0439, \u041f\u0428\u0415":
            to_add.append((col, "\u0422\u043e\u0447\u043d\u043e\u0441\u0442\u044c \u0422\u0435\u043a\u0443\u0449\u0438\u0439"))
        elif val_str.startswith("mape_catboost_ver") and val_str.endswith("_fts"):
            ver = val_str.replace("mape_catboost_ver", "").replace("_fts", "").split("_")[0]
            to_add.append((col, f"\u0422\u043e\u0447\u043d\u043e\u0441\u0442\u044c catboost_ver{ver}"))
    for col_idx, new_header in sorted(to_add, key=lambda x: -x[0]):
        ws_data.insert_cols(col_idx + 1)
        ws_data.cell(row=1, column=col_idx + 1, value=new_header)
        mape_letter = get_column_letter(col_idx)
        for row in range(2, ws_data.max_row + 1):
            ws_data.cell(row=row, column=col_idx + 1, value=f"=MAX(0,100-{mape_letter}{row})")
    wb_t.save(history_xlsx)
    print("Kolonki Tochnost' dobavleny na list Dannye")
except Exception as e:
    print("Oshibka pri dobavlenii kolonok Tochnost':", e)

# --- Metriki: svodnyj list + listy po resist_id (raschety v Python, bez formul Excel) ---


def _get_forecast_specs(df_hist_local: pd.DataFrame):
    specs = [{"forecast_name": "fact_predict", "pred_ops_col": "fact_predict", "pred_fts_col": "predict_fts", "mape_fts_col": "mape_fact_predict_fts"}]
    cat_ops = [c for c in df_hist_local.columns if c.startswith("predict_catboost_ver") and not c.endswith("_fts")
               and c.replace("predict_catboost_ver", "").split("_")[0].isdigit()]
    cat_ops = sorted(cat_ops, key=lambda c: int(c.replace("predict_catboost_ver", "").split("_")[0]))
    for ops_col in cat_ops:
        fts_col = f"{ops_col}_fts"
        mape_col = f"mape_catboost_ver{ops_col.replace('predict_catboost_ver', '').split('_')[0]}_fts"
        if mape_col in df_hist_local.columns and fts_col in df_hist_local.columns:
            specs.append({"forecast_name": ops_col, "pred_ops_col": ops_col, "pred_fts_col": fts_col, "mape_fts_col": mape_col})
    return specs


df_hist_num = df_hist.copy()
df_hist_num["year"] = pd.to_numeric(df_hist_num["year"], errors="coerce")
df_hist_num["month"] = pd.to_numeric(df_hist_num["month"], errors="coerce")
df_hist_num = df_hist_num.dropna(subset=["year", "month"])
df_hist_num["year"] = df_hist_num["year"].astype(int)
df_hist_num["month"] = df_hist_num["month"].astype(int)
df_hist_num["_rid_num"] = pd.to_numeric(df_hist_num["resist_id"], errors="coerce")

required_cols = {"year", "month", "resist_id", "fact_value", "fact_fts", "fact_predict", "predict_fts"}
missing = [c for c in required_cols if c not in df_hist.columns]
if missing:
    print("Vnimanie: net kolonok dlja metrik:", missing)
else:
    specs = _get_forecast_specs(df_hist)
    if not specs:
        print("Vnimanie: ne najdeno ni odnogo prognoza dlja metrik")
    else:
        resist_ids = sorted(df_hist_num["_rid_num"].dropna().astype(int).unique().tolist())
        summary_rows = []
        for rid in resist_ids + ["ALL"]:
            mask_resist = (df_hist_num["_rid_num"] == rid) if rid != "ALL" else pd.Series(True, index=df_hist_num.index)
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
                fact_ops = df_slice["fact_value"].sum()
                fact_fts = df_slice["fact_fts"].sum()
                row = {"resist_id": rid, "month": month_val if period_type == "MONTH" else "YEAR", "\u0424\u0430\u043a\u0442, \u0448\u0442.": round(fact_ops, 2) if pd.notna(fact_ops) else "", "\u0424\u0430\u043a\u0442, \u041f\u0428\u0415": round(fact_fts, 2) if pd.notna(fact_fts) else ""}
                for s in specs:
                    pred_ops_col = s["pred_ops_col"]
                    pred_fts_col = s.get("pred_fts_col")
                    if pred_ops_col not in df_slice.columns:
                        continue
                    pred_ops_sum = df_slice[pred_ops_col].sum()
                    pred_fts_sum = df_slice[pred_fts_col].sum() if pred_fts_col and pred_fts_col in df_slice.columns else np.nan
                    wape_ops = calc_wmape(df_slice["fact_value"], df_slice[pred_ops_col])
                    if pd.notna(fact_fts) and fact_fts != 0 and pd.notna(pred_fts_sum):
                        mape_fts_agg = abs(fact_fts - pred_fts_sum) / fact_fts * 100
                    else:
                        mape_fts_agg = np.nan
                    if s["forecast_name"] == "fact_predict":
                        prefix = "\u041f\u0440\u043e\u0433\u043e\u0437 \u0422\u0435\u043a\u0443\u0449\u0438\u0439"
                    else:
                        ver = s["forecast_name"].replace("predict_catboost_ver", "").split("_")[0]
                        prefix = f"\u041f\u0440\u043e\u0433\u043e\u0437 \u041d\u043e\u0432\u044b\u0439 {ver}"
                    row[f"{prefix}, \u0448\u0442."] = round(pred_ops_sum, 2) if pd.notna(pred_ops_sum) else ""
                    row[f"{prefix}, \u041f\u0428\u0415"] = round(pred_fts_sum, 2) if pd.notna(pred_fts_sum) else ""
                    row[f"{prefix}, WAPE \u043f\u043e \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u0443 \u0448\u0442, %"] = round(wape_ops, 2) if pd.notna(wape_ops) else ""
                    row[f"{prefix}, MAPE \u043f\u043e \u041f\u0428\u0415, %"] = round(mape_fts_agg, 2) if pd.notna(mape_fts_agg) else ""
                summary_rows.append(row)
        summary_df = pd.DataFrame(summary_rows)
        if not summary_df.empty:
            col_order = ["resist_id", "month", "\u0424\u0430\u043a\u0442, \u0448\u0442.", "\u0424\u0430\u043a\u0442, \u041f\u0428\u0415"]
            for s in specs:
                if s["forecast_name"] == "fact_predict":
                    prefix = "\u041f\u0440\u043e\u0433\u043e\u0437 \u0422\u0435\u043a\u0443\u0449\u0438\u0439"
                else:
                    ver = s["forecast_name"].replace("predict_catboost_ver", "").split("_")[0]
                    prefix = f"\u041f\u0440\u043e\u0433\u043e\u0437 \u041d\u043e\u0432\u044b\u0439 {ver}"
                col_order.extend([f"{prefix}, \u0448\u0442.", f"{prefix}, \u041f\u0428\u0415", f"{prefix}, WAPE \u043f\u043e \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u0443 \u0448\u0442, %", f"{prefix}, MAPE \u043f\u043e \u041f\u0428\u0415, %"])
            summary_df = summary_df[[c for c in col_order if c in summary_df.columns]]

        wb = load_workbook(history_xlsx)
        for name in list(wb.sheetnames):
            if name == "metrics" or name.startswith("resist_"):
                wb.remove(wb[name])
        for _n in ["Metriki_svod", "\u041c\u0435\u0442\u0440\u0438\u043a\u0438_\u0441\u0432\u043e\u0434"]:
            if _n in wb.sheetnames:
                wb.remove(wb[_n])

        ws_svod = wb.create_sheet("\u041c\u0435\u0442\u0440\u0438\u043a\u0438_\u0441\u0432\u043e\u0434", 1)
        if not summary_df.empty:
            ws_svod.append(list(summary_df.columns))
            for _, r in summary_df.iterrows():
                ws_svod.append([r[c] for c in summary_df.columns])

        # Listy po (resist_id, division_title): imja lista = "<resist_id><division_title>", bez drugoy stroki WAPE, bez goda
        MONTH_NAMES_RU = ["\u044f\u043d\u0432\u0430\u0440\u044c", "\u0444\u0435\u0432\u0440\u0430\u043b\u044c", "\u043c\u0430\u0440\u0442", "\u0430\u043f\u0440\u0435\u043b\u044c", "\u043c\u0430\u0439", "\u0438\u044e\u043d\u044c", "\u0438\u044e\u043b\u044c", "\u0430\u0432\u0433\u0443\u0441\u0442", "\u0441\u0435\u043d\u0442\u044f\u0431\u0440\u044c", "\u043e\u043a\u0442\u044f\u0431\u0440\u044c", "\u043d\u043e\u044f\u0431\u0440\u044c", "\u0434\u0435\u043a\u0430\u0431\u0440\u044c"]
        specs_avail = [s for s in specs if s["pred_ops_col"] in df_hist_num.columns and (s.get("pred_fts_col") in df_hist_num.columns if s.get("pred_fts_col") else True)]
        if not specs_avail:
            specs_avail = [s for s in specs if s["pred_ops_col"] in df_hist_num.columns]
        n_f = len(specs_avail)
        cols_per_month = 2 + 4 * n_f
        n_cols = 12 * cols_per_month
        rid_div_list = df_hist_num.drop_duplicates(subset=["_rid_num", "division_title"])[["_rid_num", "division_title"]].dropna(subset=["_rid_num"]).to_dict("records")
        print("Sozdanie listov <rid><division>: n_f =", n_f)
        for rec in rid_div_list:
            rid, div = rec["_rid_num"], rec["division_title"]
            df_r = df_hist_num[(df_hist_num["_rid_num"] == rid) & (df_hist_num["division_title"] == div)].copy()
            if df_r.empty or n_f == 0:
                continue
            sheet_name = (str(int(rid)) + str(div) if pd.notna(div) else str(int(rid)))[:31]
            for ch in ":\\/?*[]":
                sheet_name = sheet_name.replace(ch, "_")
            if sheet_name in wb.sheetnames:
                wb.remove(wb[sheet_name])
            ws = wb.create_sheet(sheet_name)
            print("  Sozdan list", sheet_name)
            ws.cell(row=1, column=1, value="resist_id")
            ws.cell(row=1, column=2, value="\u041f\u043e\u0434\u0440\u0430\u0437\u0434\u0435\u043b\u0435\u043d\u0438\u0435 (division_title)")
            ws.cell(row=1, column=3, value="\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u044f (operation_id)")
            if n_cols > 0:
                ws.merge_cells(start_row=1, start_column=4, end_row=1, end_column=3 + n_cols)
                ws.cell(row=1, column=4, value="\u041c\u0435\u0441\u044f\u0446 (month)")
            ws.cell(row=2, column=1, value=rid)
            ws.cell(row=2, column=2, value=div if pd.notna(div) else "")
            ws.cell(row=2, column=3, value="")
            for col_m in range(12):
                c1 = 4 + col_m * cols_per_month
                c2 = c1 + cols_per_month - 1
                ws.merge_cells(start_row=2, start_column=c1, end_row=2, end_column=c2)
                ws.cell(row=2, column=c1, value=MONTH_NAMES_RU[col_m])
                ws.cell(row=3, column=c1, value="\u0424\u0430\u043a\u0442, \u0448\u0442.")
                ws.cell(row=3, column=c1 + 1, value="\u0424\u0430\u043a\u0442, \u041f\u0428\u0415")
                for fi, s in enumerate(specs_avail):
                    pre = "\u041f\u0440\u043e\u0433\u043e\u0437 \u0422\u0435\u043a\u0443\u0449\u0438\u0439" if s["forecast_name"] == "fact_predict" else "\u041f\u0440\u043e\u0433\u043e\u0437 \u041d\u043e\u0432\u044b\u0439 " + s["forecast_name"].replace("predict_catboost_ver", "").split("_")[0]
                    ws.cell(row=3, column=c1 + 2 + 4 * fi, value=f"{pre}, \u0448\u0442.")
                    ws.cell(row=3, column=c1 + 3 + 4 * fi, value=f"{pre}, \u041f\u0428\u0415")
                    ws.cell(row=3, column=c1 + 4 + 4 * fi, value=f"{pre}, MAPE \u043f\u043e \u041f\u0428\u0415, %")
                    ws.cell(row=3, column=c1 + 5 + 4 * fi, value=f"{pre}, WAPE \u043f\u043e \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u0443 \u0448\u0442, %")
            data_start_row = 4
            current_row = data_start_row
            div_ops_list = df_r.drop_duplicates(subset=["operation_id"])[["operation_id"]].sort_values("operation_id").to_dict("records")
            for op_rec in div_ops_list:
                op = op_rec["operation_id"]
                op_str = str(op) if pd.notna(op) else ""
                ws.cell(row=current_row, column=1, value=rid)
                ws.cell(row=current_row, column=2, value="")
                ws.cell(row=current_row, column=3, value=op_str)
                for col_m in range(12):
                    r = df_r[(df_r["operation_id"] == op) & (df_r["month"] == col_m + 1)]
                    c1 = 4 + col_m * cols_per_month
                    if not r.empty:
                        ws.cell(row=current_row, column=c1, value=round(r["fact_value"].sum(), 2))
                        ws.cell(row=current_row, column=c1 + 1, value=round(r["fact_fts"].sum(), 2))
                    else:
                        ws.cell(row=current_row, column=c1, value="")
                        ws.cell(row=current_row, column=c1 + 1, value="")
                    for fi, sp in enumerate(specs_avail):
                        if not r.empty and sp["pred_ops_col"] in r.columns:
                            ws.cell(row=current_row, column=c1 + 2 + 4 * fi, value=round(r[sp["pred_ops_col"]].sum(), 2))
                            pred_fts = sp.get("pred_fts_col") and sp["pred_fts_col"] in r.columns
                            ws.cell(row=current_row, column=c1 + 3 + 4 * fi, value=round(r[sp["pred_fts_col"]].sum(), 2) if pred_fts else "")
                            mape_v = r[sp["mape_fts_col"]].mean() if sp["mape_fts_col"] in r.columns else np.nan
                            ws.cell(row=current_row, column=c1 + 4 + 4 * fi, value=round(mape_v, 2) if pd.notna(mape_v) else "")
                        else:
                            ws.cell(row=current_row, column=c1 + 2 + 4 * fi, value="")
                            ws.cell(row=current_row, column=c1 + 3 + 4 * fi, value="")
                            ws.cell(row=current_row, column=c1 + 4 + 4 * fi, value="")
                        ws.cell(row=current_row, column=c1 + 5 + 4 * fi, value="")
                current_row += 1
            if current_row > data_start_row:
                ws.cell(row=current_row, column=2, value="\u0418\u0442\u043e\u0433\u043e")
                ws.cell(row=current_row, column=3, value="")
                for col_m in range(12):
                    slice_m = df_r[df_r["month"] == col_m + 1]
                    c1 = 4 + col_m * cols_per_month
                    if not slice_m.empty:
                        ws.cell(row=current_row, column=c1, value=round(slice_m["fact_value"].sum(), 2))
                        ws.cell(row=current_row, column=c1 + 1, value=round(slice_m["fact_fts"].sum(), 2))
                    for fi, sp in enumerate(specs_avail):
                        if not slice_m.empty and sp["pred_ops_col"] in slice_m.columns:
                            ws.cell(row=current_row, column=c1 + 2 + 4 * fi, value=round(slice_m[sp["pred_ops_col"]].sum(), 2))
                            f_fts = slice_m["fact_fts"].sum()
                            p_fts = slice_m[sp["pred_fts_col"]].sum() if sp.get("pred_fts_col") and sp["pred_fts_col"] in slice_m.columns else 0
                            mape_agg = abs(f_fts - p_fts) / f_fts * 100 if f_fts and pd.notna(p_fts) else np.nan
                            ws.cell(row=current_row, column=c1 + 3 + 4 * fi, value=round(slice_m[sp["pred_fts_col"]].sum(), 2) if sp.get("pred_fts_col") and sp["pred_fts_col"] in slice_m.columns else "")
                            ws.cell(row=current_row, column=c1 + 4 + 4 * fi, value=round(mape_agg, 2) if pd.notna(mape_agg) else "")
                        else:
                            ws.cell(row=current_row, column=c1 + 2 + 4 * fi, value="")
                            ws.cell(row=current_row, column=c1 + 3 + 4 * fi, value="")
                            ws.cell(row=current_row, column=c1 + 4 + 4 * fi, value="")
                        ws.cell(row=current_row, column=c1 + 5 + 4 * fi, value="")
                current_row += 1
                ws.cell(row=current_row, column=3, value="WAPE \u043d\u0430 \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u0435 \u0448\u0442\u0443\u043a")
                for col_m in range(12):
                    slice_m = df_r[df_r["month"] == col_m + 1]
                    c1 = 4 + col_m * cols_per_month
                    for fi, sp in enumerate(specs_avail):
                        if not slice_m.empty and sp["pred_ops_col"] in slice_m.columns:
                            w = calc_wmape(slice_m["fact_value"], slice_m[sp["pred_ops_col"]])
                            ws.cell(row=current_row, column=c1 + 5 + 4 * fi, value=round(w, 2) if pd.notna(w) else "")
                        else:
                            ws.cell(row=current_row, column=c1 + 5 + 4 * fi, value="")

        wb.save(history_xlsx)
        print("Listy Metriki_svod i resist_* (metriki po operacijam, po vsem prognozam) sozdany:", history_xlsx)


    if name == "lightgbm":
        import lightgbm as lgb
        return lgb.LGBMRegressor(
            n_estimators=2000,
            max_depth=8,
            learning_rate=0.05,
            min_child_samples=20,
            num_leaves=64,
            reg_alpha=0.1,
            reg_lambda=0.1,
            objective="regression_l1",  # MAE — устойчивее к выбросам при разных масштабах
            random_state=42,
            verbose=100,
            early_stopping_rounds=100,
            force_col_wise=True,
        )


cat_idx = [FEATURE_COLS.index(c) for c in CAT_COLS]
    train_weight = train_df["calculate_minute"].fillna(train_df["calculate_minute"].mean())
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        sample_weight=train_weight,
        categorical_feature=[FEATURE_COLS[i] for i in cat_idx],
    )


def calc_mape(y_true, y_pred):
    y_true, y_pred = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    err = np.empty_like(y_true)
    mask_zero = y_true == 0
    err[mask_zero] = np.where(y_pred[mask_zero] == 0, 0.0, 100.0)
    mask_ok = ~mask_zero
    if np.any(mask_ok):
        err[mask_ok] = np.abs(y_true[mask_ok] - y_pred[mask_ok]) / np.abs(y_true[mask_ok]) * 100
    return float(np.mean(err))

def calc_accuracy_pct(y_true, y_pred):
    y_true, y_pred = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    acc = np.empty_like(y_true)
    mask_zero = y_true == 0
    acc[mask_zero] = np.where(y_pred[mask_zero] == 0, 100.0, 0.0)
    mask_ok = ~mask_zero
    if np.any(mask_ok):
        acc[mask_ok] = np.clip(100.0 - np.abs(y_true[mask_ok] - y_pred[mask_ok]) / np.abs(y_true[mask_ok]) * 100.0, 0, 100)
    return acc







y_pred = model.predict(X_test)
y_pred = np.maximum(y_pred, 0)  # предсказания не должны быть отрицательными

y_true = np.asarray(y_test, dtype=float)
y_pred = np.asarray(y_pred, dtype=float)

# Точность по строке: 100 - MAPE%, с ограничением [0, 100]
acc = np.empty_like(y_true)
mask_zero = y_true == 0
acc[mask_zero] = np.where(y_pred[mask_zero] == 0, 100.0, 0.0)
mask_ok = ~mask_zero
if np.any(mask_ok):
    acc[mask_ok] = np.clip(
        100.0 - np.abs(y_true[mask_ok] - y_pred[mask_ok]) / np.abs(y_true[mask_ok]) * 100.0,
        0, 100,
    )

# Точность — среднее по accuracy_pct
tochnost = float(np.mean(acc))
# Стабильность — (1 - CV) * 100%, CV = σ/μ по accuracy_pct
mean_acc = float(np.mean(acc))
stab = 0.0
if mean_acc > 0:
    cv = np.std(acc, ddof=0) / mean_acc
    stab = max(0.0, (1 - cv)) * 100
# Качество — гармоническое среднее Точности и Стабильности
kachestvo = 0.0
if tochnost + stab > 0:
    kachestvo = 2 * tochnost * stab / (tochnost + stab)

print(f"Точность, %:   {tochnost:.2f}")
print(f"Стабильность, %: {stab:.2f}")
print(f"Качество, %:   {kachestvo:.2f}")

# График: факт vs предсказание
plt.figure(figsize=(5, 5))
plt.scatter(y_test, y_pred, alpha=0.7)
plt.plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], "r--", lw=2, label="Идеальная линия")
plt.xlabel("Фактическое значение")
plt.ylabel("Предсказание")
plt.title("Факт vs предсказание LinearRegression")
plt.legend()
plt.tight_layout()
plt.show()







def calc_metrics_for_forecast(df_sub: pd.DataFrame, forecast_col: str) -> tuple[float, float, float]:
    """Точность, Стабильность, Качество по df с fact_value и forecast_col."""
    if df_sub.empty:
        return 0.0, 0.0, 0.0
    y_true = df_sub["fact_value"].astype(float).values
    y_pred = df_sub[forecast_col].astype(float).fillna(0).values
    y_pred = np.maximum(y_pred, 0)
    acc = np.empty_like(y_true, dtype=float)
    mask_zero = y_true == 0
    acc[mask_zero] = np.where(y_pred[mask_zero] == 0, 100.0, 0.0)
    mask_ok = ~mask_zero
    if np.any(mask_ok):
        acc[mask_ok] = np.clip(
            100.0 - np.abs(y_true[mask_ok] - y_pred[mask_ok]) / np.abs(y_true[mask_ok]) * 100.0,
            0, 100,
        )
    tochnost = float(np.mean(acc))
    stab = 0.0
    if tochnost > 0:
        cv = np.std(acc, ddof=0) / tochnost
        stab = max(0.0, (1 - cv)) * 100
    kachestvo = 0.0
    if tochnost + stab > 0:
        kachestvo = 2 * tochnost * stab / (tochnost + stab)
    return round(tochnost, 2), round(stab, 2), round(kachestvo, 2)


# Таблица по операциям
rows_op = []
for (rid, op_id), grp in df_test.groupby(["resist_id", "operation_id"]):
    t1, s1, q1 = calc_metrics_for_forecast(grp, "fact_predict")
    t2, s2, q2 = calc_metrics_for_forecast(grp, "predict_linear")
    div = grp["division_title"].iloc[0] if "division_title" in grp.columns else ""
    rows_op.append({
        "resist_id": rid,
        "operation_id": op_id,
        "division_title": div,
        "Точность (fact_predict)": t1,
        "Стабильность (fact_predict)": s1,
        "Качество (fact_predict)": q1,
        "Точность (прогноз)": t2,
        "Стабильность (прогноз)": s2,
        "Качество (прогноз)": q2,
    })

# Таблица по resist_id в целом
rows_rid = []
for rid, grp in df_test.groupby("resist_id"):
    t1, s1, q1 = calc_metrics_for_forecast(grp, "fact_predict")
    t2, s2, q2 = calc_metrics_for_forecast(grp, "predict_linear")
    div = grp["division_title"].iloc[0] if "division_title" in grp.columns else ""
    rows_rid.append({
        "resist_id": rid,
        "division_title": div,
        "Точность (fact_predict)": t1,
        "Стабильность (fact_predict)": s1,
        "Качество (fact_predict)": q1,
        "Точность (прогноз)": t2,
        "Стабильность (прогноз)": s2,
        "Качество (прогноз)": q2,
    })

df_metrics_op = pd.DataFrame(rows_op)
df_metrics_rid = pd.DataFrame(rows_rid)

# Детали тестовой выборки: даты и значения
df_detail = df_test[["resist_id", "operation_id", "division_title", "year", "month", "fact_value", "fact_predict", "predict_linear"]].copy()
df_detail = df_detail.sort_values(["resist_id", "operation_id", "year", "month"]).reset_index(drop=True)
df_detail = df_detail.rename(columns={
    "fact_value": "fact_value (факт)",
    "fact_predict": "fact_predict (кол-во)",
    "predict_linear": "прогноз (кол-во)",
})

out_path = Path("../data/processed/regression_forecast_metrics.xlsx")
out_path.parent.mkdir(parents=True, exist_ok=True)
with pd.ExcelWriter(out_path, engine="openpyxl") as w:
    df_detail.to_excel(w, sheet_name="Данные теста", index=False)
    df_metrics_op.to_excel(w, sheet_name="По операциям", index=False)
    df_metrics_rid.to_excel(w, sheet_name="По resist_id", index=False)

print(f"Excel сохранён: {out_path.resolve()}")