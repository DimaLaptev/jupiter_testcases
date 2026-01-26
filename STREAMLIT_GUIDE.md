### Гайд: как читать данные и метрики в Streamlit‑приложении (Streamlit app)

Этот документ объясняет, что именно показывает текущий Streamlit‑дашборд (Streamlit dashboard), какие метрики (metrics) он считает, как их интерпретировать и какие типовые ловушки (pitfalls) учитывать.

---

## 1) Что измеряем и на каких данных (data)

В приложении есть два режима (mode):

### A) Operations (кол-во операций) (operations count)

- **fact (fact)**: `operation_fact_value` — фактическое количество операций (operations) по каждой операции (operation) в месяце (month).
- **ai_pred (AI prediction)**: `operation_forecast_value` (= `fact_predict` из БД (database)) — прогноз количества операций (operations) ИИ‑моделью (AI model).
- Объект сравнения: прогноз количества операций (operations count) по каждой операции (operation).

### B) Workload (нагрузка, %) (workload)

- **fact (fact)**: `workload_fact` (= `resist_10.value` из `calculate_parameter` (JSON)) — фактическая нагрузка (workload) по модели численности (staffing model) / подразделению (division) за месяц (month).
- **ai_pred (AI prediction)**: `workload_ai` (= `resist_10_predict.value`) — нагрузка (workload), полученная из прогноза ИИ (AI forecast).
- Объект сравнения: прогноз нагрузки (workload) в процентах (%).

Важно:

- В режиме Operations (operations) ошибок много строк (rows): по операциям (operations).
- В режиме Workload (workload) строк меньше: по `resist_id × месяц` (month).

---

## 2) Фильтры (filters) в sidebar (sidebar)

### Период (month range)

Ограничивает анализ диапазоном месяцев (months). Все таблицы (tables) и графики (charts) ниже пересчитываются только по данным внутри диапазона.

### Подразделение (division)

Если выбрано конкретное подразделение (division), всё считается только по нему.

---

## 3) Что такое baseline (baseline) и зачем он нужен

### 3.1. Зачем baseline (baseline model)

Baseline (baseline model) — простое правило без ML (ML), чтобы понять, насколько ИИ (AI) лучше эвристик (heuristics).
Если ИИ (AI) хуже baseline (baseline), модель (model) пока не даёт ценности (value).

### 3.2. Hybrid baseline (hybrid baseline) в текущей версии

Baseline (baseline) строится как “лесенка” (fallback ladder) по каждой группе (group):

- **Operations (operations)**: группа (group) = (`resist_id`, `operation_id`)
- **Workload (workload)**: группа (group) = (`resist_id`)

Для каждой точки времени \(t\) baseline (baseline) выбирается по приоритету:

1. **year_ago (year-over-year)**: факт (fact) год назад  
   \[
   baseline(t) = fact(t - 12\ месяцев)
   \]
2. **rolling_median (rolling median)**: медиана (median) последних 6 месяцев (без текущего), если есть ≥3 наблюдений  
   \[
   baseline(t) = median(fact(t-1),...,fact(t-6))
   \]
3. **last_value (last observation)**: факт (fact) прошлого месяца  
   \[
   baseline(t) = fact(t-1)
   \]
4. **global_median (global median)**: медиана (median) по всей истории (history) в группе (group)

Также baseline (baseline) “обрезается” (clipping): `baseline >= 0`.

### 3.3. baseline_rule (baseline_rule)

Приложение (app) показывает, какое правило baseline (baseline) сработало:

- `year_ago`
- `rolling_median`
- `last_value`
- `global_median`

Это индикатор качества fallback (fallback): если почти всегда `global_median`, значит истории мало.

---

## 4) Глобальные метрики (metrics) по источникам (sources)

Таблица “Глобальные метрики (metrics) по источникам (sources)” считает качество на текущих фильтрах (filters).

Там есть 3 строки:

### ai_all (ai_all)

Метрики (metrics) для ИИ (AI) на всех строках (rows), где есть факт (fact) и прогноз (prediction).

### ai_common (ai_common)

Метрики (metrics) для ИИ (AI) на подмножестве (subset), где baseline (baseline) рассчитан.

### baseline_common (baseline_common)

Метрики (metrics) baseline (baseline) на том же подмножестве (subset), что и ai_common.

#### Почему так сделано

Чтобы сравнение было честным (fair): baseline (baseline) может отсутствовать на ранних периодах (periods).

### catboost_v1 (catboost_v1)
Метрики (metrics) для модели (model) CatBoost (CatBoostRegressor) на строках (rows), где есть её прогноз (prediction).
Используется для сравнения с AI (ai_pred) и baseline (baseline) в режиме Workload (workload).

### Coverage (coverage)

**Покрытие baseline (coverage)** = доля строк (rows), где baseline (baseline) определён.

Если coverage (coverage) низкий, выводы нужно делать осторожно.

---

## 5) Метрики (metrics): полный разбор и почему выбран именно этот набор

Ниже объясняю, почему набор метрик (metrics) даёт полную картину качества (quality) прогноза (forecast), как именно они считаются в нашем проекте (project), какие параметры (parameters) используются, и привожу понятные примеры “на пальцах”.

### 5.1 Почему именно этот набор метрик (metrics) даёт полную картину качества (quality)

Каждая метрика (metric) отвечает на отдельный риск (risk). Вместе они закрывают **все ключевые вопросы**:

- **MAE (MAE)** отвечает на вопрос: “какая **типичная** ошибка (error) в единицах измерения (units)?”  
  Это основной показатель “обычного” качества (quality).

- **RMSE (RMSE)** отвечает на вопрос: “есть ли **редкие крупные промахи (large errors)**?”  
  RMSE (RMSE) усиливает вклад больших ошибок (large errors), поэтому показывает риск “сильных провалов”.

- **MAPE_% (MAPE)** отвечает на вопрос: “насколько ошибка (error) велика **относительно факта**?”  
  Это нужно, чтобы сравнивать подразделения (divisions) разного масштаба (scale).

- **large_error_share (large_error_share)** отвечает на вопрос: “как часто модель (model) **критично** ошибается?”  
  Это прямая метрика (metric) управленческого риска (risk).

Итого:  
**MAE (MAE)** = типичная точность (accuracy),  
**RMSE (RMSE)** = риск больших ошибок (large errors),  
**MAPE_% (MAPE)** = относительная точность (relative accuracy) между разными масштабами (scales),  
**large_error_share (large_error_share)** = доля критических промахов (critical misses).  

Без любой из этих метрик (metrics) картина качества (quality) будет неполной.

---

### 5.2 Как именно считаются метрики (metrics) в проекте (project)

В коде используется функция `compute_metrics()` (см. `streamlit_app.py`):

1. Берём пары `y_true` и `y_pred` и удаляем NaN (NaN).  
2. Считаем ошибки (errors):  
   - `error = y_pred - y_true`  
   - `abs_error = |error|`

3. Формулы (formulas):
   - **MAE (MAE)** = `mean(abs_error)`
   - **RMSE (RMSE)** = `sqrt(mean(error^2))`
   - **MAPE_% (MAPE)** = `mean(|error / y_true|) * 100%`, **только где `y_true != 0`**
   - **large_error_share (large_error_share)** = доля строк (rows), где  
     `abs_error > large_abs` **или** `abs_error > |y_true| * large_pct`

#### 5.2.1 Режим Workload (workload)

- В приложении факты (facts) и прогнозы (predictions) в процентах (percent) — это колонки:
  - `fact_pct`, `ai_pct`, `baseline_pct`, `catboost_pct`
- Эти значения получаются как `значение * 100`, т.е. **единицы измерения (units) = процентные пункты (percentage points)**.
- Порог (threshold) “большой ошибки (large error)” берётся из `METRICS_KW`:
  - `large_abs = 10` (10 п.п.)
  - `large_pct = 0.1` (10% от факта)

Итого:  
**в Workload (workload)** ошибка считается “большой (large)”, если  
`|y_pred - y_true| > 10` **или** `|y_pred - y_true| > 0.1 * |y_true|`.

#### 5.2.2 Режим Operations (operations)

- В режиме Operations (operations) используются **абсолютные значения операций (operations)**:
  - `fact`, `ai_pred`, `baseline_pred`
- Формулы (formulas) те же, но единицы измерения (units) = “операции (operations)”.

Важно: сейчас в приложении активен режим Workload (workload).  
Если режим Operations (operations) будет снова включён, пороги (thresholds) для `large_error_share` нужно явно выставить в `METRICS_KW`.  

---

### 5.3 Примеры “на пальцах” (by-hand examples)

#### Пример 1 (Workload, workload)
Факт (fact) = 80, прогноз (pred) = 90.  
- Ошибка (error) = 10 п.п.  
- MAE (MAE) = 10  
- RMSE (RMSE) = 10  
- MAPE_% (MAPE) = `10/80 * 100% = 12.5%`  
- large_error_share (large_error_share):  
  `abs_error = 10`  
  Проверка порога (threshold):  
  - `10 > 10` → **нет**  
  - `10 > 0.1 * 80 = 8` → **да**  
  Значит это **большая ошибка (large error)**.

#### Пример 2 (Workload, workload): зачем нужен RMSE (RMSE)
Ошибки (errors) по 3 месяцам (months): 2, 2, 20.  
- MAE (MAE) = `(2+2+20)/3 = 8`  
- RMSE (RMSE) = `sqrt((4+4+400)/3) ≈ 11.7`  
Вывод: RMSE (RMSE) заметно выше MAE (MAE) → есть редкий большой промах (large error).

#### Пример 3 (Operations, operations)
Факт (fact) = 1000 операций (operations), прогноз (pred) = 900.  
- Ошибка (error) = 100  
- MAE (MAE) = 100  
- MAPE_% (MAPE) = `100/1000 * 100% = 10%`  
- large_error_share (large_error_share) зависит от порогов (thresholds), которые задаются в `METRICS_KW` при включении режима Operations (operations).

---

**Итог:**  
Этот набор метрик (metrics) отвечает на все ключевые вопросы:  
“насколько обычно точны (MAE)”, “есть ли серьёзные провалы (RMSE)”,  
“насколько ошибка велика относительно масштаба (MAPE_%)”,  
“как часто ошибки критичны (large_error_share)”.

---

## 6) Метрики по подразделениям (divisions)

Таблица “Метрики по подразделениям (divisions)” показывает MAE и MAPE по каждому подразделению (division) отдельно, сравнивая:

- `ai`
- `baseline`

Считается на common set (intersection), чтобы сравнение было корректным.

---

## 7) Динамика MAE по месяцам (months)

График (chart) показывает MAE по времени:

- линия (line) `ai`
- линия (line) `baseline`

Пики означают проблемные периоды (problem periods) или изменения процесса (process change).

---

## 8) Heatmap (heatmap) ошибок по разрезам (slices)

Heatmap (heatmap) строится как матрица:

- строки (rows): `division_title` или `resist_id`
- колонки (columns): `month` (месяц)
- значение (value): выбранная метрика (metric) для выбранного источника (source) — ai/baseline/catboost_v1

Использование:

- быстро найти “красные зоны” (red zones): проблемные подразделения (divisions) и месяцы (months).

---

## 9) Практический workflow (workflow)

1. Выбери режим (mode):
   - улучшать прогноз нагрузки → Workload (workload).
2. Выставь период (period), например последние 12–24 месяцев.
3. Сравни `ai_common` vs `baseline_common`.
4. Проверь coverage (coverage).
5. Посмотри “по подразделениям (divisions)” и heatmap (heatmap), найди где ИИ (AI) хуже baseline (baseline).
6. Зафиксируй “проблемные” подразделения/месяцы и дальше улучшай модель (model).

---

## 10) Частые ловушки (pitfalls)

- Сравнивать `ai_all` с baseline нельзя: это разные выборки (different subsets). Используй `ai_common` vs `baseline_common`.
- MAPE_% нестабилен при малых фактах (small y_true).
- Workload (workload) и Operations (operations) — разные уровни агрегации (aggregation); выводы могут отличаться.


