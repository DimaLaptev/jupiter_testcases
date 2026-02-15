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

    # Для не-версионной метрики current forecast обновляем колонку без конфликтных суффиксов.
    if "mape_fact_predict_fts" in df_hist.columns and "mape_fact_predict_fts" in df_new.columns:
        df_hist = df_hist.drop(columns=["mape_fact_predict_fts"])

    # left-merge к истории по ключам
    df_hist = df_hist.merge(df_new, on=key_cols, how="left")

# сохраняем

wmape_hist_cols = [c for c in df_hist.columns if c.startswith("wmape_catboost_ver")]
if wmape_hist_cols:
    df_hist = df_hist.drop(columns=wmape_hist_cols)

df_hist.to_excel(history_xlsx, index=False)
print("История сохранена:", history_xlsx)

# --- Формирование вкладки metrics с формулами Excel ---
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter


def _extract_ver(col_name: str) -> int:
    return int(col_name.replace("predict_catboost_ver", ""))


def _collect_forecasts(df_hist_local: pd.DataFrame):
    forecasts = [{
        "forecast_name": "fact_predict",
        "pred_ops_col": "fact_predict",
        "pred_fts_col": "predict_fts",
    }]

    cat_ops_cols = [
        c for c in df_hist_local.columns
        if c.startswith("predict_catboost_ver") and c.replace("predict_catboost_ver", "").isdigit()
    ]
    cat_ops_cols = sorted(cat_ops_cols, key=_extract_ver)

    for ops_col in cat_ops_cols:
        fts_col = f"{ops_col}_fts"
        if fts_col in df_hist_local.columns:
            forecasts.append({
                "forecast_name": ops_col,
                "pred_ops_col": ops_col,
                "pred_fts_col": fts_col,
            })

    return forecasts


def _build_metrics_rows(df_hist_local: pd.DataFrame, forecast_specs):
    rows = []

    years = sorted(pd.to_numeric(df_hist_local["year"], errors="coerce").dropna().astype(int).unique().tolist())

    for spec in forecast_specs:
        forecast_name = spec["forecast_name"]

        for year in years:
            df_year = df_hist_local[pd.to_numeric(df_hist_local["year"], errors="coerce") == year]
            if df_year.empty:
                continue

            months = sorted(pd.to_numeric(df_year["month"], errors="coerce").dropna().astype(int).unique().tolist())

            # a) по каждой операции за месяц
            for month in months:
                df_ym = df_year[pd.to_numeric(df_year["month"], errors="coerce") == month]
                ops = sorted(df_ym["operation_id"].dropna().astype(str).unique().tolist())
                for op in ops:
                    rows.append({
                        "aggregation_level": "operation",
                        "year": year,
                        "period_type": "MONTH",
                        "month": month,
                        "group_key": op,
                        "forecast_name": forecast_name,
                        "key_col_name": "operation_id",
                    })

            # a) по каждой операции за год
            ops_year = sorted(df_year["operation_id"].dropna().astype(str).unique().tolist())
            for op in ops_year:
                rows.append({
                    "aggregation_level": "operation",
                    "year": year,
                    "period_type": "YEAR_TOTAL",
                    "month": "",
                    "group_key": op,
                    "forecast_name": forecast_name,
                    "key_col_name": "operation_id",
                })

            # b) по каждому подразделению за месяц
            for month in months:
                df_ym = df_year[pd.to_numeric(df_year["month"], errors="coerce") == month]
                divisions = sorted(df_ym["division_title"].dropna().astype(str).unique().tolist())
                for div in divisions:
                    rows.append({
                        "aggregation_level": "division",
                        "year": year,
                        "period_type": "MONTH",
                        "month": month,
                        "group_key": div,
                        "forecast_name": forecast_name,
                        "key_col_name": "division_title",
                    })

            # b) по каждому подразделению за год
            divisions_year = sorted(df_year["division_title"].dropna().astype(str).unique().tolist())
            for div in divisions_year:
                rows.append({
                    "aggregation_level": "division",
                    "year": year,
                    "period_type": "YEAR_TOTAL",
                    "month": "",
                    "group_key": div,
                    "forecast_name": forecast_name,
                    "key_col_name": "division_title",
                })

            # c) по всем подразделениям за месяц
            for month in months:
                rows.append({
                    "aggregation_level": "total",
                    "year": year,
                    "period_type": "MONTH",
                    "month": month,
                    "group_key": "ALL",
                    "forecast_name": forecast_name,
                    "key_col_name": "",
                })

            # c) по всем подразделениям за год
            rows.append({
                "aggregation_level": "total",
                "year": year,
                "period_type": "YEAR_TOTAL",
                "month": "",
                "group_key": "ALL",
                "forecast_name": forecast_name,
                "key_col_name": "",
            })

    return pd.DataFrame(rows)


required_cols = {
    "year", "month", "division_title", "operation_id",
    "fact_value", "fact_fts", "fact_predict", "predict_fts",
}
missing_required = [c for c in required_cols if c not in df_hist.columns]
if missing_required:
    print("Внимание: пропущены обязательные колонки для metrics:", missing_required)
else:
    forecast_specs = _collect_forecasts(df_hist)
    if len(forecast_specs) == 0:
        print("Внимание: не найдено ни одного прогноза для metrics")
    else:
        metrics_rows = _build_metrics_rows(df_hist, forecast_specs)

        wb = load_workbook(history_xlsx)

        if "metrics" in wb.sheetnames:
            wb.remove(wb["metrics"])
        ws = wb.create_sheet("metrics")

        headers = [
            "aggregation_level", "year", "period_type", "month", "group_key",
            "forecast_name", "pred_ops_col", "pred_fts_col", "key_col_name",
            "n_rows", "wape_ops", "mape_fts",
        ]
        ws.append(headers)

        # Заполняем базовые поля строк
        for _, r in metrics_rows.iterrows():
            ws.append([
                r["aggregation_level"],
                int(r["year"]),
                r["period_type"],
                r["month"],
                r["group_key"],
                r["forecast_name"],
                "",  # formula
                "",  # formula
                r["key_col_name"],
                "",  # formula
                "",  # formula
                "",  # formula
            ])

        data_start_row = 2
        data_end_row = 1 + len(metrics_rows)

        # Таблица соответствия forecast_name -> pred_ops_col/pred_fts_col
        map_start_col = 14  # N
        ws.cell(row=1, column=map_start_col, value="forecast_name")
        ws.cell(row=1, column=map_start_col + 1, value="pred_ops_col")
        ws.cell(row=1, column=map_start_col + 2, value="pred_fts_col")

        for idx, spec in enumerate(forecast_specs, start=2):
            ws.cell(row=idx, column=map_start_col, value=spec["forecast_name"])
            ws.cell(row=idx, column=map_start_col + 1, value=spec["pred_ops_col"])
            ws.cell(row=idx, column=map_start_col + 2, value=spec["pred_fts_col"])

        # Формулы в строках метрик
        for excel_row in range(data_start_row, data_end_row + 1):
            # pred_ops_col / pred_fts_col по forecast_name
            ws.cell(
                row=excel_row,
                column=7,
                value=f'=IFERROR(INDEX($O:$O,MATCH($F{excel_row},$N:$N,0)),"")'
            )
            ws.cell(
                row=excel_row,
                column=8,
                value=f'=IFERROR(INDEX($P:$P,MATCH($F{excel_row},$N:$N,0)),"")'
            )

            # n_rows (Excel 2016 compatible)
            ws.cell(
                row=excel_row,
                column=10,
                value=(
                    f'=SUMPRODUCT('
                    f'--(INDEX(Sheet1!$2:$1048576,0,MATCH("year",Sheet1!$1:$1,0))=$B{excel_row}),' 
                    f'IF($C{excel_row}="YEAR_TOTAL",1,--(INDEX(Sheet1!$2:$1048576,0,MATCH("month",Sheet1!$1:$1,0))=$D{excel_row})),'
                    f'IF($I{excel_row}="",1,--(INDEX(Sheet1!$2:$1048576,0,MATCH($I{excel_row},Sheet1!$1:$1,0))=$E{excel_row}))'
                    f')'
                )
            )

            # WAPE по операциям (без таймингов), Excel 2016 compatible
            ws.cell(
                row=excel_row,
                column=11,
                value=(
                    f'=IFERROR('
                    f'SUMPRODUCT('
                    f'--(INDEX(Sheet1!$2:$1048576,0,MATCH("year",Sheet1!$1:$1,0))=$B{excel_row}),' 
                    f'IF($C{excel_row}="YEAR_TOTAL",1,--(INDEX(Sheet1!$2:$1048576,0,MATCH("month",Sheet1!$1:$1,0))=$D{excel_row})),'
                    f'IF($I{excel_row}="",1,--(INDEX(Sheet1!$2:$1048576,0,MATCH($I{excel_row},Sheet1!$1:$1,0))=$E{excel_row})),'
                    f'ABS(INDEX(Sheet1!$2:$1048576,0,MATCH("fact_value",Sheet1!$1:$1,0))-INDEX(Sheet1!$2:$1048576,0,MATCH($G{excel_row},Sheet1!$1:$1,0)))'
                    f')/'
                    f'SUMPRODUCT('
                    f'--(INDEX(Sheet1!$2:$1048576,0,MATCH("year",Sheet1!$1:$1,0))=$B{excel_row}),' 
                    f'IF($C{excel_row}="YEAR_TOTAL",1,--(INDEX(Sheet1!$2:$1048576,0,MATCH("month",Sheet1!$1:$1,0))=$D{excel_row})),'
                    f'IF($I{excel_row}="",1,--(INDEX(Sheet1!$2:$1048576,0,MATCH($I{excel_row},Sheet1!$1:$1,0))=$E{excel_row})),'
                    f'ABS(INDEX(Sheet1!$2:$1048576,0,MATCH("fact_value",Sheet1!$1:$1,0)))'
                    f')*100,'
                    f'NA()'
                    f')'
                )
            )

            # MAPE в FTS, Excel 2016 compatible
            ws.cell(
                row=excel_row,
                column=12,
                value=(
                    f'=IFERROR('
                    f'('
                    f'SUMPRODUCT('
                    f'--(INDEX(Sheet1!$2:$1048576,0,MATCH("year",Sheet1!$1:$1,0))=$B{excel_row}),' 
                    f'IF($C{excel_row}="YEAR_TOTAL",1,--(INDEX(Sheet1!$2:$1048576,0,MATCH("month",Sheet1!$1:$1,0))=$D{excel_row})),'
                    f'IF($I{excel_row}="",1,--(INDEX(Sheet1!$2:$1048576,0,MATCH($I{excel_row},Sheet1!$1:$1,0))=$E{excel_row})),'
                    f'IF(INDEX(Sheet1!$2:$1048576,0,MATCH("fact_fts",Sheet1!$1:$1,0))=0,'
                    f'IF(INDEX(Sheet1!$2:$1048576,0,MATCH($H{excel_row},Sheet1!$1:$1,0))=0,0,100),'
                    f'ABS(INDEX(Sheet1!$2:$1048576,0,MATCH("fact_fts",Sheet1!$1:$1,0))-INDEX(Sheet1!$2:$1048576,0,MATCH($H{excel_row},Sheet1!$1:$1,0)))/'
                    f'ABS(INDEX(Sheet1!$2:$1048576,0,MATCH("fact_fts",Sheet1!$1:$1,0)))*100'
                    f')'
                    f')/'
                    f'SUMPRODUCT('
                    f'--(INDEX(Sheet1!$2:$1048576,0,MATCH("year",Sheet1!$1:$1,0))=$B{excel_row}),' 
                    f'IF($C{excel_row}="YEAR_TOTAL",1,--(INDEX(Sheet1!$2:$1048576,0,MATCH("month",Sheet1!$1:$1,0))=$D{excel_row})),'
                    f'IF($I{excel_row}="",1,--(INDEX(Sheet1!$2:$1048576,0,MATCH($I{excel_row},Sheet1!$1:$1,0))=$E{excel_row}))'
                    f')'
                    f'),' 
                    f'NA()'
                    f')'
                )
            )

        # Форматирование
        ws.freeze_panes = "A2"
        col_widths = {
            1: 16, 2: 8, 3: 12, 4: 8, 5: 28, 6: 24,
            7: 22, 8: 24, 9: 16, 10: 10, 11: 12, 12: 12,
            14: 24, 15: 24, 16: 24,
        }
        for col_idx, width in col_widths.items():
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # Скрываем служебные колонки pred_ops_col/pred_fts_col/key_col_name и map-table
        ws.column_dimensions[get_column_letter(7)].hidden = True
        ws.column_dimensions[get_column_letter(8)].hidden = True
        ws.column_dimensions[get_column_letter(9)].hidden = True
        ws.column_dimensions[get_column_letter(14)].hidden = True
        ws.column_dimensions[get_column_letter(15)].hidden = True
        ws.column_dimensions[get_column_letter(16)].hidden = True

        wb.save(history_xlsx)
        print("Вкладка metrics обновлена:", history_xlsx)