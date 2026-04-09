"""
Одноразовые проверки окружения сервиса (health): переменные, почта, каталоги,
Excel-конфиги depo_validation, API Регион. Запуск: python main_test.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv

# Имена переменных (environment), которые должны быть заданы непустыми (как в config_ews).
_REQUIRED_ENV = [
    "MAIL_SERVER_NAME",
    "MAIL_1_ADDRESS",
    "MAIL_1_USERNAME",
    "MAIL_1_PASSWORD",
    "MAIL_2_ADDRESS",
    "MAIL_2_USERNAME",
    "MAIL_2_PASSWORD",
    "REPORS_DEPO_DIRECTORY",
    "DECODE",
    "DOMRF_OPEN_DIR",
    "DOMRFIA_OPEN_DIR",
    "DOMRF_SECRET_DIR",
    "DOMRFIA_SECRET_DIR",
    "EIS_DIR",
    "REPORTS_DIR",
]

_DEPO_VALIDATION_XLSX = (
    "file_handler_config.xlsx",
    "validate_gpb_config.xlsx",
    "validate_rsd_config.xlsx",
)


def _check_env() -> List[str]:
    missing = [name for name in _REQUIRED_ENV if not (os.getenv(name) or "").strip()]
    if missing:
        return [f"Не заданы или пусты переменные окружения: {', '.join(missing)}"]
    return []


def _check_mailboxes() -> List[str]:
    errors: List[str] = []
    try:
        from exchangelib import Account, Configuration, Credentials, DELEGATE
    except ImportError as e:
        return [f"exchangelib не установлен: {e}"]

    from config_ews import (
        MAIL_1_ADDRESS,
        MAIL_1_PASSWORD,
        MAIL_1_USERNAME,
        MAIL_2_ADDRESS,
        MAIL_2_PASSWORD,
        MAIL_2_USERNAME,
        MAIL_SERVER_NAME,
    )

    pairs: List[Tuple[str, str, str, str]] = [
        ("MAIL_1", MAIL_1_ADDRESS, MAIL_1_USERNAME, MAIL_1_PASSWORD),
        ("MAIL_2", MAIL_2_ADDRESS, MAIL_2_USERNAME, MAIL_2_PASSWORD),
    ]
    for label, addr, user, pwd in pairs:
        try:
            creds = Credentials(username=user, password=pwd)
            config = Configuration(server=MAIL_SERVER_NAME, credentials=creds)
            account = Account(
                primary_smtp_address=addr,
                credentials=creds,
                autodiscover=False,
                config=config,
                access_type=DELEGATE,
            )
            _ = account.inbox.total_count
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Почта {label} ({addr}): {type(exc).__name__}: {exc}")
    return errors


def _check_directories() -> List[str]:
    from config_ews import (
        DECODE,
        DOMRFIA_OPEN_DIR,
        DOMRFIA_SECRET_DIR,
        DOMRF_OPEN_DIR,
        DOMRF_SECRET_DIR,
        EIS_DIR,
        REPORS_DEPO_DIRECTORY,
        REPORTS_DIR,
    )

    errors: List[str] = []
    repors = (REPORS_DEPO_DIRECTORY or "").strip()

    checks: List[Tuple[str, str]] = []
    if repors:
        checks.append(("REPORS_DEPO_DIRECTORY", repors))
        decode = (DECODE or "").strip()
        if decode:
            combined = os.path.normpath(os.path.join(repors, decode))
            checks.append(("REPORS_DEPO_DIRECTORY + DECODE", combined))

    for name, path in (
        ("DOMRF_OPEN_DIR", DOMRF_OPEN_DIR),
        ("DOMRFIA_OPEN_DIR", DOMRFIA_OPEN_DIR),
        ("DOMRF_SECRET_DIR", DOMRF_SECRET_DIR),
        ("DOMRFIA_SECRET_DIR", DOMRFIA_SECRET_DIR),
        ("EIS_DIR", EIS_DIR),
        ("REPORTS_DIR", REPORTS_DIR),
    ):
        p = (path or "").strip()
        if p:
            checks.append((name, os.path.normpath(p)))

    for label, path in checks:
        if not os.path.isdir(path):
            errors.append(f"Каталог недоступен или не существует ({label}): {path}")
        elif not os.access(path, os.R_OK):
            errors.append(f"Нет чтения (read) для каталога ({label}): {path}")

    return errors


def _check_depo_validation_xlsx() -> List[str]:
    repors = (os.getenv("REPORS_DEPO_DIRECTORY") or "").strip()
    if not repors:
        return ["REPORS_DEPO_DIRECTORY пуст — не проверяем depo_validation"]

    base = Path(repors) / "depo_validation"
    errors: List[str] = []
    for name in _DEPO_VALIDATION_XLSX:
        p = base / name
        if not p.is_file():
            errors.append(f"Нет файла (file): {p}")
    return errors


def _run_region_check() -> Tuple[List[str], int]:
    script_dir = Path(__file__).resolve().parent
    rc = subprocess.run(
        [sys.executable, "region_connect_check.py"],
        cwd=str(script_dir),
        check=False,
    )
    out: List[str] = []
    if rc.returncode != 0:
        out.append(
            f"region_connect_check.py завершился с кодом (exit code) {rc.returncode}"
        )
    return out, rc.returncode


def main() -> None:
    load_dotenv()

    all_errors: List[str] = []

    print("=" * 60)
    print("1. Переменные окружения (environment) из config_ews")
    print("=" * 60)
    env_err = _check_env()
    if env_err:
        all_errors.extend(env_err)
        for e in env_err:
            print(f"  [FAIL] {e}")
    else:
        print("  [OK] Все обязательные переменные заданы непустыми значениями")

    print("\n" + "=" * 60)
    print("2. Почтовые ящики (Exchange / EWS)")
    print("=" * 60)
    if env_err:
        print("  [SKIP] из-за ошибок переменных окружения")
    else:
        mail_err = _check_mailboxes()
        if mail_err:
            all_errors.extend(mail_err)
            for e in mail_err:
                print(f"  [FAIL] {e}")
        else:
            print("  [OK] Подключение к MAIL_1 и MAIL_2 успешно")

    print("\n" + "=" * 60)
    print("3. Каталоги из config_ews (строки 18–27)")
    print("=" * 60)
    if env_err:
        print("  [SKIP] из-за ошибок переменных окружения")
    else:
        dir_err = _check_directories()
        if dir_err:
            all_errors.extend(dir_err)
            for e in dir_err:
                print(f"  [FAIL] {e}")
        else:
            print("  [OK] Каталоги существуют и доступны на чтение")

    print("\n" + "=" * 60)
    print("4. Excel в depo_validation (file_handler / validate_gpb / validate_rsd)")
    print("=" * 60)
    if env_err:
        print("  [SKIP] из-за ошибок переменных окружения")
    else:
        xlsx_err = _check_depo_validation_xlsx()
        if xlsx_err:
            all_errors.extend(xlsx_err)
            for e in xlsx_err:
                print(f"  [FAIL] {e}")
        else:
            print("  [OK] Все три .xlsx на месте")

    print("\n" + "=" * 60)
    print("5. API Регион (region_connect_check.py)")
    print("=" * 60)
    if env_err:
        print("  [SKIP] из-за ошибок переменных окружения")
        region_notes: List[str] = []
    else:
        region_notes, _region_code = _run_region_check()
        all_errors.extend(region_notes)
        for n in region_notes:
            print(f"  [FAIL] {n}")
        if not region_notes:
            print("  [OK] region_connect_check завершился успешно")

    print("\n" + "=" * 60)
    if all_errors:
        print("ИТОГ: ОШИБКИ")
        for e in all_errors:
            print(f"  - {e}")
        sys.exit(1)
    print("ИТОГ: OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
