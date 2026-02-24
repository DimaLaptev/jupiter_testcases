"""
Формирование ежемесячного загрузочного файла Ord_Quantity.xlsx
для АХД по количеству поручений (assignment quantity).

Источники (sources):
  - I_<YYYY_MM>_GPB.xlsx      (report_GPB.py)
  - I_<YYYY_MM>_RSD_msg.xlsx  (report_RSD_msg.py)
  - I_<YYYY_MM>_RSD_xls.xlsx  (report_RSD_xls.py)
  - I_<YYYY_MM>_VTBSD.xlsx    (report_VTBSD.py)
  - I_<YYYY_MM>_REGION.xlsx   (report_REGION.py)

Логика (logic):
  Из каждого отчёта (report) извлекаются строки (rows) с полями:
    Депозитарий, Владелец счета депо, Счет депо, ТипПоручения.
  Считается количество поручений (orders count) — одно поручение = одна
  уникальная подача одного типа поручения на одну дату по одному счёту
  и одному разделу счета депо (для ГПБ).
  Считается количество закладных (bonds count) из поля «Количество закладных»
  (НомерКД) если оно доступно.

Запуск (run):
    python ord_quantity.py
"""

import os
import sys
from collections import defaultdict

import pandas as pd

from get_month_name_dir import get_current_year_month

ASSIGNMENT_TYPES = ['Z', 'G', 'D', 'P', 'F', 'X', 'RP', 'RF', 'VP', 'VF']

DEPOSITARY_MAP = {
    'GPB': 'АО "ДК РЕГИОН"',
    'RSD_msg': 'АО "ДК РЕГИОН"',
    'RSD_xls': 'АО "ДК РЕГИОН"',
    'VTBSD': 'АО "ДК РЕГИОН"',
    'REGION': 'АО "ДК РЕГИОН"',
}

OWNER_MAP = {
    'GPB': 'АО "ДОМ.РФ"',
    'RSD_msg': 'ООО "ДОМ.РФ ИА"',
    'RSD_xls': 'ООО "ДОМ.РФ ИА"',
    'VTBSD': 'ООО "ДОМ.РФ ИА"',
    'REGION': 'АО "ДОМ.РФ"',
}


def _load_report(month: str, suffix: str) -> pd.DataFrame | None:
    """Загружает (load) файл отчёта I_<month>_<suffix>.xlsx."""
    filepath = f'./{month}/I_{month}_{suffix}.xlsx'
    if not os.path.exists(filepath):
        print(f"Файл {filepath} не найден — пропуск.")
        return None
    try:
        df = pd.read_excel(filepath)
        print(f"Загружен {filepath}: {len(df)} строк")
        return df
    except Exception as e:
        print(f"Ошибка чтения {filepath}: {e}")
        return None


def _extract_account(row: pd.Series) -> str:
    """Извлекает (extract) счёт депо (depo account) из строки отчёта."""
    for col in ['СчетДЕПО', 'Счет ДЕПО', 'Счет должника', 'Код должника']:
        if col in row.index and row[col] and str(row[col]).strip() not in ('', '-'):
            return str(row[col]).strip()
    return ''


def _extract_assignment_type(row: pd.Series) -> str:
    """Извлекает (extract) тип поручения (assignment type) из строки отчёта."""
    for col in ['ТипПоручения', 'Тип поручения']:
        if col in row.index and row[col] and str(row[col]).strip():
            return str(row[col]).strip()
    return ''


def _count_bonds(row: pd.Series) -> int:
    """
    Подсчитывает количество закладных (bonds count).
    В REGION-отчёте это поле НомерКД, в RSD_xls — Количество закладных,
    в GPB — вычисляется из данных.
    Каждая непустая запись — одна закладная (bond).
    """
    for col in ['Количество закладных', 'НомерКД', 'Номер кредитного договора']:
        if col in row.index:
            val = row[col]
            if val and str(val).strip() not in ('', '-', '0'):
                return 1
    return 0


def _process_report(df: pd.DataFrame, source: str) -> list[dict]:
    """
    Обрабатывает (process) DataFrame отчёта и возвращает
    список записей (records) для агрегации (aggregation).
    """
    records = []
    depositary = DEPOSITARY_MAP.get(source, '')
    owner = OWNER_MAP.get(source, '')

    for _, row in df.iterrows():
        account = _extract_account(row)
        assignment_type = _extract_assignment_type(row)
        bonds = _count_bonds(row)

        if not account or not assignment_type:
            continue

        records.append({
            'Депозитарий': depositary,
            'Владелец': owner,
            'Счет депо': account,
            'ТипПоручения': assignment_type,
            'bonds': bonds,
        })

    return records


def _aggregate(records: list[dict]) -> pd.DataFrame:
    """
    Агрегирует (aggregate) записи (records) в итоговую таблицу (summary table).
    Группировка (grouping): Депозитарий + Владелец + Счет депо.
    Для каждой группы подсчитывается количество поручений (orders) и закладных (bonds)
    в разрезе (breakdown) типов поручений (assignment types).
    """
    key_data = defaultdict(lambda: {
        at: {'orders': 0, 'bonds': 0} for at in ASSIGNMENT_TYPES
    })

    for rec in records:
        key = (rec['Депозитарий'], rec['Владелец'], rec['Счет депо'])
        at = rec['ТипПоручения']
        if at in ASSIGNMENT_TYPES:
            key_data[key][at]['orders'] += 1
            key_data[key][at]['bonds'] += rec['bonds']

    rows = []
    for (dep, owner, account), type_counts in sorted(key_data.items(), key=lambda x: x[0]):
        row = {
            'Депозитарий': dep,
            'Владелец': owner,
            'Счет депо': account,
        }

        total_orders = 0
        total_bonds = 0

        for at in ASSIGNMENT_TYPES:
            orders = type_counts[at]['orders']
            bonds = type_counts[at]['bonds']
            row[f'{at}_Пор'] = orders if orders else ''
            row[f'{at}_Закл'] = bonds if bonds else ''
            total_orders += orders
            total_bonds += bonds

        row['Spr(z)_Закл'] = ''
        row['Spr(z)_Лист'] = ''
        row['Spr(b)_Закл'] = ''
        row['Spr(b)_Лист'] = ''
        row['Q'] = total_orders if total_orders else ''

        rows.append(row)

    return pd.DataFrame(rows)


def _build_header_df(month: str) -> pd.DataFrame:
    """
    Формирует (build) заголовочные строки (header rows) для Excel-файла
    в соответствии с шаблоном (template).
    """
    month_names = {
        '01': 'Январь', '02': 'Февраль', '03': 'Март',
        '04': 'Апрель', '05': 'Май', '06': 'Июнь',
        '07': 'Июль', '08': 'Август', '09': 'Сентябрь',
        '10': 'Октябрь', '11': 'Ноябрь', '12': 'Декабрь',
    }
    parts = month.split('_')
    year = parts[0]
    mm = parts[1]
    month_name = month_names.get(mm, mm)
    return f'{month_name} {year}'


def _write_excel(df: pd.DataFrame, output_file: str, month: str):
    """Записывает (write) итоговый DataFrame в Excel с форматированием (formatting)."""
    if os.path.exists(output_file):
        print(f"Файл {output_file} уже существует.")
        return

    header_title = _build_header_df(month)

    header_row_1 = ['', '', '', 'Тип поручения']
    header_row_2 = ['Депозитарий', 'Владелец\nсчета депо', 'Счет Депо', '']

    for at in ASSIGNMENT_TYPES:
        header_row_1.extend([at, ''])
        header_row_2.extend(['Пор', 'Закл'])

    header_row_1.extend(['Spr(z)', '', 'Spr(b)', '', ''])
    header_row_2.extend(['Закл', 'Лист', 'Закл', 'Лист', 'Q'])

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        workbook = writer.book
        worksheet = workbook.create_sheet('Отчет')

        worksheet.append([header_title])
        worksheet.append(header_row_1)
        worksheet.append(header_row_2)

        for _, row in df.iterrows():
            data_row = [
                row.get('Депозитарий', ''),
                row.get('Владелец', ''),
                row.get('Счет депо', ''),
                '',
            ]
            for at in ASSIGNMENT_TYPES:
                data_row.append(row.get(f'{at}_Пор', ''))
                data_row.append(row.get(f'{at}_Закл', ''))

            data_row.append(row.get('Spr(z)_Закл', ''))
            data_row.append(row.get('Spr(z)_Лист', ''))
            data_row.append(row.get('Spr(b)_Закл', ''))
            data_row.append(row.get('Spr(b)_Лист', ''))
            data_row.append(row.get('Q', ''))

            worksheet.append(data_row)

        if 'Sheet' in workbook.sheetnames:
            del workbook['Sheet']

    print(f"Файл сохранён: {output_file}")


def main():
    month = get_current_year_month()
    print(f"{'='*70}")
    print(f"Формирование Ord_Quantity для {month}")
    print(f"{'='*70}")

    report_sources = {
        'GPB': f'GPB',
        'RSD_msg': f'RSD_msg',
        'RSD_xls': f'RSD_xls',
        'VTBSD': f'VTBSD',
        'REGION': f'REGION',
    }

    all_records = []

    for source_name, suffix in report_sources.items():
        df = _load_report(month, suffix)
        if df is not None and not df.empty:
            records = _process_report(df, source_name)
            print(f"  {source_name}: извлечено записей (records): {len(records)}")
            all_records.extend(records)
        else:
            print(f"  {source_name}: нет данных (no data)")

    if not all_records:
        print("Нет данных для формирования Ord_Quantity.")
        sys.exit(0)

    print(f"\nВсего записей (total records): {len(all_records)}")

    result_df = _aggregate(all_records)
    print(f"Уникальных строк (unique rows): {len(result_df)}")

    output_file = f'./{month}/{month}_Ord_Quantity.xlsx'
    _write_excel(result_df, output_file, month)

    print(f"{'='*70}")
    print("Готово (done).")


if __name__ == '__main__':
    main()
