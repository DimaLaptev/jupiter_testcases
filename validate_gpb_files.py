"""
Валидация файлов ГПБ: проверка наличия файлов с кодами выписки за вчера
в папках GPB/D, GPB/I, GPB/R. Отправка отчёта в Outlook.
"""

import os
from dotenv import load_dotenv
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from config_ews import GPB_VALIDATION_RECIPIENT
from file_handler_config_loader import load_validate_gpb_config

_validate_gpb = load_validate_gpb_config()
GPB_STATEMENT_CODES: List[str] = _validate_gpb["GPB_STATEMENT_CODES"]
GPB_SUBFOLDERS: List[str] = _validate_gpb["GPB_SUBFOLDERS"]


def get_base_path() -> str:
    """Корневая папка (текущий месяц, напр. 2026_02)."""
    from config_ews import GPB_BASE_DIR
    base = os.path.abspath(GPB_BASE_DIR or ".")
    return base


def get_gpb_month_path(ref: Optional[datetime] = None) -> str:
    """
    Путь к папке GPB: YYYY_MM/GPB.
    По умолчанию месяц берётся от «вчера», чтобы на стыке месяцев (напр. 1 апреля)
    искать файлы за 31 марта в каталоге 2026_03, а не в 2026_04.
    """
    base = get_base_path()
    d = ref if ref is not None else datetime.now() - timedelta(days=1)
    month_dir = d.strftime("%Y_%m")
    return os.path.join(base, month_dir, "GPB")


def get_yesterday_date_str(ref: Optional[datetime] = None) -> str:
    """Дата проверки в формате YYYYMMDD (по умолчанию — календарный вчера)."""
    d = ref if ref is not None else datetime.now() - timedelta(days=1)
    return d.strftime("%Y%m%d")


def find_files_with_codes(folder_path: str, date_str: str, codes: List[str]) -> Set[str]:
    """
    Ищет в папке файлы формата *_<date>_<code>.<ext> за указанную дату.
    Возвращает множество найденных кодов.
    """
    found = set()
    if not os.path.isdir(folder_path):
        return found
    # Паттерн: любые символы + _ + дата + _ + код выписки (5 цифр) + расширение
    pattern = re.compile(rf"^.+_{re.escape(date_str)}_(?P<code>\d{{5}})\.[^.]+$", re.IGNORECASE)
    for name in os.listdir(folder_path):
        m = pattern.match(name)
        if m:
            code = m.group("code")
            if code in codes:
                found.add(code)
    return found


def collect_missing_codes(base_gpb: str, date_str: str) -> Dict[str, List[str]]:
    """
    Собирает недостающие коды по каждой папке D, I, R.
    Возвращает: { "D": [...], "I": [...], "R": [...] }
    """
    result = {sub: [] for sub in GPB_SUBFOLDERS}
    for sub in GPB_SUBFOLDERS:
        folder = os.path.join(base_gpb, sub)
        found = find_files_with_codes(folder, date_str, GPB_STATEMENT_CODES)
        missing = [c for c in GPB_STATEMENT_CODES if c not in found]
        result[sub] = sorted(missing)
    return result


def build_email_body(missing_by_folder: Dict[str, List[str]]) -> str:
    """Формирует HTML-таблицу для письма."""
    rows = []
    for folder in GPB_SUBFOLDERS:
        codes = missing_by_folder.get(folder, [])
        codes_str = ", ".join(codes) if codes else "—"
        rows.append(f"<tr><td>{folder}</td><td>{codes_str}</td></tr>")
    return f"""<html><body>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Папка</th><th>Недостающие коды выписки</th></tr>
{chr(10).join(rows)}
</table>
</body></html>"""


def _send_via_exchangelib(subject: str, html_body: str, to_recipients: str) -> bool:
    """Отправка через Exchange/EWS (exchangelib), ящик MAIL_2 (см. config_ews)."""
    try:
        from exchangelib import Credentials, Account, DELEGATE, Configuration, Version, Build
        from exchangelib import Message, Mailbox, HTMLBody
        from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
        from config_ews import (
            MAIL_2_ADDRESS,
            MAIL_2_USERNAME,
            MAIL_2_PASSWORD,
            MAIL_SERVER_NAME,
            USE_AUTODISCOVER,
        )
    except ImportError:
        return False

    raw_ssl = os.getenv("VERIFY_SSL")
    verify_ssl = True
    if raw_ssl is not None and raw_ssl != "":
        verify_ssl = raw_ssl.strip().lower() in ("1", "true", "yes", "on")

    if not MAIL_2_ADDRESS or not MAIL_2_USERNAME or not MAIL_2_PASSWORD:
        return False

    try:
        if not verify_ssl:
            BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter
        creds = Credentials(username=MAIL_2_USERNAME, password=MAIL_2_PASSWORD)
        if USE_AUTODISCOVER:
            account = Account(
                primary_smtp_address=MAIL_2_ADDRESS,
                credentials=creds,
                autodiscover=True,
                access_type=DELEGATE
            )
        else:
            config = Configuration(
                server=MAIL_SERVER_NAME,
                credentials=creds,
                version=Version(build=Build(15, 1))
            )
            account = Account(
                primary_smtp_address=MAIL_2_ADDRESS,
                config=config,
                autodiscover=False,
                access_type=DELEGATE
            )
        m = Message(
            account=account,
            subject=subject,
            body=HTMLBody(html_body),
            to_recipients=[Mailbox(email_address=to_recipients.strip())]
        )
        m.send_and_save()
        print("[OK] Письмо отправлено (Exchange)")
        return True
    except Exception as e:
        print(f"[!] Ошибка отправки через Exchange: {e}")
        return False


def _send_via_outlook(subject: str, html_body: str, to_recipients: str) -> bool:
    """Отправка через Outlook (win32com)."""
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
    """Отправляет письмо: сначала Outlook, при отсутствии pywin32 — Exchange."""
    if _send_via_outlook(subject, html_body, to_recipients):
        return True
    if _send_via_exchangelib(subject, html_body, to_recipients):
        return True
    print("[!] Не удалось отправить письмо. Установите pywin32 или настройте Exchange в .env")
    return False


def main() -> None:
    load_dotenv()

    # Одна точка отсчёта (reference): папка месяца и дата в имени файла не расходятся
    ref = datetime.now() - timedelta(days=1)
    base_gpb = get_gpb_month_path(ref)
    date_str = get_yesterday_date_str(ref)
    recipient = (GPB_VALIDATION_RECIPIENT or "").strip()

    print("=" * 60)
    print("Ежедневная проверка файлов ГПБ")
    print("=" * 60)
    print(f"Папка: {base_gpb}")
    print(f"Дата (вчера): {date_str}")
    print("=" * 60)

    missing_by_folder = collect_missing_codes(base_gpb, date_str)

    all_found = all(not missing_by_folder[f] for f in GPB_SUBFOLDERS)

    for folder in GPB_SUBFOLDERS:
        missing = missing_by_folder[folder]
        status = "+" if not missing else "-"
        print(f"{status} {folder}: {len(missing)} недостающих" + (f" — {', '.join(missing)}" if missing else ""))

    subject = "Ежедневная проверка файлов ГПБ"
    if all_found:
        html_body = "<html><body>Проверка ГПБ пройдена успешно, все коды выписок найдены</body></html>"
    else:
        html_body = build_email_body(missing_by_folder)

    if recipient:
        send_email(subject, html_body, recipient)
    else:
        print("\n[!] GPB_VALIDATION_RECIPIENT не задан в .env — письмо не отправлено")
        print("Тело письма:")
        print(html_body)


if __name__ == "__main__":
    main()
