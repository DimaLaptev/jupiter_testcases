"""
Валидация файлов РСД: счёт депо (depo account) в имени файла в подпапках YYYY_MM/RSD/…
- D / I / R — отдельный справочник счетов (MSG, из Excel: RSD_DEPO_ACCOUNTS_MSG);
  D → D_YYMMDD_<цифры>.MSG и т.д.
- REP — свой справочник (из Excel: RSD_DEPO_ACCOUNTS_REP);
  имена R-01_<YYMMDD>_<цифры> … .xlsx / .xls; дополнительно открывается файл и в ячейке F13
  ищется период «за DD.MM.YYYY», который должен совпадать с календарным «вчера».
Отправка отчёта — как validate_gpb_files.py.
"""

import os
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set

from dotenv import load_dotenv

from config_ews import RSD_VALIDATION_RECIPIENT
from file_handler_config_loader import load_validate_rsd_config

_validate_rsd = load_validate_rsd_config()
RSD_DEPO_ACCOUNTS_MSG: List[str] = _validate_rsd["RSD_DEPO_ACCOUNTS_MSG"]
RSD_DEPO_ACCOUNTS_REP: List[str] = _validate_rsd["RSD_DEPO_ACCOUNTS_REP"]
RSD_SUBFOLDERS: List[str] = _validate_rsd["RSD_SUBFOLDERS"]

# Префикс имени (name prefix) по имени подпапки; REP — отчёты Excel с R-01_
_MSG_SUBFOLDERS = frozenset({"D", "I", "R"})


def _msg_pattern_for_prefix(file_prefix: str, date_yymmdd: str):
    esc_p = re.escape(file_prefix)
    esc_d = re.escape(date_yymmdd)
    return re.compile(
        rf"^{esc_p}_{esc_d}_(?P<depo>\d+)\.msg$",
        re.IGNORECASE,
    )


# R-01_260113_000300044001 ООО….xlsx — блок цифр счёта после второго «_»
_REP_NAME_RE = re.compile(r"^R-01_\d{6}_(?P<depo>\d+)", re.IGNORECASE)
_REP_EXTS = (".xlsx", ".xls")
# Ячейка F13: «за 12.01.2026» (период отчёта для сверки с «вчера»)
_ZA_DDMMYYYY_IN_F13 = re.compile(
    r"за\s*(\d{1,2})\.(\d{1,2})\.(\d{4})",
    re.IGNORECASE,
)


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
    """Дата вчера в формате YYMMDD (как в имени .MSG)."""
    yesterday = datetime.now() - timedelta(days=1)
    return yesterday.strftime("%y%m%d")


def get_yesterday_date() -> date:
    """Календарное «вчера» (для сверки с датой периода в F13 отчёта REP)."""
    return (datetime.now() - timedelta(days=1)).date()


def _parse_za_date_from_f13_raw(raw: object) -> Optional[date]:
    """Из значения ячейки F13 получает дату периода (ожидается «за DD.MM.YYYY» или дата Excel)."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    m = _ZA_DDMMYYYY_IN_F13.search(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def _rep_f13_period_equals_yesterday(file_path: str, yesterday: date) -> bool:
    """
    Открывает книгу REP (.xlsx / .xls), читает активный лист (active sheet), ячейку F13.
    Дата периода в F13 должна совпадать с yesterday.
    """
    ext = os.path.splitext(file_path)[1].lower()
    raw: object
    try:
        if ext == ".xlsx":
            from openpyxl import load_workbook

            wb = load_workbook(filename=file_path, data_only=True)
            try:
                ws = wb.active
                raw = ws["F13"].value
            finally:
                wb.close()
        elif ext == ".xls":
            import xlrd

            book = xlrd.open_workbook(file_path)
            sheet = book.sheet_by_index(0)
            raw = sheet.cell_value(12, 5)
            if isinstance(raw, (int, float)):
                try:
                    t = xlrd.xldate_as_tuple(raw, book.datemode)
                    raw = date(int(t[0]), int(t[1]), int(t[2]))
                except (xlrd.XLDateError, ValueError, TypeError):
                    pass
        else:
            return False
    except OSError:
        return False
    except Exception:
        return False

    period = _parse_za_date_from_f13_raw(raw)
    if period is None and isinstance(raw, date):
        period = raw
    return period == yesterday


def _normalize_depo(depo_raw: str) -> str:
    if not depo_raw.isdigit():
        return ""
    return str(int(depo_raw))


def _expected_accounts_for_subfolder(subfolder: str) -> Set[str]:
    """Ожидаемые счета депо для подпапки: REP — отдельный список, остальное — MSG."""
    if subfolder == "REP":
        return set(RSD_DEPO_ACCOUNTS_REP)
    return set(RSD_DEPO_ACCOUNTS_MSG)


def _ordered_expected_for_subfolder(subfolder: str) -> List[str]:
    """Порядок счетов для отчёта о пропусках (как в Excel)."""
    if subfolder == "REP":
        return list(RSD_DEPO_ACCOUNTS_REP)
    return list(RSD_DEPO_ACCOUNTS_MSG)


def find_depo_accounts_in_folder(
    folder_path: str,
    subfolder: str,
    date_yymmdd: str,
    expected_accounts: Set[str],
) -> Set[str]:
    """Сканирует одну подпапку RSD с учётом типа (MSG vs REP)."""
    found: Set[str] = set()
    if not os.path.isdir(folder_path):
        return found

    if subfolder == "REP":
        yesterday_d = get_yesterday_date()
        for name in os.listdir(folder_path):
            lower = name.lower()
            if not lower.endswith(_REP_EXTS):
                continue
            m = _REP_NAME_RE.match(name)
            if not m:
                continue
            normalized = _normalize_depo(m.group("depo"))
            if not normalized or normalized not in expected_accounts:
                continue
            full_path = os.path.join(folder_path, name)
            if not _rep_f13_period_equals_yesterday(full_path, yesterday_d):
                continue
            found.add(normalized)
        return found

    if subfolder not in _MSG_SUBFOLDERS:
        return found

    pattern = _msg_pattern_for_prefix(subfolder, date_yymmdd)
    for name in os.listdir(folder_path):
        m = pattern.match(name)
        if not m:
            continue
        normalized = _normalize_depo(m.group("depo"))
        if normalized and normalized in expected_accounts:
            found.add(normalized)
    return found


def collect_missing_accounts(base_rsd: str, date_yymmdd: str) -> Dict[str, List[str]]:
    """Недостающие счета депо по каждой подпапке из конфига."""
    result: Dict[str, List[str]] = {sub: [] for sub in RSD_SUBFOLDERS}
    for sub in RSD_SUBFOLDERS:
        expected = _expected_accounts_for_subfolder(sub)
        ordered = _ordered_expected_for_subfolder(sub)
        folder = os.path.join(base_rsd, sub)
        found = find_depo_accounts_in_folder(folder, sub, date_yymmdd, expected)
        missing = [a for a in ordered if a not in found]
        result[sub] = missing
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
    """Отправка через Exchange/EWS (exchangelib), ящик MAIL_1 (см. config_ews)."""
    try:
        from exchangelib import Credentials, Account, DELEGATE, Configuration, Version, Build
        from exchangelib import Message, Mailbox, HTMLBody
        from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
        from config_ews import (
            MAIL_1_ADDRESS,
            MAIL_1_USERNAME,
            MAIL_1_PASSWORD,
            MAIL_SERVER_NAME,
            USE_AUTODISCOVER,
        )
    except ImportError:
        return False

    raw_ssl = os.getenv("VERIFY_SSL")
    verify_ssl = True
    if raw_ssl is not None and raw_ssl != "":
        verify_ssl = raw_ssl.strip().lower() in ("1", "true", "yes", "on")

    if not MAIL_1_ADDRESS or not MAIL_1_USERNAME or not MAIL_1_PASSWORD:
        return False

    try:
        if not verify_ssl:
            BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter
        creds = Credentials(username=MAIL_1_USERNAME, password=MAIL_1_PASSWORD)
        if USE_AUTODISCOVER:
            account = Account(
                primary_smtp_address=MAIL_1_ADDRESS,
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
                primary_smtp_address=MAIL_1_ADDRESS,
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
    recipient = (RSD_VALIDATION_RECIPIENT or "").strip()

    print("=" * 60)
    print("Проверка файлов РСД (счёт депо в имени)")
    print("=" * 60)
    print(f"Папка: {base_rsd}")
    print(f"Подпапки: {', '.join(RSD_SUBFOLDERS)}")
    print(f"Дата в имени .MSG (вчера, YYMMDD): {date_yymmdd}")
    print(f"REP: в F13 дата периода «за DD.MM.YYYY» = вчера ({get_yesterday_date().strftime('%d.%m.%Y')})")
    print("Шаблоны: D/I/R → {папка}_YYMMDD_<счёт>.MSG; REP → R-01_*_<счёт>*.xlsx/.xls")
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
            "найдены файлы во всех настроенных подпапках.</body></html>"
        )
    else:
        html_body = build_email_body(missing_by_folder)

    if recipient:
        send_email(subject, html_body, recipient)
    else:
        print("\n[!] RSD_VALIDATION_RECIPIENT не задан в .env — письмо не отправлено")
        print("Тело письма:")
        print(html_body)


if __name__ == "__main__":
    main()
