"""
Формирование ежемесячного загрузочного файла Ord_Quantity.xlsx
для АХД по количеству поручений (assignment quantity).

Источники (sources):
  - I_<YYYY_MM>_GPB.xlsx      (report_GPB.py)
  - I_<YYYY_MM>_RSD_msg.xlsx  (report_RSD_msg.py)
  - I_<YYYY_MM>_RSD_xls.xlsx  (report_RSD_xls.py)
  - I_<YYYY_MM>_VTBSD.xlsx    (report_VTBSD.py)
  - I_<YYYY_MM>_REGION.xlsx   (report_REGION.py)

Итоговая книга содержит листы (sheets):
  1. СВОД_операций     — все строки из 5 отчётов
  2. Ord_Quantity      — сводная по типам поручений
  3. Кол-воПоручений   — плоский список поручений
  4. REPs              — разбор ГПБ (REP)
  5. Кол-воПорученийREP— сводная по REP
  6. Dks               — разбор ГПБ (D)

Запуск (run):
    python ord_quantity.py
"""

import os
import sys
from collections import defaultdict

import pandas as pd
from openpyxl.utils import get_column_letter

from get_month_name_dir import get_current_year_month

# ---------------------------------------------------------------------------
# Типы поручений (assignment types) для листа Ord_Quantity
# ---------------------------------------------------------------------------
ASSIGNMENT_TYPES = ['Z', 'G', 'T', 'Y', 'P', 'F', 'XP', 'XF', 'RP', 'RF', 'VP', 'VF']

# ---------------------------------------------------------------------------
# Маппинг источника → Депозитарий / Владелец
# ---------------------------------------------------------------------------
DEPOSITARY_MAP = {
    'GPB': 'Банк ГПБ АО',
    'RSD_msg': 'АО "ДК РЕГИОН"',
    'RSD_xls': 'АО "ДК РЕГИОН"',
    'VTBSD': 'АО "ВТБ СД"',
    'REGION': 'АО "ДК РЕГИОН"',
}

OWNER_MAP = {
    'GPB': 'АО "ДОМ.РФ"',
    'RSD_msg': 'ООО "ДОМ.РФ ИА"',
    'RSD_xls': 'ООО "ДОМ.РФ ИА"',
    'VTBSD': 'ООО "ДОМ.РФ ИА"',
    'REGION': 'АО "ДОМ.РФ"',
}

# ---------------------------------------------------------------------------
# Унифицированные столбцы для СВОД_операций
# ---------------------------------------------------------------------------
SVOD_COLUMNS = [
    'Дата операции',
    'Депозитарий',
    'Счет депо',
    'Тип операции',
    'Счет операции',
    'Раздел списания',
    'Раздел зачисления',
    'Счет зачисления',
    'Раздел счета зачисления',
    'НГРИ',
    'Номер КД',
    'Тип поручения',
    'Комментарий',
    'Технический столбец',
    'Источник',
]

# Маппинг столбцов каждого источника → унифицированные столбцы СВОД_операций.
# Ключ — унифицированное имя, значение — список возможных имён в исходном файле.
COLUMN_ALIASES = {
    'Дата операции': ['Дата операции', 'Дата проведения операции'],
    'Счет депо': ['СчетДЕПО', 'Счет ДЕПО', 'Счет должника', 'Код должника'],
    'Тип операции': ['ТипОперации', 'Тип операции'],
    'Счет операции': ['СчетСписания', 'Счет списания'],
    'Раздел списания': ['РазделСчетаСписания', 'Раздел счета списания'],
    'Раздел зачисления': ['РазделСчетаЗачисления', 'Раздел счета зачисления'],
    'Счет зачисления': ['СчетЗачисления', 'Счет зачисления'],
    'Раздел счета зачисления': ['РазделСчетаЗачисления', 'Раздел счета зачисления'],
    'НГРИ': ['НГРИ', 'Номер госрегистрации (НГРИ)'],
    'Номер КД': ['НомерКД', 'Номер КД', 'Номер кредитного договора'],
    'Тип поручения': ['ТипПоручения', 'Тип поручения', 'Тип поручений'],
    'Комментарий': ['Комментарий'],
    'Технический столбец': ['Основание операции', 'Основание', 'Основание операции'],
    'Источник': ['Источник', 'Имя файла-источника / Номер документа в ЕД'],
}

REPORT_SOURCES = ['GPB', 'RSD_msg', 'RSD_xls', 'VTBSD', 'REGION']


# ========================================================================
# Загрузка данных (data loading)
# ========================================================================

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


def _load_all_reports(month: str) -> dict[str, pd.DataFrame]:
    """Загружает все 5 отчётов и возвращает dict {source_name: DataFrame}."""
    result = {}
    for src in REPORT_SOURCES:
        df = _load_report(month, src)
        if df is not None and not df.empty:
            result[src] = df
            print(f"  {src}: {len(df)} строк")
        else:
            print(f"  {src}: нет данных (no data)")
    return result


# ========================================================================
# Вспомогательные функции (helpers)
# ========================================================================

def _resolve_column(row_or_df, aliases: list[str]) -> str:
    """Находит первый существующий столбец из списка алиасов."""
    cols = row_or_df.columns if hasattr(row_or_df, 'columns') else row_or_df.index
    for alias in aliases:
        if alias in cols:
            return alias
    return ''


def _get_value(row: pd.Series, aliases: list[str], default=''):
    """Получает значение из строки по первому совпавшему алиасу."""
    for alias in aliases:
        if alias in row.index:
            val = row[alias]
            if pd.notna(val):
                return val
    return default


def _month_title(month: str) -> str:
    """Формирует 'Март 2025' из '2025_03'."""
    month_names = {
        '01': 'Январь', '02': 'Февраль', '03': 'Март',
        '04': 'Апрель', '05': 'Май', '06': 'Июнь',
        '07': 'Июль', '08': 'Август', '09': 'Сентябрь',
        '10': 'Октябрь', '11': 'Ноябрь', '12': 'Декабрь',
    }
    parts = month.split('_')
    year = parts[0]
    mm = parts[1]
    return f'{month_names.get(mm, mm)} {year}'


# ========================================================================
# 1. СВОД_операций
# ========================================================================

def _build_svod(reports: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Объединяет все строки из 5 отчётов в единый DataFrame (СВОД_операций).
    Добавляет столбец 'Депозитарий' на основе маппинга источника.
    """
    all_rows = []

    for source, df in reports.items():
        depositary = DEPOSITARY_MAP.get(source, source)
        for _, row in df.iterrows():
            unified = {}
            for target_col, aliases in COLUMN_ALIASES.items():
                unified[target_col] = _get_value(row, aliases)
            unified['Депозитарий'] = depositary
            all_rows.append(unified)

    if not all_rows:
        return pd.DataFrame(columns=SVOD_COLUMNS)

    svod_df = pd.DataFrame(all_rows)
    for col in SVOD_COLUMNS:
        if col not in svod_df.columns:
            svod_df[col] = ''
    return svod_df[SVOD_COLUMNS]


# ========================================================================
# 2. Ord_Quantity (сводная таблица)
# ========================================================================

def _build_ord_quantity(svod_df: pd.DataFrame) -> list[dict]:
    """
    Агрегирует данные СВОД_операций в сводную таблицу Ord_Quantity.
    Группировка: Депозитарий + Владелец (из маппинга) + Счет депо.
    Подсчёт Пор. и Закл. по каждому типу поручения.
    """
    key_data = defaultdict(lambda: {
        at: {'orders': 0, 'bonds': 0} for at in ASSIGNMENT_TYPES
    })

    source_to_depositary = {}
    for src in REPORT_SOURCES:
        source_to_depositary[DEPOSITARY_MAP.get(src, '')] = src

    for _, row in svod_df.iterrows():
        dep = str(row.get('Депозитарий', '')).strip()
        account = str(row.get('Счет депо', '')).strip()
        at = str(row.get('Тип поручения', '')).strip()

        if not account or not at:
            continue

        src = source_to_depositary.get(dep, '')
        owner = OWNER_MAP.get(src, dep)
        key = (dep, owner, account)

        if at in ASSIGNMENT_TYPES:
            key_data[key][at]['orders'] += 1
            nkd = str(row.get('Номер КД', '')).strip()
            if nkd and nkd not in ('', '-', '0'):
                key_data[key][at]['bonds'] += 1

    rows = []
    for (dep, owner, account), type_counts in sorted(key_data.items()):
        r = {
            'Депозитарий': dep,
            'Владельцы': owner,
            'Счет Деп.': account,
        }
        for at in ASSIGNMENT_TYPES:
            r[f'{at}_Пор'] = type_counts[at]['orders'] or 0
            r[f'{at}_Закл'] = type_counts[at]['bonds'] or 0

        r['Q_Закл'] = sum(type_counts[at]['orders'] for at in ASSIGNMENT_TYPES)
        r['Q_Пор'] = r['Q_Закл']
        rows.append(r)

    return rows


# ========================================================================
# 3. Кол-воПоручений (плоский список)
# ========================================================================

def _build_kol_vo_porucheniy(svod_df: pd.DataFrame) -> pd.DataFrame:
    """
    Формирует плоский список всех поручений для листа 'Кол-воПоручений'.
    Столбцы: Названия строк, Счет депо, Идел или Осн, Тип поручения, Дата операции.
    """
    rows = []
    for _, row in svod_df.iterrows():
        account = str(row.get('Счет депо', '')).strip()
        at = str(row.get('Тип поручения', '')).strip()
        date_val = row.get('Дата операции', '')
        section = str(row.get('Раздел списания', '')).strip()
        if not section or section == '-':
            section = str(row.get('Раздел зачисления', '')).strip()

        if not account or not at:
            continue

        source = str(row.get('Источник', '')).strip()
        row_name = f"{account}_{section}_{at}_{date_val}"

        rows.append({
            'Названия строк': row_name,
            'Счет депо': account,
            'Идел или Осн': section,
            'Тип поручения': at,
            'Дата операции': date_val,
        })

    if not rows:
        return pd.DataFrame(columns=['Названия строк', 'Счет депо', 'Идел или Осн',
                                     'Тип поручения', 'Дата операции'])
    return pd.DataFrame(rows)


# ========================================================================
# 4. REPs (разбор ГПБ REP)
# ========================================================================

def _build_reps(reports: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Фильтрует строки из I_*_GPB.xlsx, где Источник содержит 'REP'.
    """
    gpb_df = reports.get('GPB')
    if gpb_df is None or gpb_df.empty:
        return pd.DataFrame()

    src_col = _resolve_column(gpb_df, ['Источник', 'Имя файла-источника / Номер документа в ЕД'])
    if not src_col:
        return pd.DataFrame()

    mask = gpb_df[src_col].astype(str).str.contains('REP', case=False, na=False)
    rep_df = gpb_df[mask].copy()

    rename_map = {}
    for col in rep_df.columns:
        if col == 'Дата операции' or col == 'Дата проведения операции':
            rename_map[col] = 'Дата операции'
        elif col in ('СчетДЕПО', 'Счет ДЕПО', 'Счет должника'):
            rename_map[col] = 'Счет депо'
        elif col in ('НГРИ', 'Номер госрегистрации (НГРИ)'):
            rename_map[col] = 'НГРИ'
        elif col in ('КодОперации', 'Код операции'):
            rename_map[col] = 'Код операции'
        elif col in ('ТипОперации', 'Тип операции'):
            rename_map[col] = 'Вид операции'
        elif col in ('ТипПоручения', 'Тип поручения', 'Тип поручений'):
            rename_map[col] = 'Тип поручения'
        elif col == 'Депонент':
            rename_map[col] = 'Вид поручения'
        elif col in ('Источник', 'Имя файла-источника / Номер документа в ЕД'):
            rename_map[col] = 'Источник'

    rep_df = rep_df.rename(columns=rename_map)
    return rep_df


# ========================================================================
# 5. Кол-воПорученийREP (сводная по REP)
# ========================================================================

def _build_kol_vo_rep(rep_df: pd.DataFrame) -> pd.DataFrame:
    """
    Формирует сводную по REP-файлам: операция → файл → количество.
    """
    if rep_df.empty:
        return pd.DataFrame()

    type_col = None
    for c in ['Тип поручения', 'ТипПоручения']:
        if c in rep_df.columns:
            type_col = c
            break

    src_col = None
    for c in ['Источник', 'Имя файла-источника / Номер документа в ЕД']:
        if c in rep_df.columns:
            src_col = c
            break

    op_col = None
    for c in ['Вид операции', 'ТипОперации', 'Тип операции']:
        if c in rep_df.columns:
            op_col = c
            break

    if not type_col or not src_col:
        return pd.DataFrame()

    rows = []
    grouped = rep_df.groupby([type_col, src_col] if not op_col else [op_col, src_col])
    for keys, group in grouped:
        operation = keys[0] if len(keys) > 1 else ''
        source_file = keys[-1]
        count = len(group)
        rows.append({
            'Операция': operation,
            'Названия строк': source_file,
            'Количество по полю Тип сделки или иного основания': count,
        })

    if not rows:
        return pd.DataFrame()

    result_df = pd.DataFrame(rows)
    total = result_df['Количество по полю Тип сделки или иного основания'].sum()
    total_row = pd.DataFrame([{
        'Операция': '',
        'Названия строк': 'Общий итог',
        'Количество по полю Тип сделки или иного основания': total,
    }])
    result_df = pd.concat([result_df, total_row], ignore_index=True)

    return result_df


# ========================================================================
# 6. Dks (разбор ГПБ D)
# ========================================================================

def _build_dks(reports: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Фильтрует строки из I_*_GPB.xlsx, где Источник содержит 'D_' (файлы типа D).
    """
    gpb_df = reports.get('GPB')
    if gpb_df is None or gpb_df.empty:
        return pd.DataFrame()

    src_col = _resolve_column(gpb_df, ['Источник', 'Имя файла-источника / Номер документа в ЕД'])
    if not src_col:
        return pd.DataFrame()

    mask = gpb_df[src_col].astype(str).str.contains(r'\bD_', case=False, na=False, regex=True)
    d_df = gpb_df[mask].copy()

    rename_map = {}
    for col in d_df.columns:
        if col == 'Дата операции' or col == 'Дата проведения операции':
            rename_map[col] = 'Дата операции'
        elif col in ('СчетДЕПО', 'Счет ДЕПО', 'Счет должника'):
            rename_map[col] = 'Счет депо'
        elif col in ('НГРИ', 'Номер госрегистрации (НГРИ)'):
            rename_map[col] = 'НГРИ'
        elif col in ('ТипОперации', 'Тип операции'):
            rename_map[col] = 'Наименование документа'
        elif col in ('Основание операции', 'Основание'):
            rename_map[col] = 'Номер документа'
        elif col in ('ТипПоручения', 'Тип поручения', 'Тип поручений'):
            rename_map[col] = 'Тип поручения'
        elif col in ('Источник', 'Имя файла-источника / Номер документа в ЕД'):
            rename_map[col] = 'Источник'

    d_df = d_df.rename(columns=rename_map)
    return d_df


# ========================================================================
# Запись Excel (write Excel)
# ========================================================================

def _write_excel(
    month: str,
    svod_df: pd.DataFrame,
    ord_qty_rows: list[dict],
    kol_vo_df: pd.DataFrame,
    rep_df: pd.DataFrame,
    kol_vo_rep_df: pd.DataFrame,
    dks_df: pd.DataFrame,
    output_file: str,
):
    """Записывает все листы в одну книгу Excel."""

    if os.path.exists(output_file):
        print(f"Файл {output_file} уже существует.")
        return

    title = _month_title(month)

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        wb = writer.book

        # ---- 1. СВОД_операций ----
        ws_svod = wb.create_sheet('СВОД_операций')
        ws_svod.append([
            'Участвуют файлы ГПБ (I и D), РСД (I, R-01), РЕГИОН (IS), ВТБСД (VTB00001)'
        ])
        ws_svod.append(SVOD_COLUMNS)
        for _, row in svod_df.iterrows():
            ws_svod.append([row.get(c, '') for c in SVOD_COLUMNS])

        # ---- 2. Ord_Quantity ----
        ws_oq = wb.create_sheet('Ord_Quantity')
        _write_ord_quantity_sheet(ws_oq, ord_qty_rows, title)

        # ---- 3. Кол-воПоручений ----
        ws_kv = wb.create_sheet('Кол-воПоручений')
        ws_kv.append([''])
        kv_cols = ['Названия строк', 'Счет депо', 'Идел или Осн',
                   'Тип поручения', 'Дата операции']
        ws_kv.append(kv_cols)
        for _, row in kol_vo_df.iterrows():
            ws_kv.append([row.get(c, '') for c in kv_cols])

        # ---- 4. REPs ----
        ws_rep = wb.create_sheet('REPs')
        ws_rep.append(['Разбор ГПБ (REP)'])
        if not rep_df.empty:
            ws_rep.append(list(rep_df.columns))
            for _, row in rep_df.iterrows():
                ws_rep.append(list(row.values))

        # ---- 5. Кол-воПорученийREP ----
        ws_kv_rep = wb.create_sheet('Кол-воПорученийREP')
        ws_kv_rep.append([
            'Операция', '', 'ПЕРЕВОД ЦЕННЫХ БУМАГ ПО РАЗДЕЛАМ СЧЕТА ДЕПО'
        ])
        ws_kv_rep.append([''])
        if not kol_vo_rep_df.empty:
            ws_kv_rep.append(list(kol_vo_rep_df.columns))
            for _, row in kol_vo_rep_df.iterrows():
                ws_kv_rep.append(list(row.values))

        # ---- 6. Dks ----
        ws_dks = wb.create_sheet('Dks')
        ws_dks.append(['Разбор ГПБ (D)'])
        if not dks_df.empty:
            ws_dks.append(list(dks_df.columns))
            for _, row in dks_df.iterrows():
                ws_dks.append(list(row.values))

        if 'Sheet' in wb.sheetnames:
            del wb['Sheet']

    print(f"Файл сохранён: {output_file}")


def _write_ord_quantity_sheet(ws, rows: list[dict], title: str):
    """
    Записывает лист Ord_Quantity с многоуровневым заголовком.
    Структура заголовков (по скриншотам ord_2, ord_3):
      Строка 1: 'Количество поручений'
      Строка 2: типы поручений (верхний уровень)
      Строка 3: Депозитарий | Владельцы | Счет Деп. | Пор. | Закл. ...
    """

    # -- Строка 1 --
    header_row_1 = [title, '', '', '']
    for at in ASSIGNMENT_TYPES:
        header_row_1.extend([at, ''])
    # Q
    header_row_1.extend(['Q', ''])
    # Хранение комплектов: DF | DP | в тек.
    header_row_1.extend(['Хранение комплектов', '', ''])
    # S(u): Закл | Лист
    header_row_1.extend(['S(u)', ''])
    # S(b): Закл | Лист
    header_row_1.extend(['S(b)', ''])
    # Spr(u): Закл | Лист
    header_row_1.extend(['Spr(u)', ''])
    # Spr(b): Закл | Лист
    header_row_1.extend(['Spr(b)', ''])
    # Открытие счета: Пор.
    header_row_1.append('Открытие счета')
    # Назначение УЛ: Пор.
    header_row_1.append('Назначение УЛ')
    # Прочие расходы
    header_row_1.append('Прочие расходы в сумме руб.')

    ws.append(['Количество поручений'])
    ws.append(header_row_1)

    # -- Строка 2 (подзаголовки) --
    header_row_2 = ['Депозитарий', 'Владельцы', 'Счет Деп.', '']
    for at in ASSIGNMENT_TYPES:
        header_row_2.extend(['Пор.', 'Закл.'])
    # Q
    header_row_2.extend(['Закл.', 'Пор.'])
    # Хранение комплектов: DF | DP | в тек.
    header_row_2.extend(['DF', 'DP', 'в тек.'])
    # S(u): Закл | Лист
    header_row_2.extend(['Закл.', 'Лист'])
    # S(b): Закл | Лист
    header_row_2.extend(['Закл.', 'Лист'])
    # Spr(u): Закл | Лист
    header_row_2.extend(['Закл.', 'Лист'])
    # Spr(b): Закл | Лист
    header_row_2.extend(['Закл.', 'Лист'])
    # Открытие счета: Пор.
    header_row_2.append('Пор.')
    # Назначение УЛ: Пор.
    header_row_2.append('Пор.')
    # Прочие расходы
    header_row_2.append('')

    ws.append(header_row_2)

    # -- Данные --
    for r in rows:
        data_row = [
            r.get('Депозитарий', ''),
            r.get('Владельцы', ''),
            r.get('Счет Деп.', ''),
            '',
        ]
        for at in ASSIGNMENT_TYPES:
            data_row.append(r.get(f'{at}_Пор', 0))
            data_row.append(r.get(f'{at}_Закл', 0))

        # Q
        data_row.append(r.get('Q_Закл', 0))
        data_row.append(r.get('Q_Пор', 0))

        # Хранение комплектов (пустые — заполняются вручную)
        data_row.extend([0, 0, 0])
        # S(u)
        data_row.extend([0, 0])
        # S(b)
        data_row.extend([0, 0])
        # Spr(u)
        data_row.extend([0, 0])
        # Spr(b)
        data_row.extend([0, 0])
        # Открытие счета
        data_row.append(0)
        # Назначение УЛ
        data_row.append(0)
        # Прочие расходы
        data_row.append(0)

        ws.append(data_row)


# ========================================================================
# Главная функция (main)
# ========================================================================

def main():
    month = get_current_year_month()
    print(f"{'=' * 70}")
    print(f"Формирование Ord_Quantity для {month}")
    print(f"{'=' * 70}")

    reports = _load_all_reports(month)

    if not reports:
        print("Нет данных для формирования Ord_Quantity.")
        sys.exit(0)

    # 1. СВОД_операций
    print("\n[1/6] Формирование СВОД_операций...")
    svod_df = _build_svod(reports)
    print(f"  СВОД: {len(svod_df)} строк")

    # 2. Ord_Quantity
    print("[2/6] Формирование Ord_Quantity...")
    ord_qty_rows = _build_ord_quantity(svod_df)
    print(f"  Ord_Quantity: {len(ord_qty_rows)} строк")

    # 3. Кол-воПоручений
    print("[3/6] Формирование Кол-воПоручений...")
    kol_vo_df = _build_kol_vo_porucheniy(svod_df)
    print(f"  Кол-воПоручений: {len(kol_vo_df)} строк")

    # 4. REPs
    print("[4/6] Формирование REPs...")
    rep_df = _build_reps(reports)
    print(f"  REPs: {len(rep_df)} строк")

    # 5. Кол-воПорученийREP
    print("[5/6] Формирование Кол-воПорученийREP...")
    kol_vo_rep_df = _build_kol_vo_rep(rep_df)
    print(f"  Кол-воПорученийREP: {len(kol_vo_rep_df)} строк")

    # 6. Dks
    print("[6/6] Формирование Dks...")
    dks_df = _build_dks(reports)
    print(f"  Dks: {len(dks_df)} строк")

    # Запись Excel
    output_file = f'./{month}/{month}_Ord_Quantity.xlsx'
    _write_excel(
        month, svod_df, ord_qty_rows, kol_vo_df,
        rep_df, kol_vo_rep_df, dks_df, output_file,
    )

    print(f"{'=' * 70}")
    print("Готово (done).")


if __name__ == '__main__':
    main()
