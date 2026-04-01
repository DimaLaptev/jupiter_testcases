from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from openpyxl import load_workbook

FILE_HANDLER_CONFIG_PATH = (
    Path(__file__).resolve().parent / "depo_validation" / "file_handler_config.xlsx"
)


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


if __name__ == "__main__":
    cfg = load_file_handler_config()
    for k, v in cfg.items():
        print(k, "=", v)
