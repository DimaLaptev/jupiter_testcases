# Конфигурации прогноза (forecast scripts)

Скрипты прогноза создают Excel-дашборд с метриками. Каждая конфигурация отличается способом обучения XGBoost и влияет на итоговый прогноз.

---

## Сравнение конфигураций

| Скрипт | Конфигурация | objective | sample_weight | Гиперпараметры |
|--------|--------------|-----------|---------------|----------------|
| run_forecast_xgb_sqrt.py | block9_sample_weight_sqrt | MAE | sqrt(calculate_minute) | n=1000, depth=6, lr=0.1 |
| run_forecast_xgb_mae.py | block3_xgb_mae | MAE | calculate_minute (линейный) | n=1000, depth=6, lr=0.1 |
| run_forecast_xgb_hyperparams.py | block4_hyperparams | MAE | calculate_minute | n=1500, depth=8, lr=0.05 |
| run_forecast_xgb_log1p.py | block9_sample_weight_log1p | MAE | log1p(calculate_minute) | n=1000, depth=6, lr=0.1 |
| run_forecast_hybrid.py | block12_hybrid | MAE | sqrt (база) + sqrt (спецмодель) | Комбинация двух моделей |

---

## 1. block3_xgb_mae (run_forecast_xgb_mae.py)

**Отличия:**
- `sample_weight = calculate_minute` — линейный вес по нормативу времени (в минутах)
- Операции с большим нормативом (крупные) получают существенно больший вес

**Влияние на обучение:**
- Модель сильнее ориентирована на точность крупных операций
- Мелкие операции могут быть предсказаны менее точно

**Итоговый прогноз:**
- Лучше по WMAPE и в группах с крупными объёмами
- Хуже по среднему MAPE и в мелких операциях

---

## 2. block4_hyperparams (run_forecast_xgb_hyperparams.py)

**Отличия:**
- Те же веса, что в block3 (линейный calculate_minute)
- Другие гиперпараметры: `n_estimators=1500`, `max_depth=8`, `learning_rate=0.05`

**Влияние на обучение:**
- Более глубкие деревья и больше итераций → выше риск переобучения
- Меньший learning_rate → более осторожное обучение

**Итоговый прогноз:**
- Потенциально лучше на сложных паттернах
- При малом объёме данных возможен переобучение

---

## 3. block9_sample_weight_sqrt (run_forecast_xgb_sqrt.py)

**Отличия:**
- `sample_weight = sqrt(calculate_minute)` — сжатие разницы весов
- Баланс между мелкими и крупными операциями лучше, чем при линейных весах

**Влияние на обучение:**
- Крупные операции важнее, но не доминируют
- Модель лучше учитывает мелкие операции

**Итоговый прогноз:**
- Обычно лучший баланс Точность / Стабильность / Качество
- Рекомендуется как основная конфигурация

---

## 4. block9_sample_weight_log1p (run_forecast_xgb_log1p.py)

**Отличия:**
- `sample_weight = log1p(calculate_minute)` — ещё более мягкое сжатие весов
- Разница между операциями по весу меньше, чем при sqrt

**Влияние на обучение:**
- Все операции ближе по влиянию на функцию потерь
- Модель меньше смещена к крупным операциям

**Итоговый прогноз:**
- Может лучше работать на мелких операциях
- Крупные операции могут прогнозироваться хуже, чем при sqrt

---

## 5. block12_hybrid (run_forecast_hybrid.py)

**Отличия:**
- Две модели: базовая (block9 sqrt) и спецмодель для мелких FOCUS
- FOCUS: resist_id 31, 49, 159, 195
- Спецмодель обучается только на строках с `resist_id in FOCUS` и `fact_value < 50`
- На тесте: если `resist_id in FOCUS` и `lag_1 < 50` — прогноз от спецмодели, иначе от базовой

**Влияние на обучение:**
- Базовая модель обучается на всех данных
- Спецмодель — только на проблемных мелких операциях
- Спецмодель лучше учитывает особенности мелких FOCUS-операций

**Итоговый прогноз:**
- Крупные операции и resist_id 47, 59, 84, 88, 128, 161 — как у block9 sqrt
- Мелкие операции в 31, 49, 159, 195 — прогноз от спецмодели
- Цель — улучшить метрики по «мелкие FOCUS (31,49,159,195)»

---

## Запуск

```bash
python run_forecast_xgb_sqrt.py
python run_forecast_xgb_mae.py
python run_forecast_xgb_hyperparams.py
python run_forecast_xgb_log1p.py
python run_forecast_hybrid.py
```

С опцией `--output`:
```bash
python run_forecast_xgb_sqrt.py --output data/processed/my_dashboard.xlsx
```

Все скрипты создают Excel-дашборд с листами «Данные», «Оценка прогноза», «Тепловая карта».
