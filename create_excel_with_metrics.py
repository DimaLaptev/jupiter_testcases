import pandas as pd
import openpyxl

# Создаем структуру таблицы
columns = [
    "ID (A)", 
    "Название операции (B)", 
    "Хронометраж, мин (C)", 
    "Коэфф. ПШЕ (D)", 
    "Факт, шт (E)", 
    "Прогноз, шт (F)", 
    "Разница, шт (G)", 
    "MAPE % (шт) (H)",
    "Факт, ПШЕ (I)",
    "Прогноз, ПШЕ (J)",
    "Разница, ПШЕ (K)",
    "MAPE % (ПШЕ) (L)",
    "Квадрат ошибки (M)"
]

# Создаем пустой DataFrame
df = pd.DataFrame(columns=columns)

# Сохраняем в Excel, чтобы добавить формулы
file_path = 'shablon_analiza_modeli.xlsx'
writer = pd.ExcelWriter(file_path, engine='openpyxl')
df.to_excel(writer, index=False, sheet_name='Анализ точности')

workbook = writer.book
worksheet = writer.sheets['Анализ точности']

# Добавляем пример формул для строк 2-100
# Обратите внимание: Google Sheets/Excel автоматически переведет формулы на русский, если у вас русский интерфейс
for row in range(2, 102):
    # Коэффициент перевода в ПШЕ: (Минуты / 60) / 148.3
    worksheet[f'D{row}'] = f'=C{row}/60/148.3'
    
    # Разница в штуках (модуль)
    worksheet[f'G{row}'] = f'=ABS(E{row}-F{row})'
    
    # MAPE % (штуки). IFERROR нужен, чтобы не было ошибки при делении на 0
    worksheet[f'H{row}'] = f'=IFERROR(G{row}/E{row}, 0)'
    
    # Факт ПШЕ (Факт шт * Коэфф)
    worksheet[f'I{row}'] = f'=E{row}*D{row}'
    
    # Прогноз ПШЕ (Прогноз шт * Коэфф)
    worksheet[f'J{row}'] = f'=F{row}*D{row}'
    
    # Разница ПШЕ
    worksheet[f'K{row}'] = f'=ABS(I{row}-J{row})'
    
    # MAPE % (ПШЕ)
    worksheet[f'L{row}'] = f'=IFERROR(K{row}/I{row}, 0)'
    
    # Квадрат ошибки для RMSE
    worksheet[f'M{row}'] = f'=(I{row}-J{row})^2'

# Добавляем строку ИТОГО сверху (в строку 1, сдвинув заголовки, но для простоты добавим в ячейки справа от таблицы)
# В реальном файле лучше закрепить первую строку

writer.close()

print(f"Файл {file_path} успешно создан.")
