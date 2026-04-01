"""
Валидация файлов РСД: проверка наличия .MSG с «Счёт депо» (depo account) в имени за вчера
в папках вида YYYY_MM/RSD/<подпапка>. Имя: {prefix}_YYMMDD_<цифры>.MSG (пример: D_260130_000300008201.MSG).
Отправка отчёта в Outlook / Exchange — как validate_gpb_files.py.
"""

import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Set

from dotenv import load_dotenv

from file_handler_config_loader import load_validate_rsd_config

_validate_rsd = load_validate_rsd_config()
RSD_DEPO_ACCOUNTS: List[str] = _validate_rsd["RSD_DEPO_ACCOUNTS"]
RSD_SUBFOLDERS: List[str] = _validate_rsd["RSD_SUBFOLDERS"]
RSD_FILE_PREFIX: str = _validate_rsd["RSD_FILE_PREFIX"]


def get_base_path() -> str:
    """Корневая папка (текущий месяц, напр. 2026_04)."""
    from config_ews import GPB_BASE_DIR

    return os.path.abspath(GPB_BASE_DIR or ".")


def get_rsd_month_path() -> str:
    """Путь к папке RSD за текущий месяц: YYYY_MM/RSD."""
    base = get_base_path()
    month_dir = datetime.now().strftime("%Y_%m")
    return os.path.join(base, month_dir, "RSD")


def get_yesterday_yymmdd() -> str:
    """Дата вчера в формате YYMMDD (как в имени файла РСД)."""
    yesterday = datetime.now() - timedelta(days=1)
    return yesterday.strftime("%y%m%d")


def _build_filename_pattern(file_prefix: str, date_yymmdd: str):
    esc_p = re.escape(file_prefix)
    esc_d = re.escape(date_yymmdd)
    # D_260130_000300008201.MSG — после даты блок цифр (часто 12), сравниваем по int
    return re.compile(
        rf"^{esc_p}_{esc_d}_(?P<depo>\d+)\.msg$",
        re.IGNORECASE,
    )


def find_depo_accounts_in_folder(
    folder_path: str,
    pattern: re.Pattern[str],
    expected_accounts: Set[str],
) -> Set[str]:
    """Возвращает множество нормализованных счетов депо, найденных в именах файлов."""
    found: Set[str] = set()
    if not os.path.isdir(folder_path):
        return found
    for name in os.listdir(folder_path):
        m = pattern.match(name)
        if not m:
            continue
        depo_raw = m.group("depo")
        if not depo_raw.isdigit():
            continue
        normalized = str(int(depo_raw))
        if normalized in expected_accounts:
            found.add(normalized)
    return found


def collect_missing_accounts(base_rsd: str, date_yymmdd: str) -> Dict[str, List[str]]:
    """
    Недостающие счета депо по каждой подпапке RSD.
    Возвращает: { \"D\": [...], ... }
    """
    expected = set(RSD_DEPO_ACCOUNTS)
    pattern = _build_filename_pattern(RSD_FILE_PREFIX, date_yymmdd)
    result: Dict[str, List[str]] = {sub: [] for sub in RSD_SUBFOLDERS}
    for sub in RSD_SUBFOLDERS:
        folder = os.path.join(base_rsd, sub)
        found = find_depo_accounts_in_folder(folder, pattern, expected)
        missing = [a for a in RSD_DEPO_ACCOUNTS if a not in found]
        result[sub] = sorted(missing, key=lambda x: int(x))
    return result


def build_email_body(missing_by_folder: Dict[str, List[str]]) -> str:
    """Формирует HTML-таблицу для письма."""
    rows = []
    for folder in RSD_SUBFOLDERS:
        accs = missing_by_folder.get(folder, [])
        accs_str = ", ".join(accs) if accs else "—"
        rows.append(f"<tr><td>{folder}</td><td>{accs_str}</td></tr>")
    return f"""<html><body>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Папка</th><th>Недостающие счета депо</th></tr>
{chr(10).join(rows)}
</table>
</body></html>"""


def _send_via_exchangelib(subject: str, html_body: str, to_recipients: str) -> bool:
    try:
        from exchangelib import Credentials, Account, DELEGATE, Configuration, Version, Build
        from exchangelib import Message, Mailbox, HTMLBody
        from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
        from config_ews import (
            MAIL_ADDRESS,
            MAIL_PASSWORD,
            MAIL_SERVER_NAME,
            USE_AUTODISCOVER,
            VERIFY_SSL,
        )
    except ImportError:
        return False

    if not MAIL_ADDRESS or not MAIL_PASSWORD:
        return False

    try:
        if not VERIFY_SSL:
            BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter
        creds = Credentials(username=MAIL_ADDRESS, password=MAIL_PASSWORD)
        if USE_AUTODISCOVER:
            account = Account(
                primary_smtp_address=MAIL_ADDRESS,
                credentials=creds,
                autodiscover=True,
                access_type=DELEGATE,
            )
        else:
            config = Configuration(
                server=MAIL_SERVER_NAME,
                credentials=creds,
                version=Version(build=Build(15, 1)),
            )
            account = Account(
                primary_smtp_address=MAIL_ADDRESS,
                config=config,
                autodiscover=False,
                access_type=DELEGATE,
            )
        m = Message(
            account=account,
            subject=subject,
            body=HTMLBody(html_body),
            to_recipients=[Mailbox(email_address=to_recipients.strip())],
        )
        m.send_and_save()
        print("[OK] Письмо отправлено (Exchange)")
        return True
    except Exception as e:
        print(f"[!] Ошибка отправки через Exchange: {e}")
        return False


def _send_via_outlook(subject: str, html_body: str, to_recipients: str) -> bool:
    try:
        import win32com.client
    except ImportError:
        return False
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.Subject = subject
        mail.HTMLBody = html_body
        mail.To = to_recipients
        mail.Send()
        print("[OK] Письмо отправлено (Outlook)")
        return True
    except Exception as e:
        print(f"[!] Ошибка отправки через Outlook: {e}")
        return False


def send_email(subject: str, html_body: str, to_recipients: str) -> bool:
    if _send_via_outlook(subject, html_body, to_recipients):
        return True
    if _send_via_exchangelib(subject, html_body, to_recipients):
        return True
    print("[!] Не удалось отправить письмо. Установите pywin32 или настройте Exchange в .env")
    return False


def main() -> None:
    load_dotenv()

    base_rsd = get_rsd_month_path()
    date_yymmdd = get_yesterday_yymmdd()
    recipient = os.getenv("RSD_VALIDATION_RECIPIENT") or os.getenv("MAIL_ADDRESS", "")

    print("=" * 60)
    print("Проверка файлов РСД (MSG, счёт депо в имени)")
    print("=" * 60)
    print(f"Папка: {base_rsd}")
    print(f"Дата в имени файла (вчера, YYMMDD): {date_yymmdd}")
    print(f"Префикс имён: {RSD_FILE_PREFIX}_")
    print("=" * 60)

    missing_by_folder = collect_missing_accounts(base_rsd, date_yymmdd)
    all_found = all(not missing_by_folder[f] for f in RSD_SUBFOLDERS)

    for folder in RSD_SUBFOLDERS:
        missing = missing_by_folder[folder]
        status = "+" if not missing else "-"
        print(
            f"{status} {folder}: {len(missing)} недостающих"
            + (f" — {', '.join(missing)}" if missing else "")
        )

    subject = "Проверка файлов РСД (счета депо)"
    if all_found:
        html_body = (
            "<html><body>Проверка РСД пройдена успешно, по всем счетам депо из справочника "
            "найдены файлы за указанную дату.</body></html>"
        )
    else:
        html_body = build_email_body(missing_by_folder)

    if recipient:
        send_email(subject, html_body, recipient)
    else:
        print("\n[!] RSD_VALIDATION_RECIPIENT или MAIL_ADDRESS не задан в .env — письмо не отправлено")
        print("Тело письма:")
        print(html_body)


if __name__ == "__main__":
    main()
