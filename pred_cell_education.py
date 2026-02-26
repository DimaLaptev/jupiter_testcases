# Data Cleaning: фильтруем только утвержденные записи до парсинга JSON

# Нормализация булевых полей

def to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "t", "1"])


def to_bool_value(value):
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return None
    return str(value).strip().lower() in ["true", "t", "1"]


bool_cols = ["send", "validate_one", "validate_two", "cancel_approve", "forecast"]
for col in bool_cols:
    if col in df_all.columns:
        df_all[col] = to_bool(df_all[col])

# Валидация этапов

df_all["validate_count"] = pd.to_numeric(df_all["validate_count"], errors="coerce").fillna(0).astype(int)

mask_sent = df_all["send"]
mask_not_cancelled = ~df_all["cancel_approve"]
mask_approved = (
    (df_all["validate_count"] == 0)
    | ((df_all["validate_count"] == 1) & df_all["validate_one"])
    | ((df_all["validate_count"] >= 2) & df_all["validate_one"] & df_all["validate_two"])
)

# Исключение авто-прогнозов (Data Leakage / Loop prevention)

PREDICT_COMMENT = "first_predict_value_record"
if "comment" in df_all.columns:
    df_all["comment"] = df_all["comment"].fillna("")
    mask_predict_record = df_all["comment"] == PREDICT_COMMENT
else:
    mask_predict_record = pd.Series(False, index=df_all.index)

# Итоговый фильтр (важно: forecast не фильтруем!)
# Условия send=True и validation намеренно исключены.
# В БД есть полезные записи и при send=False, а validate_* в последних месяцах часто не заполнены.
# Дополнительно исключаем набор моделей (resist_id), которые не должны попадать в обучение.

EXCLUDED_RESIST_IDS = [
    25, 26, 27, 29, 54, 57, 61, 63, 66, 68, 80, 81, 82, 83, 100, 101, 102, 103,
    104, 105, 106, 109, 112, 113, 115, 116, 119, 120, 121, 122, 123, 125, 126,
    129, 131, 132, 134, 135, 136, 137, 138, 140, 141, 143, 144, 146, 147, 148,
    149, 150, 151, 152, 153, 154, 156, 157, 158, 162, 165, 169, 170, 171, 172,
    173, 174, 175, 176, 177, 178, 179, 181, 196,
]
mask_resist_allowed = ~df_all["resist_id"].isin(EXCLUDED_RESIST_IDS)

df_ok = df_all[mask_not_cancelled & ~mask_predict_record & mask_resist_allowed].copy()

# Разбор operation_parameter + calculate_parameter

def parse_division_title(div_json: str):
    if pd.isna(div_json):
        return None
    try:
        obj = json.loads(div_json)
    except Exception:
        return None
    return obj.get("name")


def parse_calculate_param(calc_json: str):
    if pd.isna(calc_json):
        return {}
    try:
        return json.loads(calc_json)
    except Exception:
        return {}


def get_calc_value(calc_obj: dict, key: str):
    val = calc_obj.get(key)
    if isinstance(val, dict):
        return val.get("value")
    return val


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

    for op_id, payload in op_data.items():
        if not isinstance(payload, dict):
            continue
        # исключаем неактивные операции
        active_flag = to_bool_value(payload.get("operation_active", payload.get("active")))
        if active_flag is False:
            continue

        period = row.get("period")
        if pd.isna(period):
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
            "predict_catboost_ver1": None,
            "mape_catboost_ver1": pd.NA,
            "workDayMonth_2": workday,
            "calculate_minute": payload.get("calculate_minute"),
        })

df_model39 = pd.DataFrame(records)

# Типы и базовые поля

df_model39["fact_value"] = pd.to_numeric(df_model39["fact_value"], errors="coerce")
df_model39["fact_predict"] = pd.to_numeric(df_model39["fact_predict"], errors="coerce")
df_model39["workDayMonth_2"] = pd.to_numeric(df_model39["workDayMonth_2"], errors="coerce")
df_model39["calculate_minute"] = pd.to_numeric(df_model39["calculate_minute"], errors="coerce")

# коэффициент полной занятости

df_model39["coefficient_fulltime_staff"] = (
    df_model39["calculate_minute"] / 60 / 148.3
)

# значения в FTE (fact vs predict)

df_model39["fact_fts"] = df_model39["fact_value"] * df_model39["coefficient_fulltime_staff"]
df_model39["predict_fts"] = df_model39["fact_predict"] * df_model39["coefficient_fulltime_staff"]

# MAPE по текущему прогнозу (fact_predict vs fact_value)

df_model39["mape_fact_predict"] = (
    (df_model39["fact_value"] - df_model39["fact_predict"]).abs()
    / df_model39["fact_value"].abs()
) * 100

# если появились бесконечности — заменяем на NA

df_model39["mape_fact_predict"] = df_model39["mape_fact_predict"].replace(
    [float("inf"), float("-inf")], pd.NA
)

# Правила для fact_value == 0:
# - если fact_predict == 0 => MAPE = 0 (0%)
# - если fact_predict != 0 => MAPE = 1 (100%)
mask_zero = df_model39["fact_value"] == 0
mask_zero_pred = mask_zero & (df_model39["fact_predict"] == 0)
mask_zero_nonzero_pred = mask_zero & (df_model39["fact_predict"] != 0)

df_model39.loc[mask_zero_pred, "mape_fact_predict"] = 0.0
df_model39.loc[mask_zero_nonzero_pred, "mape_fact_predict"] = 100.0

# MAPE по текущему прогнозу в FTE (fact_fts vs predict_fts)

df_model39["mape_fact_predict_fts"] = (
    (df_model39["fact_fts"] - df_model39["predict_fts"]).abs()
    / df_model39["fact_fts"].abs()
) * 100

df_model39["mape_fact_predict_fts"] = df_model39["mape_fact_predict_fts"].replace(
    [float("inf"), float("-inf")], pd.NA
)

mask_zero_fts = df_model39["fact_fts"] == 0
mask_zero_pred_fts = mask_zero_fts & (df_model39["predict_fts"] == 0)
mask_zero_nonzero_pred_fts = mask_zero_fts & (df_model39["predict_fts"] != 0)

df_model39.loc[mask_zero_pred_fts, "mape_fact_predict_fts"] = 0.0
df_model39.loc[mask_zero_nonzero_pred_fts, "mape_fact_predict_fts"] = 100.0

# large_error_share для текущего прогноза

df_model39["large_error_share"] = df_model39["mape_fact_predict"] > 30

# квадрат ошибки (в FTE)

df_model39["square_error_fact_predict"] = (
    (df_model39["fact_value"] * df_model39["coefficient_fulltime_staff"])
    - (df_model39["fact_predict"] * df_model39["coefficient_fulltime_staff"])
).abs() ** 2

# Feature Engineering (Time Series)

# дата из года и месяца

df_model39["date"] = pd.to_datetime(
    dict(year=df_model39["year"], month=df_model39["month"], day=1),
    errors="coerce",
).dt.date

# сортировка обязательна для лагов

df_model39 = df_model39.sort_values(["operation_id", "year", "month"]).reset_index(drop=True)

# лаги и скользящие средние (по operation_id)

group = df_model39.groupby("operation_id")

df_model39["lag_1"] = group["fact_value"].shift(1)

df_model39["lag_12"] = group["fact_value"].shift(12)

df_model39["roll_mean_3"] = group["fact_value"].transform(
    lambda s: s.shift(1).rolling(3, min_periods=3).mean()
)

df_model39["roll_mean_6"] = group["fact_value"].transform(
    lambda s: s.shift(1).rolling(6, min_periods=6).mean()
)

# тренд: отношение прошлого месяца к среднему за 3 мес

df_model39["trend"] = df_model39["lag_1"] / df_model39["roll_mean_3"]

# убираем бесконечности, которые могли появиться в тренде

df_model39["trend"] = df_model39["trend"].replace([np.inf, -np.inf], 0)

# Финальная очистка

# 1) удаляем строки без факта

df_model39 = df_model39.dropna(subset=["fact_value"])

# 2) Фильтрация начальных нулевых месяцев 2025 года по каждой операции:
# Если у операции в январе 2025 fact_value=0 и fact_predict=0, находим первый месяц 2025,
# где fact_value>0 или fact_predict>0, и удаляем предшествующие нулевые строки 2025 года.
# Данные других лет не затрагиваются.

FILTER_YEAR = 2025

def filter_leading_zeros_2025(group: pd.DataFrame) -> pd.DataFrame:
    group = group.sort_values(["year", "month"]).reset_index(drop=True)
    yr_mask = group["year"] == FILTER_YEAR
    yr_rows = group.loc[yr_mask]
    if yr_rows.empty:
        return group
    jan_rows = yr_rows[yr_rows["month"] == 1]
    if jan_rows.empty:
        return group
    jan_row = jan_rows.iloc[0]
    if jan_row["fact_value"] != 0 or jan_row["fact_predict"] != 0:
        return group
    first_active_pos = None
    for idx in yr_rows.index:
        r = group.loc[idx]
        if r["fact_value"] > 0 or r["fact_predict"] > 0:
            first_active_pos = idx
            break
    drop_mask = pd.Series(False, index=group.index)
    if first_active_pos is None:
        drop_mask.loc[yr_mask] = True
    else:
        drop_mask.loc[yr_rows.index[yr_rows.index < first_active_pos]] = True
    return group.loc[~drop_mask]

df_model39 = (
    df_model39
    .groupby("operation_id", group_keys=False)
    .apply(filter_leading_zeros_2025)
    .reset_index(drop=True)
)

# 3) оставшиеся пропуски заполняем нулями (только числовые поля)

num_cols = df_model39.select_dtypes(include=["number"]).columns

df_model39[num_cols] = df_model39[num_cols].fillna(0)

# приведение типов после fillna (для future-совместимости pandas)

df_model39 = df_model39.infer_objects(copy=False)

# порядок колонок

ordered_cols = [
    "resist_id",
    "division_title",
    "date",
    "operation_id",
    "fact_value",
    "fact_predict",
    "fact_fts",
    "predict_fts",
    "mape_fact_predict",
    "mape_fact_predict_fts",
    "large_error_share",
    "square_error_fact_predict",
    "predict_catboost_ver1",
    "mape_catboost_ver1",
    "id",
    "month",
    "year",
    "calculate_minute",
    "coefficient_fulltime_staff",
    "lag_1",
    "lag_12",
    "roll_mean_3",
    "roll_mean_6",
    "trend",
]

extra_cols = [c for c in df_model39.columns if c not in ordered_cols]

if extra_cols:
    df_model39 = df_model39[ordered_cols + extra_cols]
else:
    df_model39 = df_model39[ordered_cols]

print("Итоговых строк:", len(df_model39))
df_model39.head()