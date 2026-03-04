"""
Валидация файлов ГПБ: проверка наличия файлов с кодами выписки за вчера
в папках GPB/D, GPB/I, GPB/R. Отправка отчёта в Outlook.
"""

import os
from dotenv import load_dotenv
import re
from datetime import datetime, timedelta
from typing import Dict, List, Set

# Коды выписки из Validation_GPB (столбец D)
GPB_STATEMENT_CODES = [
    "00004", "00083", "00070", "00109", "00108", "00107", "00110", "00136",
    "00248", "00252", "00167", "00166", "00240", "00239", "00253", "00254",
    "00256", "00255", "00263", "00264", "00234", "00235",
]

# Папки для проверки
GPB_SUBFOLDERS = ["D", "I", "R"]


def get_base_path() -> str:
    """Корневая папка (текущий месяц, напр. 2026_02)."""
    from config_ews import GPB_BASE_DIR
    base = os.path.abspath(GPB_BASE_DIR or ".")
    return base


def get_gpb_month_path() -> str:
    """Путь к папке GPB за текущий месяц: YYYY_MM/GPB."""
    base = get_base_path()
    now = datetime.now()
    month_dir = now.strftime("%Y_%m")
    return os.path.join(base, month_dir, "GPB")


def get_yesterday_date_str() -> str:
    """Дата вчера в формате YYYYMMDD."""
    yesterday = datetime.now() - timedelta(days=1)
    return yesterday.strftime("%Y%m%d")


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


def send_outlook_email(subject: str, html_body: str, to_recipients: str) -> bool:
    """Отправляет письмо через Outlook (win32com)."""
    try:
        import win32com.client
    except ImportError:
        print("[!] pywin32 не установлен. Установите: pip install pywin32")
        return False

    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # olMailItem
        mail.Subject = subject
        mail.HTMLBody = html_body
        mail.To = to_recipients
        mail.Send()
        print("[OK] Письмо отправлено")
        return True
    except Exception as e:
        print(f"[!] Ошибка отправки: {e}")
        return False


def main() -> None:
    load_dotenv()

    base_gpb = get_gpb_month_path()
    date_str = get_yesterday_date_str()
    recipient = os.getenv("GPB_VALIDATION_RECIPIENT") or os.getenv("MAIL_ADDRESS", "")

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
        send_outlook_email(subject, html_body, recipient)
    else:
        print("\n[!] GPB_VALIDATION_RECIPIENT или MAIL_ADDRESS не задан в .env - письмо не отправлено")
        print("Тело письма:")
        print(html_body)


if __name__ == "__main__":
    main()
