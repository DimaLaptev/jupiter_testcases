import os
import traceback

import xlrd
import pandas as pd

from get_month_name_dir import get_current_year_month


def get_report(directoria: str, filename: str):
    print(f'{filename=}')
    try:
        filepath = f'{directoria}{filename}'
        workbook = xlrd.open_workbook(filepath)

        sheet = workbook.sheet_by_index(0)
        print(f'{type(sheet)=}')
        multi_str = False
        str_list = []
        for i in range(sheet.nrows):
            if multi_str:
                print(f'{sheet.cell_value(i, 0)=}')
                if isinstance(sheet.cell_value(i, 0), float):
                    str_list.append(int(sheet.cell_value(i, 0)))
            if sheet.cell_value(i, 0) == '№ п/п' and not multi_str:
                if sheet.cell_value(i+1, 0) == 1 and sheet.cell_value(i+2, 0) == 2:
                    print('в файле несколько позиций')
                    multi_str = True
            if sheet.cell_value(i, 0) == 'Рег.№ поручения:':
                basis_index = i
        print(f'{str_list=}')
        return parse_sheet(str_list, sheet, filename, basis_index)
    except FileNotFoundError:
        print(f"Файл {filepath} не найден.")
        return {}
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        traceback.print_exc()
        return {}


def get_entities_with_codificator(depo_type_operation: str):
    if depo_type_operation == 'Списание ценных бумаг':
        AssignmentType = 'G'
        OperationType = 'Снятие (списание) ЦБ'
        StageName = '12212'
    elif depo_type_operation == 'Зачисление ценных бумаг':
        AssignmentType = 'Z'
        OperationType = 'Прием (зачисление) ЦБ'
        StageName = '12211'
    elif depo_type_operation == 'Зачисление ценных бумаг (перевод)':
        AssignmentType = 'F'
        OperationType = 'Перевод ЦБ по счетам (зачисление)'
        StageName = '12003'
    elif depo_type_operation == 'Списание ценных бумаг (перевод)':
        AssignmentType = 'P'
        OperationType = 'Списание ценных бумаг (перевод)'
        StageName = '12003'
    elif depo_type_operation == 'Снятие залога ЦБ':
        AssignmentType = 'E'
        OperationType = 'Перевод ЦБ по разделам счета'
        StageName = '12002'
    else:
        AssignmentType = ''
        OperationType = ''
        StageName = ''
    return AssignmentType, OperationType, StageName


def _find_account_rows(sheet):
    """
    Находит (find) строки с 'На счет депо' и 'Со счета депо' по всему листу (sheet).
    Возвращает dict с ключами 'На счет депо' и 'Со счета депо',
    значения — номер строки (row index) или None.
    """
    result = {'На счет депо': None, 'Со счета депо': None}
    for i in range(sheet.nrows):
        cell = sheet.cell_value(i, 0)
        if not isinstance(cell, str):
            continue
        cell_stripped = cell.strip()
        if 'На счет депо' in cell_stripped and result['На счет депо'] is None:
            result['На счет депо'] = i
        elif 'Со счета депо' in cell_stripped and result['Со счета депо'] is None:
            result['Со счета депо'] = i
    return result


def _extract_accounts(sheet, account_rows: dict):
    """
    Извлекает (extract) данные счетов списания/зачисления
    на основе найденных строк (rows).
    """
    DebitAccount = ''
    DebitAccountSection = ''
    DepoAccount = ''
    DepoAccountSection = ''

    co_row = account_rows.get('Со счета депо')
    na_row = account_rows.get('На счет депо')

    if co_row is not None:
        DebitAccount = sheet.cell_value(co_row, 2)
        if co_row + 3 < sheet.nrows:
            DebitAccountSection = sheet.cell_value(co_row + 3, 2)

    if na_row is not None:
        DepoAccount = sheet.cell_value(na_row, 2)
        if na_row + 3 < sheet.nrows:
            DepoAccountSection = sheet.cell_value(na_row + 3, 2)

    return DebitAccount, DebitAccountSection, DepoAccount, DepoAccountSection


def _parse_single_position(sheet, filename, basis_index):
    """Разбор (parse) файла с одной позицией (single position)."""
    report_dict = {}

    basis_value = sheet.cell_value(basis_index, 2)
    Basis = basis_value.split(' ')[0]
    Deponent = '-'
    Comment = ''

    depo_type_operation = sheet.cell_value(9, 2)
    AssignmentType, OperationType, StageName = get_entities_with_codificator(depo_type_operation)

    account_rows = _find_account_rows(sheet)

    na_row = account_rows.get('На счет депо')
    co_row = account_rows.get('Со счета депо')
    ngri_base_row = na_row if na_row is not None else (co_row if co_row is not None else 13)

    NumberKD = ''
    NGRI = ''
    if ngri_base_row + 10 < sheet.nrows:
        NumberKD = sheet.cell_value(ngri_base_row + 10, 4)
        NGRI = sheet.cell_value(ngri_base_row + 10, 1)

    DebitAccount, DebitAccountSection, DepoAccount, DepoAccountSection = \
        _extract_accounts(sheet, account_rows)

    filename_entities = filename.split('_')
    Account_from_filename = ''
    for entity in filename_entities:
        if len(entity) == 6:
            Account_from_filename = entity

    Initiator = 'Акционерное общество "ДОМ.РФ"'
    OperationDate = sheet.cell_value(10, 2)

    report_dict['Дата операции'] = OperationDate
    report_dict['КодОперации'] = StageName
    report_dict['ТипОперации'] = OperationType
    report_dict['Инициатор'] = Initiator
    report_dict['СчетДЕПО'] = Account_from_filename
    report_dict['СчетСписания'] = DebitAccount
    report_dict['РазделСчетаСписания'] = DebitAccountSection
    report_dict['СчетЗачисления'] = DepoAccount
    report_dict['РазделСчетаЗачисления'] = DepoAccountSection
    report_dict['НГРИ'] = NGRI
    report_dict['НомерКД'] = NumberKD
    report_dict['ТипПоручения'] = AssignmentType
    report_dict['Комментарий'] = Comment
    report_dict['Депонент'] = Deponent
    report_dict['Основание операции'] = Basis
    report_dict['Источник'] = filename

    return report_dict


def parse_sheet(str_list: list, sheet, filename: str, basis_index: int = 27):
    file_dict = {}
    report_dict = {}
    if not str_list:
        print('single')
        report_dict = _parse_single_position(sheet, filename, basis_index)
        file_dict[1] = report_dict
        print(f'{file_dict}')
        return file_dict
    else:
        print('multi')
        basis_value = sheet.cell_value(basis_index, 2)
        print(f'{basis_value=}')
        Basis = basis_value.split(' ')[0]
        Deponent = '-'
        Comment = ''
        depo_type_operation = sheet.cell_value(9, 2)
        AssignmentType, OperationType, StageName = get_entities_with_codificator(depo_type_operation)

        Initiator = 'Акционерное общество "ДОМ.РФ"'
        OperationDate = sheet.cell_value(10, 2)

        account_rows = _find_account_rows(sheet)
        DebitAccount, DebitAccountSection, DepoAccount, DepoAccountSection = \
            _extract_accounts(sheet, account_rows)

        na_row = account_rows.get('На счет депо')
        co_row = account_rows.get('Со счета депо')
        ngri_base_row = na_row if na_row is not None else (co_row if co_row is not None else 13)

        NumberKD = ''
        NGRI = ''
        if ngri_base_row + 10 < sheet.nrows:
            NumberKD = sheet.cell_value(ngri_base_row + 10, 4)
            NGRI = sheet.cell_value(ngri_base_row + 10, 1)

        filename_entities = filename.split('_')
        Account_from_filename = ''
        for entity in filename_entities:
            if len(entity) == 6:
                Account_from_filename = entity

        for idx, row_num in enumerate(str_list, start=1):
            report_dict = {}

            report_dict['Дата операции'] = OperationDate
            report_dict['КодОперации'] = StageName
            report_dict['ТипОперации'] = OperationType
            report_dict['Инициатор'] = Initiator
            report_dict['СчетДЕПО'] = Account_from_filename
            report_dict['СчетСписания'] = DebitAccount
            report_dict['РазделСчетаСписания'] = DebitAccountSection
            report_dict['СчетЗачисления'] = DepoAccount
            report_dict['РазделСчетаЗачисления'] = DepoAccountSection
            report_dict['НГРИ'] = NGRI
            report_dict['НомерКД'] = NumberKD
            report_dict['ТипПоручения'] = AssignmentType
            report_dict['Комментарий'] = Comment
            report_dict['Депонент'] = Deponent
            report_dict['Основание операции'] = Basis
            report_dict['Источник'] = filename
            file_dict[idx] = report_dict

        print(f'{file_dict}')
        return file_dict


def make_excel_report(data, output_file):
    if os.path.exists(output_file):
        print(f"Файл {output_file} уже существует.")
        return
    print(f'{data=}')
    rows = []

    for outer_key in data:
        file_dict = data[outer_key]
        if file_dict:
            for position_key in file_dict:
                record = file_dict[position_key]
                if record:
                    rows.append(record)

    if rows:
        columns = list(rows[0].keys())

        df = pd.DataFrame(rows, columns=columns)

        df.to_excel(output_file, index=False, sheet_name='Отчет')
    else:
        print("Нет данных для создания Excel-файла.")


def files_counter():
    directoria = f'./{get_current_year_month()}/REGION/REP/'
    main_report = {}
    for filename in os.listdir(directoria):
        if filename.endswith('.XLS'):
            main_report[filename] = get_report(directoria, filename)
            print(f'{main_report=}')
    make_excel_report(main_report, f'./{get_current_year_month()}/I_{get_current_year_month()}_REGION.xlsx')


if __name__ == "__main__":
    files_counter()
