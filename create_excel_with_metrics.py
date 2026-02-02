import pandas as pd
import numpy as np
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

# --- 1. Генерация тестовых данных (Заглушка) ---
# Создаем список из 10 операций для примера
months = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 
          'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
num_ops = 10
ids = np.arange(1001, 1001 + num_ops)
names = [f"Операция {i}" for i in range(1, num_ops + 1)]

# Случайные данные факта и прогноза
data_fact = np.random.randint(50, 500, size=(num_ops, 12))
data_forecast = data_fact + np.random.randint(-50, 50, size=(num_ops, 12)) # Прогноз с ошибкой
chronometry = np.random.randint(5, 120, size=num_ops) # Хронометраж в минутах

# Создаем DataFrames
df_fact = pd.DataFrame(data_fact, columns=months)
df_fact.insert(0, 'Название операции', names)
df_fact.insert(0, 'ID', ids)

df_forecast = pd.DataFrame(data_forecast, columns=months)
df_forecast.insert(0, 'Название операции', names)
df_forecast.insert(0, 'ID', ids)

# --- 2. Создание Excel файла ---
wb = Workbook()

# === ЛИСТ 1: Фактические значения ===
ws1 = wb.active
ws1.title = "Fact_Values"

# Записываем заголовки
headers_vals = ['ID', 'Название операции'] + months + ['Итого за год']
ws1.append(headers_vals)

# Записываем данные построчно
for r in dataframe_to_rows(df_fact, index=False, header=False):
    ws1.append(r)

# Добавляем формулы сумм построчно (столбец O - это 15-й столбец)
max_row = len(df_fact) + 1
for row in range(2, max_row + 1):
    # Формула суммы с C (3) по N (14)
    ws1[f'O{row}'] = f"=SUM(C{row}:N{row})"

# Итого внизу столбца "Итого за год"
ws1[f'A{max_row + 1}'] = "ОБЩИЙ ИТОГ:"
ws1[f'O{max_row + 1}'] = f"=SUM(O2:O{max_row})"
ws1[f'O{max_row + 1}'].font = Font(bold=True)


# === ЛИСТ 2: Прогнозные значения ===
ws2 = wb.create_sheet("Forecast_Values")

# Заголовки
ws2.append(headers_vals)

# Данные
for r in dataframe_to_rows(df_forecast, index=False, header=False):
    ws2.append(r)

# Формулы сумм построчно
for row in range(2, max_row + 1):
    ws2[f'O{row}'] = f"=SUM(C{row}:N{row})"

# Итого внизу
ws2[f'A{max_row + 1}'] = "ОБЩИЙ ИТОГ:"
ws2[f'O{max_row + 1}'] = f"=SUM(O2:O{max_row})"
ws2[f'O{max_row + 1}'].font = Font(bold=True)


# === ЛИСТ 3: Метрики и расчеты ===
ws3 = wb.create_sheet("Metrics_Calculation")

# Заголовки метрик
headers_metrics = [
    'ID', 
    'Название операции', 
    'Хронометраж (мин)', 
    'Коэфф. ПШЕ', 
    'Разница (Факт-Прогноз) шт', 
    'Разница (Факт-Прогноз) ПШЕ', 
    'MAPE % (шт)', 
    'MAPE % (ПШЕ)', 
    'Квадрат ошибки (ПШЕ)' # Нужно для RMSE
]
ws3.append(headers_metrics)

# Заполняем формулами
for i in range(num_ops):
    row = i + 2
    
    # Ссылки на ID и Имя (берем с листа Fact)
    ws3[f'A{row}'] = f"='Fact_Values'!A{row}"
    ws3[f'B{row}'] = f"='Fact_Values'!B{row}"
    
    # Хронометраж (вставляем значение)
    ws3[f'C{row}'] = chronometry[i]
    
    # Коэффициент ПШЕ: мин / 60 / 148.3
    ws3[f'D{row}'] = f"=C{row}/60/148.3"
    
    # Разница ШТ: (Итого факт - Итого прогноз)
    # Ссылаемся на столбец O (15-й) в листах факта и прогноза
    ws3[f'E{row}'] = f"='Fact_Values'!O{row} - 'Forecast_Values'!O{row}"
    
    # Разница ПШЕ: Разница ШТ * Коэфф
    ws3[f'F{row}'] = f"=E{row}*D{row}"
    
    # MAPE % (шт): ABS(Разница) / Факт. IFERROR для защиты от деления на 0
    ws3[f'G{row}'] = f"=IFERROR(ABS(E{row})/'Fact_Values'!O{row}, 0)"
    ws3[f'G{row}'].number_format = '0.00%'
    
    # MAPE % (ПШЕ): ABS(Разница ПШЕ) / (Факт ШТ * Коэфф)
    # Математически равно MAPE шт, но разнесем для наглядности формул
    ws3[f'H{row}'] = f"=IFERROR(ABS(F{row})/('Fact_Values'!O{row}*D{row}), 0)"
    ws3[f'H{row}'].number_format = '0.00%'
    
    # Квадрат ошибки ПШЕ (для RMSE): (Разница ПШЕ)^2
    ws3[f'I{row}'] = f"=F{row}^2"

# === ИТОГИ ВНИЗУ ЛИСТА 3 ===
footer_row = num_ops + 2

ws3[f'A{footer_row}'] = "СРЕДНИЕ ПОКАЗАТЕЛИ:"
ws3[f'A{footer_row}'].font = Font(bold=True)

# Средний MAPE (шт)
ws3[f'G{footer_row}'] = f"=AVERAGE(G2:G{footer_row-1})"
ws3[f'G{footer_row}'].number_format = '0.00%'
ws3[f'G{footer_row}'].font = Font(bold=True)

# Средний MAPE (ПШЕ)
ws3[f'H{footer_row}'] = f"=AVERAGE(H2:H{footer_row-1})"
ws3[f'H{footer_row}'].number_format = '0.00%'
ws3[f'H{footer_row}'].font = Font(bold=True)

# RMSE (ПШЕ)
# Формула: КОРЕНЬ( СРЗНАЧ( Квадратов ошибок ) )
ws3[f'I{footer_row}'] = f"=SQRT(AVERAGE(I2:I{footer_row-1}))"
ws3[f'I{footer_row}'].font = Font(bold=True, color="FF0000") # Выделим красным
ws3[f'I{footer_row - 1}'] = "(RMSE считаем по этому столбцу)" # Подсказка


# --- 3. Оформление (Красота) ---
thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), 
                     top=Side(style='thin'), bottom=Side(style='thin'))

for sheet in [ws1, ws2, ws3]:
    # Автоширина столбцов
    for column_cells in sheet.columns:
        length = max(len(str(cell.value)) if cell.value else 0 for cell in column_cells)
        sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = length + 5
    
    # Границы и заголовки
    for row in sheet.iter_rows():
        for cell in row:
            cell.border = thin_border
            if cell.row == 1:
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")

# Сохранение файла
file_name = "Analysis_Model_Forecast_2025.xlsx"
wb.save(file_name)
print(f"Файл '{file_name}' успешно создан! Запустите этот код на своем компьютере.")
