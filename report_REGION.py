import os

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
        return parse_sheet(multi_str, sheet, filename, basis_index)
    except FileNotFoundError:
        print(f"Файл {filepath} не найден.")
        return {}
    except Exception as e:
        print(f"Произошла ошибка: {e}")
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


def _parse_single_position(sheet, filename, basis_index):
    """Разбор (parse) файла с одной позицией (single position)."""
    report_dict = {}

    basis_value = sheet.cell_value(basis_index, 2)
    Basis = basis_value.split(' ')[0]
    Deponent = '-'
    Comment = ''

    depo_type_operation = sheet.cell_value(9, 2)
    AssignmentType, OperationType, StageName = get_entities_with_codificator(depo_type_operation)
    NumberKD = sheet.cell_value(23, 4)
    NGRI = sheet.cell_value(23, 1)
    AccountDepoSection = sheet.cell_value(16, 2)
    AccountDepo = sheet.cell_value(13, 2)

    goal_count = sheet.cell_value(13, 0)
    if 'Со счета депо' in goal_count:
        DebitAccount = sheet.cell_value(13, 2)
        DebitAccountSection = sheet.cell_value(16, 2)
        DepoAccountSection = ''
        DepoAccount = ''
    elif 'На счет депо' in goal_count:
        DebitAccount = ''
        DebitAccountSection = ''
        DepoAccountSection = sheet.cell_value(16, 2)
        DepoAccount = sheet.cell_value(13, 2)
    else:
        DebitAccount = ''
        DebitAccountSection = ''
        DepoAccountSection = ''
        DepoAccount = ''

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

        filename_entities = filename.split('_')
        Account_from_filename = ''
        for entity in filename_entities:
            if len(entity) == 6:
                Account_from_filename = entity

        for idx, row_num in enumerate(str_list, start=1):
            report_dict = {}
            row_idx = row_num - 1

            goal_count = sheet.cell_value(13, 0)
            if 'Со счета депо' in goal_count:
                DebitAccount = sheet.cell_value(13, 2)
                DebitAccountSection = sheet.cell_value(16, 2)
                DepoAccountSection = ''
                DepoAccount = ''
            elif 'На счет депо' in goal_count:
                DebitAccount = ''
                DebitAccountSection = ''
                DepoAccountSection = sheet.cell_value(16, 2)
                DepoAccount = sheet.cell_value(13, 2)
            else:
                DebitAccount = ''
                DebitAccountSection = ''
                DepoAccountSection = ''
                DepoAccount = ''

            NumberKD = sheet.cell_value(23, 4)
            NGRI = sheet.cell_value(23, 1)

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
        if data[outer_key]:
            rows.append(data[outer_key])

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
