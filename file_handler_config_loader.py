from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from openpyxl import load_workbook

FILE_HANDLER_CONFIG_PATH = (
    Path(__file__).resolve().parent / "depo_validation" / "file_handler_config.xlsx"
)
FILE_HANDLER_2_CONFIG_PATH = (
    Path(__file__).resolve().parent / "depo_validation" / "file_handler_2_config.xlsx"
)
VALIDATE_GPB_CONFIG_PATH = (
    Path(__file__).resolve().parent / "depo_validation" / "validate_gpb_config.xlsx"
)
VALIDATE_RSD_CONFIG_PATH = (
    Path(__file__).resolve().parent / "depo_validation" / "validate_rsd_config.xlsx"
)

_VALID_FH2_DEST = frozenset({"D", "I", "R", "REP", "SPR"})


def load_file_handler_config(
    filename: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Читает excel-файл (Excel) с настройками и возвращает словарь
    с ключами, совпадающими с константами в file_handler.py.
    """

    path = Path(filename) if filename is not None else FILE_HANDLER_CONFIG_PATH
    wb = load_workbook(filename=path, data_only=True)
    ws = wb["config"]

    raw: Dict[str, List[str]] = {}

    # пропускаем шапку
    for row in ws.iter_rows(min_row=2, values_only=True):
        _, key, value = row
        if key is None:
            continue
        if value is None:
            continue
        raw.setdefault(str(key), []).append(str(value))

    config: Dict[str, Any] = {}

    # скалярные значения (scalar values)
    for scalar_key in ("SOURCE_DIR", "DIR_DOMRF", "DIR_DOMRFIA"):
        values = raw.get(scalar_key, [])
        config[scalar_key] = values[0] if values else ""

    # списки (lists)
    list_keys = [
        "pattern_DOMRF_MSG",
        "pattern_DOMRF_MSG_code",
        "pattern_DOMRF_any",
        "pattern_DOMRF_any_code",
        "pattern_DOMRF_TXT",
        "pattern_DOMRF_TXT_code",
        "pattern_DOMRFIA_MSG",
        "pattern_DOMRFIA_MSG_code",
        "pattern_DOMRFIA_any",
        "pattern_DOMRFIA_any_code",
    ]

    for list_key in list_keys:
        config[list_key] = raw.get(list_key, [])

    return config


def load_file_handler_2_rules(
    filename: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """
    Читает excel-файл (Excel) со справочником правил для file_handler_2.py:
    лист (sheet) «rules», колонки sort_order, extension, name_prefix, dest_folder.
    Правила с одинаковым extension проверяются по порядку sort_order.
    """

    path = Path(filename) if filename is not None else FILE_HANDLER_2_CONFIG_PATH
    wb = load_workbook(filename=path, data_only=True)
    ws = wb["rules"]

    rules: List[Dict[str, Any]] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or all(c is None for c in row):
            continue
        order, ext, prefix, dest = (row + (None,) * 4)[:4]
        if ext is None or str(ext).strip() == "":
            continue
        dest_key = str(dest).strip() if dest is not None else ""
        if dest_key not in _VALID_FH2_DEST:
            raise ValueError(
                f"file_handler_2_config: неизвестный dest_folder {dest_key!r}, "
                f"ожидается одно из {sorted(_VALID_FH2_DEST)}"
            )
        sort_order = 0
        if order is not None:
            if isinstance(order, int):
                sort_order = order
            elif isinstance(order, float):
                sort_order = int(order)
            else:
                sort_order = int(str(order).strip())
        rules.append(
            {
                "sort_order": sort_order,
                "ext": str(ext).strip().lower(),
                "prefix": str(prefix) if prefix is not None else "",
                "dest": dest_key,
            }
        )

    rules.sort(key=lambda r: (r["sort_order"], r["ext"], r["prefix"]))
    return rules


def _normalize_gpb_statement_code(value: Any) -> str:
    """Сохраняет ведущие нули (leading zeros) для кодов из Excel."""
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return f"{int(value):05d}"
    if isinstance(value, int):
        return f"{value:05d}"
    s = str(value).strip()
    if s.isdigit():
        return s.zfill(5)
    return s


def load_validate_gpb_config(
    filename: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Читает excel-файл (Excel) для validate_gpb_files.py:
    лист «config», колонки section, key, value (как file_handler_config).
    Ключи: GPB_STATEMENT_CODES (список), GPB_SUBFOLDERS (список).
    """

    path = Path(filename) if filename is not None else VALIDATE_GPB_CONFIG_PATH
    wb = load_workbook(filename=path, data_only=True)
    ws = wb["config"]

    raw_codes: List[str] = []
    raw_folders: List[str] = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        _, key, value = (row + (None,) * 3)[:3]
        if key is None or value is None:
            continue
        k = str(key).strip()
        if k == "GPB_STATEMENT_CODES":
            code = _normalize_gpb_statement_code(value)
            if code:
                raw_codes.append(code)
        elif k == "GPB_SUBFOLDERS":
            folder = str(value).strip()
            if folder:
                raw_folders.append(folder)

    if not raw_codes:
        raise ValueError("validate_gpb_config: нет строк с key=GPB_STATEMENT_CODES")
    if not raw_folders:
        raise ValueError("validate_gpb_config: нет строк с key=GPB_SUBFOLDERS")

    return {
        "GPB_STATEMENT_CODES": raw_codes,
        "GPB_SUBFOLDERS": raw_folders,
    }


def _normalize_rsd_depo_account(value: Any) -> str:
    """Нормализует «Счёт депо» (depo account) для сравнения с фрагментом в имени файла."""
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    s = str(value).strip()
    if s.isdigit():
        return str(int(s))
    return s


def load_validate_rsd_config(
    filename: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Читает excel-файл (Excel) для validate_rsd_files.py:
    лист «config», колонки section, key, value.
    Ключи: RSD_DEPO_ACCOUNTS (список), RSD_SUBFOLDERS (список),
    RSD_FILE_PREFIX (одна строка, по умолчанию D — префикс имён вида D_YYMMDD_…).
    """

    path = Path(filename) if filename is not None else VALIDATE_RSD_CONFIG_PATH
    wb = load_workbook(filename=path, data_only=True)
    ws = wb["config"]

    raw_accounts: List[str] = []
    raw_folders: List[str] = []
    prefix_values: List[str] = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        _, key, value = (row + (None,) * 3)[:3]
        if key is None:
            continue
        k = str(key).strip()
        if k == "RSD_DEPO_ACCOUNTS":
            if value is None:
                continue
            acc = _normalize_rsd_depo_account(value)
            if acc:
                raw_accounts.append(acc)
        elif k == "RSD_SUBFOLDERS":
            if value is None:
                continue
            folder = str(value).strip()
            if folder:
                raw_folders.append(folder)
        elif k == "RSD_FILE_PREFIX":
            if value is not None and str(value).strip():
                prefix_values.append(str(value).strip())

    if not raw_accounts:
        raise ValueError("validate_rsd_config: нет строк с key=RSD_DEPO_ACCOUNTS")
    if not raw_folders:
        raise ValueError("validate_rsd_config: нет строк с key=RSD_SUBFOLDERS")

    file_prefix = prefix_values[0] if prefix_values else "D"

    return {
        "RSD_DEPO_ACCOUNTS": raw_accounts,
        "RSD_SUBFOLDERS": raw_folders,
        "RSD_FILE_PREFIX": file_prefix,
    }


if __name__ == "__main__":
    cfg = load_file_handler_config()
    for k, v in cfg.items():
        print(k, "=", v)
