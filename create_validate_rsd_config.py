"""
Генерирует validate_rsd_config.xlsx (Excel) — счета депо и подпапки для validate_rsd_files.py.
Запуск из корня проекта: python depo_validation/create_validate_rsd_config.py

Список счетов — по таблицам со скриншотов (Validation РСД); при необходимости отредактируйте Excel.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openpyxl import Workbook

from file_handler_config_loader import VALIDATE_RSD_CONFIG_PATH

# «Счёт депо» (depo account), 9 цифр — объединение строк со скриншотов
DEFAULT_DEPO_ACCOUNTS = sorted(
    {
        300008201,
        300028701,
        300028801,
        300028901,
        300043501,
        300044001,
        300046301,
        300046901,
        300047001,
        300047301,
        300047401,
        300047701,
        300048201,
        300048301,
        300049401,
        300049501,
        300049701,
        300049901,
        300050001,
        300050101,
        300051001,
        300051101,
        300051201,
        300052201,
        300052301,
        300052601,
        300052701,
        300053101,
        300053201,
        300053901,
        300054001,
        300054101,
        300054201,
        300054601,
        300054701,
        300054801,
        300054901,
        300055301,
        300055401,
        300055501,
        300055601,
    }
)


def create_validate_rsd_config_xlsx() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "config"
    ws.append(["section", "key", "value"])

    start_acc = ws.max_row + 1
    for acc in DEFAULT_DEPO_ACCOUNTS:
        ws.append(["rsd", "RSD_DEPO_ACCOUNTS", str(acc)])
    for r in range(start_acc, ws.max_row + 1):
        ws.cell(row=r, column=3).number_format = "@"

    for sub in ("D",):
        ws.append(["rsd", "RSD_SUBFOLDERS", sub])

    ws.append(["rsd", "RSD_FILE_PREFIX", "D"])

    VALIDATE_RSD_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    wb.save(VALIDATE_RSD_CONFIG_PATH)


if __name__ == "__main__":
    create_validate_rsd_config_xlsx()
    print(f"Записано: {VALIDATE_RSD_CONFIG_PATH} ({len(DEFAULT_DEPO_ACCOUNTS)} счетов)")
