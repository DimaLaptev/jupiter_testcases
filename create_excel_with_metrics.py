import pandas as pd
import numpy as np
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

# --- 1. Генерация тестовых данных ---
months = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 
          'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
num_ops = 15 # Количество операций для примера
ids = np.arange(1001, 1001 + num_ops)
names = [f"Операция {i}" for i in range(1, num_ops + 1)]

# Случайные данные
data_fact = np.random.randint(20, 500, size=(num_ops, 12))
data_forecast = data_fact + np.random.randint(-50, 50, size=(num_ops, 12)) 
chronometry = np.random.randint(5, 120, size=num_ops)

# DataFrames
df_fact = pd.DataFrame(data_fact, columns=months)
df_fact.insert(0, 'Название операции', names)
df_fact.insert(0, 'ID', ids)

df_forecast = pd.DataFrame(data_forecast, columns=months)
df_forecast.insert(0, 'Название операции', names)
df_forecast.insert(0, 'ID', ids)

# --- 2. Создание Excel файла ---
wb = Workbook()

# Стили
bold_font = Font(bold=True)
center_align = Alignment(horizontal='center')
thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), 
                     top=Side(style='thin'), bottom=Side(style='thin'))
fill_header = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
fill_mape = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid") # Желтоватый
fill_fte = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")  # Голубоватый

# === ЛИСТ 1: ФАКТ ===
ws1 = wb.active
ws1.title = "Fact_Values"
ws1.append(['ID', 'Название операции'] + months + ['ИТОГО год'])

for r in dataframe_to_rows(df_fact, index=False, header=False):
    ws1.append(r)

# Формулы сумм
max_row = len(df_fact) + 1
for row in range(2, max_row + 1):
    ws1[f'O{row}'] = f"=SUM(C{row}:N{row})" # O - 15-й столбец

# Итог снизу
ws1[f'A{max_row + 1}'] = "ВСЕГО:"
ws1[f'O{max_row + 1}'] = f"=SUM(O2:O{max_row})"
ws1[f'O{max_row + 1}'].font = bold_font


# === ЛИСТ 2: ПРОГНОЗ ===
ws2 = wb.create_sheet("Forecast_Values")
ws2.append(['ID', 'Название операции'] + months + ['ИТОГО год'])

for r in dataframe_to_rows(df_forecast, index=False, header=False):
    ws2.append(r)

for row in range(2, max_row + 1):
    ws2[f'O{row}'] = f"=SUM(C{row}:N{row})"

ws2[f'A{max_row + 1}'] = "ВСЕГО:"
ws2[f'O{max_row + 1}'] = f"=SUM(O2:O{max_row})"
ws2[f'O{max_row + 1}'].font = bold_font


# === ЛИСТ 3: МЕТРИКИ ПО МЕСЯЦАМ ===
ws3 = wb.create_sheet("Metrics_Monthly")

# Формируем сложную шапку
# Статичные колонки: A, B, C, D
# Блок MAPE: E-P (12 мес) + Q (Среднее)
# Блок Разница ПШЕ: R-AC (12 мес) + AD (Итого)
# Блок Разница ШТ: AE-AP (12 мес) + AQ (Итого)

headers = ['ID', 'Название', 'Хронометраж', 'Коэфф. ПШЕ']
# Добавляем названия месяцев с префиксами для каждого блока
headers += [f"MAPE {m}" for m in months] + ["MAPE Год"]
headers += [f"Diff_FTE {m}" for m in months] + ["Diff_FTE Год"]
headers += [f"Diff_Pcs {m}" for m in months] + ["Diff_Pcs Год"]

ws3.append(headers)

# Основной цикл по строкам
for i in range(num_ops):
    row = i + 2
    
    # 1. Базовые данные
    ws3[f'A{row}'] = f"='Fact_Values'!A{row}"
    ws3[f'B{row}'] = f"='Fact_Values'!B{row}"
    ws3[f'C{row}'] = chronometry[i]
    ws3[f'D{row}'] = f"=C{row}/60/148.3" # Коэффициент ПШЕ
    
    # Цикл по месяцам (столбцы данных с 3 по 14 в исходниках, индексы C-N)
    for m_idx, month_col_letter in enumerate(['C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N']):
        
        # --- БЛОК MAPE (Столбцы E - P) ---
        # Индекс столбца в ws3: 5 + m_idx
        col_mape = get_column_letter(5 + m_idx)
        # Формула: ABS(Fact - Forecast) / Fact
        ws3[f'{col_mape}{row}'] = f"=IFERROR(ABS('Fact_Values'!{month_col_letter}{row}-'Forecast_Values'!{month_col_letter}{row})/'Fact_Values'!{month_col_letter}{row}, 0)"
        ws3[f'{col_mape}{row}'].number_format = '0%'
        
        # --- БЛОК Diff FTE (Столбцы R - AC) ---
        # Индекс столбца в ws3: 18 + m_idx
        col_fte = get_column_letter(18 + m_idx)
        # Формула: (Fact - Forecast) * Coeff
        # Используем ABS для метрики разницы по модулю, или обычную разницу для баланса? 
        # Обычно для RMSE и MAPE нужен модуль. Для "Дефицита" нужен знак.
        # Сделаем модуль разницы (ошибка), так как считаем метрики точности.
        ws3[f'{col_fte}{row}'] = f"=('Fact_Values'!{month_col_letter}{row}-'Forecast_Values'!{month_col_letter}{row})*D{row}"
        ws3[f'{col_fte}{row}'].number_format = '0.00'

        # --- БЛОК Diff Pcs (Столбцы AE - AP) ---
        # Индекс столбца в ws3: 31 + m_idx
        col_pcs = get_column_letter(31 + m_idx)
        ws3[f'{col_pcs}{row}'] = f"='Fact_Values'!{month_col_letter}{row}-'Forecast_Values'!{month_col_letter}{row}"

    # --- ГОДОВЫЕ ИТОГИ ПО СТРОКЕ ---
    
    # Средний MAPE за год (Столбец Q - 17)
    ws3[f'Q{row}'] = f"=AVERAGE(E{row}:P{row})"
    ws3[f'Q{row}'].number_format = '0.0%'
    
    # Сумма ошибки FTE за год (Столбец AD - 30)
    ws3[f'AD{row}'] = f"=SUM(R{row}:AC{row})"
    ws3[f'AD{row}'].number_format = '0.00'

    # Сумма ошибки ШТ за год (Столбец AQ - 43)
    ws3[f'AQ{row}'] = f"=SUM(AE{row}:AP{row})"


# === ИТОГИ В ПОДВАЛЕ ТАБЛИЦЫ (СРЕДНЕЕ, СУММА, RMSE) ===
footer = num_ops + 2
ws3[f'A{footer}'] = "ИТОГИ:"
ws3[f'A{footer}'].font = bold_font

# 1. MAPE (Столбцы E-Q): Считаем СРЕДНЕЕ
for col_idx in range(5, 18): # E to Q
    col = get_column_letter(col_idx)
    ws3[f'{col}{footer}'] = f"=AVERAGE({col}2:{col}{footer-1})"
    ws3[f'{col}{footer}'].number_format = '0.0%'
    ws3[f'{col}{footer}'].font = bold_font

# 2. Diff FTE (Столбцы R-AD): Считаем СУММУ (баланс)
for col_idx in range(18, 31): # R to AD
    col = get_column_letter(col_idx)
    ws3[f'{col}{footer}'] = f"=SUM({col}2:{col}{footer-1})"
    ws3[f'{col}{footer}'].number_format = '0.00'
    ws3[f'{col}{footer}'].font = bold_font

# 3. RMSE FTE (Добавляем строкой ниже, footer + 1)
# Считаем RMSE для каждого месяца по столбцам Diff FTE (R-AD)
rmse_row = footer + 1
ws3[f'A{rmse_row}'] = "RMSE (FTE):"
ws3[f'A{rmse_row}'].font = Font(bold=True, color="FF0000")

for col_idx in range(18, 31): # R to AD (Diff FTE Columns)
    col = get_column_letter(col_idx)
    # Формула: КОРЕНЬ( СУММКВ(Диапазон) / СЧЁТ(Диапазон) )
    # SUMSQ (СУММКВ) берет сумму квадратов, что и нужно для RMSE
    ws3[f'{col}{rmse_row}'] = f"=SQRT(SUMSQ({col}2:{col}{footer-1})/COUNT({col}2:{col}{footer-1}))"
    ws3[f'{col}{rmse_row}'].number_format = '0.00'
    ws3[f'{col}{rmse_row}'].font = Font(bold=True, color="FF0000")


# --- 3. Оформление ---
for sheet in [ws1, ws2, ws3]:
    # Границы
    for row in sheet.iter_rows():
        for cell in row:
            cell.border = thin_border
            if cell.row == 1:
                cell.font = bold_font
                cell.fill = fill_header

# Специфическое оформление Листа 3 (Цвета зон)
# Зона MAPE (E-Q)
for row in ws3.iter_rows(min_col=5, max_col=17):
    for cell in row:
        if cell.row == 1: cell.fill = fill_mape # Шапка

# Зона FTE (R-AD)
for row in ws3.iter_rows(min_col=18, max_col=30):
    for cell in row:
        if cell.row == 1: cell.fill = fill_fte

# Автоширина
for sheet in [ws1, ws2, ws3]:
    for column_cells in sheet.columns:
        length = max(len(str(cell.value)) if cell.value else 0 for cell in column_cells)
        # Ограничим ширину, чтобы не было гигантов
        final_width = min(length + 3, 20) 
        sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = final_width

# Сохранение
file_name = "Analysis_Model_Forecast_Monthly_2025.xlsx"
wb.save(file_name)
print(f"Файл '{file_name}' успешно создан!")
