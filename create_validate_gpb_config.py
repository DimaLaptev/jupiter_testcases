"""
Генерирует validate_gpb_config.xlsx (Excel) — коды выписки и подпапки для validate_gpb_files.py.
Запуск из корня проекта: python depo_validation/create_validate_gpb_config.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openpyxl import Workbook

from file_handler_config_loader import VALIDATE_GPB_CONFIG_PATH

DEFAULT_STATEMENT_CODES = [
    "00004", "00083", "00070", "00109", "00108", "00107", "00110", "00136",
    "00248", "00252", "00167", "00166", "00240", "00239", "00253", "00254",
    "00256", "00255", "00263", "00264", "00234", "00235",
]

DEFAULT_SUBFOLDERS = ["D", "I", "R"]


def create_validate_gpb_config_xlsx() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "config"
    ws.append(["section", "key", "value"])

    start_codes = ws.max_row + 1
    for code in DEFAULT_STATEMENT_CODES:
        ws.append(["validation", "GPB_STATEMENT_CODES", str(code)])
    for r in range(start_codes, ws.max_row + 1):
        ws.cell(row=r, column=3).number_format = "@"

    for folder in DEFAULT_SUBFOLDERS:
        ws.append(["validation", "GPB_SUBFOLDERS", folder])

    VALIDATE_GPB_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(VALIDATE_GPB_CONFIG_PATH)


if __name__ == "__main__":
    create_validate_gpb_config_xlsx()
    print(f"Записано: {VALIDATE_GPB_CONFIG_PATH}")
