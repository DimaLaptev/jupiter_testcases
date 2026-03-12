"""
Парсер Excel-документов формата DOC_INSTRUCT (отчёты по документам).
Структура: секция заголовка (key:value), пустая строка, строки с данными (;).
"""

from pathlib import Path
from typing import Any, Optional, Union

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None  # type: ignore


def _get_cell_text(ws: Any, row: int) -> str:
    """Возвращает текст из ячейки A{row}, пустая строка если None."""
    val = ws.cell(row=row, column=1).value
    if val is None:
        return ""
    return str(val).strip()


def _is_header_row(text: str) -> bool:
    """Проверяет, является ли строка парой key:value (без признаков data-строки)."""
    if not text or ";" in text:
        return False
    return ":" in text


def _parse_header_value(text: str) -> Optional[tuple[str, str]]:
    """Разбирает key:value, разделяя только по первому двоеточию."""
    if ":" not in text:
        return None
    idx = text.index(":")
    key = text[:idx].strip()
    value = text[idx + 1 :].strip()
    return (key, value) if key else None


def _is_data_row(text: str, delimiter: str = ";") -> bool:
    """Строка с данными содержит разделитель (; или ,)."""
    return bool(text and delimiter in text)


def parse_doc_instruct_excel(file_path: Union[str, Path]) -> dict:
    """
    Парсит Excel-файл формата DOC_INSTRUCT.

    Возвращает словарь:
    - Ключи из заголовка (ClientID, DepoNum, ...) -> значения
    - Ключи-номера строк (int) для data-строк -> список значений (split по ;)

    Учтены особенности:
    - Количество data-строк может быть любым (0, 1, много)
    - Начало data-строк не фиксировано (не обязательно с 9-й)
    """
    if load_workbook is None:
        raise ImportError("Требуется openpyxl: pip install openpyxl")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    wb = load_workbook(path, read_only=False, data_only=True)
    ws = wb.active
    if ws is None:
        wb.close()
        raise ValueError("В книге нет активного листа")

    result: dict[str, Any] = {}
    max_row = ws.max_row or 0
    row = 1
    in_header = True

    while row <= max_row:
        text = _get_cell_text(ws, row)
        if in_header:
            if _is_header_row(text):
                parsed = _parse_header_value(text)
                if parsed:
                    key, value = parsed
                    result[key] = value
                row += 1
                continue
            # Пустая строка или не header — конец заголовка
            in_header = False
            if not text:
                row += 1
            continue

        # Режим data-строк
        if not text:
            row += 1
            continue
        if _is_data_row(text):
            values = [v.strip() for v in text.split(";")]
            result[row] = values
        row += 1

    wb.close()

    return result


def _is_header_row_for_delim(text: str, delim: str) -> bool:
    """Header = key:value; для delim=',' ключ (до ':') не содержит разделитель."""
    if not text or ":" not in text:
        return False
    idx = text.index(":")
    key_part = text[:idx].strip()
    if delim in key_part:
        return False
    return True


def _is_data_row_for_delim(text: str, delim: str) -> bool:
    """Строка с данными содержит разделитель."""
    return bool(text and delim in text)


def _parse_doc_instruct_text(lines: list[str], delimiter: str = ";") -> dict:
    """
    Парсит текст (список строк) формата DOC_INSTRUCT.
    delimiter — разделитель в data-строках (';' или ',').
    Возвращает тот же формат, что и parse_doc_instruct_excel.
    """
    result = {}
    in_header = True
    row_num = 1
    for line in lines:
        text = line.strip() if line else ""
        if in_header:
            if _is_header_row_for_delim(text, delimiter):
                parsed = _parse_header_value(text)
                if parsed:
                    key, value = parsed
                    result[key] = value
                row_num += 1
                continue
            in_header = False
            if not text:
                row_num += 1
            continue
        if not text:
            row_num += 1
            continue
        if _is_data_row_for_delim(text, delimiter):
            values = [v.strip() for v in text.split(delimiter)]
            result[row_num] = values
        row_num += 1
    return result


def _fix_msg_encoding(content: str) -> str:
    """
    Исправляет mojibake. Пробует: cp1251-as-latin1, utf8-as-latin1.
    Применяется только при признаках порчи (нет кириллицы, есть типичный mojibake).
    """
    if not content:
        return content
    has_cyrillic = any("\u0400" <= c <= "\u04FF" for c in content)
    mojibake_chars = "\u00c2\u00c3\u00d0\u00d1\u00d2\u00d3"  # ÂÃÐÑÒÓ в mojibake
    if has_cyrillic or not any(c in content for c in mojibake_chars):
        return content
    for enc_out in ("cp1251", "utf-8"):
        try:
            fixed = content.encode("latin-1", errors="strict").decode(enc_out)
            if any("\u0400" <= c <= "\u04FF" for c in fixed):
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
    return content


def _read_msg_content(path: Path) -> str:
    """Читает тело .MSG с учётом кодировок cp1251/utf-8."""
    content = None
    try:
        from extract_msg import Message
        msg = Message(path)
        content = msg.body or ""
        msg.close()
    except ImportError:
        pass
    except Exception:
        pass
    if content is None or not content.strip():
        for enc in ("cp1251", "utf-8", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, OSError):
                content = None
        if not content or not content.strip():
            return ""
    # Исправление кодировки при ошибочном декодировании
    content = _fix_msg_encoding(content)
    return content


def parse_doc_instruct_msg(file_path: Union[str, Path]) -> dict:
    """
    Парсит .MSG файл формата DOC_INSTRUCT.
    Извлекает тело письма (body) и разбирает его как текст.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    content = None
    try:
        from extract_msg import Message
        msg = Message(path)
        content = msg.body or ""
        msg.close()
    except ImportError:
        pass
    except Exception:
        pass

    if content is None or not content.strip():
        for enc in ("cp1251", "utf-8", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, OSError):
                content = None
        if not content or not content.strip():
            return {}

    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    result = _parse_doc_instruct_text(lines)
    if not result.get("ReportName") and path.name:
        result["ReportName"] = path.name
    return result


def parse_msg_tz_i(file_path: Union[str, Path]) -> dict:
    """
    Парсит .MSG файл формата tz/I (разделитель в data-строках — запятая).
    Структура: key:value в заголовке, данные — через запятую.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    content = _read_msg_content(path)
    if not content or not content.strip():
        return {}

    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    result = _parse_doc_instruct_text(lines, delimiter=",")
    if not result.get("ReportName") and path.name:
        result["ReportName"] = path.name
    return result


def transform_parsed_to_report_rows(parsed: dict) -> list:
    """
    Преобразует результат parse_doc_instruct_excel в список словарей для отчёта.
    Каждая data-строка -> словарь с ключами: Дата операции, Счет депо, НГРИ,
    Наименование документа, Номер документа, Дата документа, Комментарий,
    Для удаления дубликатов, Тип поручения, Источник.
    """
    from gpb_codes_mapping import get_depo_account_by_client_id

    report_date = parsed.get("ReportDate", "")
    report_name = parsed.get("ReportName", "")
    client_id = parsed.get("ClientID", "")

    depo_account = get_depo_account_by_client_id(client_id)
    if depo_account is None:
        depo_account_str = ""
    else:
        depo_account_str = str(depo_account)

    rows = []
    for key, val in parsed.items():
        if not isinstance(key, int) or not isinstance(val, list):
            continue
        if len(val) < 6:
            continue

        ngri = val[2] if len(val) > 2 else ""
        doc_name = val[3] if len(val) > 3 else ""
        doc_num = val[4] if len(val) > 4 else ""
        doc_date = val[5] if len(val) > 5 else ""
        comment = val[6] if len(val) > 6 else ""

        dup_key = f"{depo_account_str}_{ngri}_{report_date}" if depo_account_str else ""
        instr_type = "DF" if depo_account_str == "10934" else "DP"

        rows.append({
            "Дата операции": report_date,
            "Счет депо": depo_account_str,
            "НГРИ": ngri,
            "Наименование документа": doc_name,
            "Номер документа": doc_num,
            "Дата документа": doc_date,
            "Комментарий": comment,
            "Для удаления дубликатов": dup_key,
            "Тип поручения": instr_type,
            "Источник": report_name,
        })
    return rows


def print_parsed_result(data: dict, use_json: bool = False) -> None:
    """
    Печатает результат парсинга в читаемом виде (словарь).
    use_json=True — вывод в JSON (UTF-8, ключи-номера строк как строка).
    """
    header_keys = [k for k in data if isinstance(k, str)]
    data_keys = sorted(k for k in data if isinstance(k, int))

    out = {}
    for k in header_keys:
        out[k] = data[k]
    for k in data_keys:
        out[k] = data[k]  # Номер строки как уникальный id

    if use_json:
        import json
        # JSON требует строковые ключи
        out_str = {str(k): v for k, v in out.items()}
        print(json.dumps(out_str, ensure_ascii=False, indent=2))
    else:
        from pprint import pprint
        pprint(out, width=120)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Использование: python parse_doc_instruct_excel.py <путь_к_excel> [--json]")
        sys.exit(1)

    path = sys.argv[1]
    use_json = "--json" in sys.argv
    parsed = parse_doc_instruct_excel(path)
    print_parsed_result(parsed, use_json=use_json)