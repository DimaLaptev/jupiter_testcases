"""
Валидация файлов ГПБ: проверка наличия файлов с кодами выписки за вчера
в одной папке GPB_BASE_DIR / DECODE (без вложенных D/I/R). Отчёт (email) в Outlook/Exchange.
Если в папке нет файлов (0) — валидация (validation) и письмо (email) не выполняются.
В письме: количества .MSG (MSG) с префиксами (prefix) D_, I_, R_ и файлов REP*.xls.
"""

import os
from dotenv import load_dotenv
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from file_handler_config_loader import load_validate_gpb_config
from config_ews import GPB_BASE_DIR, DECODE

_validate_gpb = load_validate_gpb_config()
GPB_STATEMENT_CODES: List[str] = _validate_gpb["GPB_STATEMENT_CODES"]
# GPB_SUBFOLDERS в Excel остаётся для load_validate_gpb_config; плоский обход — только base/DECODE.


def get_base_path() -> str:
    """Корневая папка (root): GPB_BASE_DIR."""
    return os.path.abspath(GPB_BASE_DIR or ".")


def get_validate_gpb_dir() -> str:
    """Путь (path) к плоской папке проверки: base / DECODE (без YYYY_MM/GPB и без D, I, R)."""
    return os.path.join(get_base_path(), DECODE)


def _count_files_in_dir(dir_path: str) -> int:
    """Число обычных файлов (files); каталога нет — 0. Подпапки (subfolders) не считаем."""
    if not os.path.isdir(dir_path):
        return 0
    n = 0
    for name in os.listdir(dir_path):
        if os.path.isfile(os.path.join(dir_path, name)):
            n += 1
    return n


# Имена вида «REP<что угодно>.xls» (регистр (case) без различия)
_REP_XLS_NAME_RE = re.compile(r"^REP.*\.xls$", re.IGNORECASE)


def count_rep_xls_files(dir_path: str) -> int:
    """Сколько файлов (files) в каталоге с именем REP*.xls (только расширение (extension) .xls)."""
    if not os.path.isdir(dir_path):
        return 0
    n = 0
    for name in os.listdir(dir_path):
        fp = os.path.join(dir_path, name)
        if not os.path.isfile(fp):
            continue
        if _REP_XLS_NAME_RE.match(name):
            n += 1
    return n


# Имена: D_ / I_ / R_ + … + .MSG (как в РСД); R-01 / REP* не сюда
_D_MSG_PREFIX = re.compile(r"^D_", re.IGNORECASE)
_I_MSG_PREFIX = re.compile(r"^I_", re.IGNORECASE)
_R_MSG_PREFIX = re.compile(r"^R_", re.IGNORECASE)


def count_d_i_r_files(dir_path: str) -> Dict[str, int]:
    """Подсчёт только файлов .MSG: имя начинается с D_, I_ или R_ (регистр (case) без различия)."""
    out = {"D": 0, "I": 0, "R": 0}
    if not os.path.isdir(dir_path):
        return out
    for name in os.listdir(dir_path):
        fp = os.path.join(dir_path, name)
        if not os.path.isfile(fp):
            continue
        if not name.lower().endswith(".msg"):
            continue
        if _D_MSG_PREFIX.match(name):
            out["D"] += 1
        elif _I_MSG_PREFIX.match(name):
            out["I"] += 1
        elif _R_MSG_PREFIX.match(name):
            out["R"] += 1
    return out


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


def collect_missing_codes(check_dir: str, date_str: str) -> Dict[str, List[str]]:
    """
    Недостающие коды в одной папке check_dir (без подпапок D/I/R).
    Возвращает одну строку отчёта: { DECODE: [...] }.
    """
    found = find_files_with_codes(check_dir, date_str, GPB_STATEMENT_CODES)
    missing = [c for c in GPB_STATEMENT_CODES if c not in found]
    return {DECODE: sorted(missing)}


def _html_gpb_file_counts_table(
    d_i_r: Dict[str, int],
    rep_xls_count: int,
) -> str:
    """Сводка: .MSG D_/I_/R_ и REP*.xls."""
    rows = [
        f'<tr><td><code>D_*.msg</code></td><td>{d_i_r.get("D", 0)}</td></tr>',
        f'<tr><td><code>I_*.msg</code></td><td>{d_i_r.get("I", 0)}</td></tr>',
        f'<tr><td><code>R_*.msg</code></td><td>{d_i_r.get("R", 0)}</td></tr>',
        f'<tr><td><code>REP*.xls</code></td><td>{rep_xls_count}</td></tr>',
    ]
    return f"""<p>Найдено файлов по шаблону (pattern):</p>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Тип</th><th>Количество</th></tr>
{chr(10).join(rows)}
</table>"""


def build_email_html(
    missing_by_folder: Dict[str, List[str]],
    d_i_r_count: Dict[str, int],
    rep_xls_count: int,
) -> str:
    """HTML письма: таблица D/I/R/REP*, затем успех или пропуски по кодам."""
    count_block = _html_gpb_file_counts_table(d_i_r_count, rep_xls_count)
    all_ok = all(not missing_by_folder.get(f) for f in missing_by_folder)
    if all_ok:
        return f"""<html><body>
{count_block}
<p>Проверка ГПБ пройдена успешно, все коды выписок найдены.</p>
</body></html>"""
    rows = []
    for folder in missing_by_folder:
        codes = missing_by_folder.get(folder, [])
        codes_str = ", ".join(codes) if codes else "—"
        rows.append(f"<tr><td>{folder}</td><td>{codes_str}</td></tr>")
    miss_table = f"""<p>Недостающие коды:</p>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Папка</th><th>Недостающие коды выписки</th></tr>
{chr(10).join(rows)}
</table>"""
    return f"""<html><body>
{count_block}
{miss_table}
</body></html>"""


def _send_via_exchangelib(subject: str, html_body: str, to_recipients: str) -> bool:
    """Отправка через Exchange/EWS (exchangelib)."""
    try:
        from exchangelib import Credentials, Account, DELEGATE, Configuration, Version, Build
        from exchangelib import Message, Mailbox, HTMLBody
        from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
        from config_ews import (
            MAIL_ADDRESS, MAIL_PASSWORD, MAIL_SERVER_NAME,
            USE_AUTODISCOVER, VERIFY_SSL
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
                access_type=DELEGATE
            )
        else:
            config = Configuration(
                server=MAIL_SERVER_NAME,
                credentials=creds,
                version=Version(build=Build(15, 1))
            )
            account = Account(
                primary_smtp_address=MAIL_ADDRESS,
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

    ref = datetime.now() - timedelta(days=1)
    base_gpb = get_validate_gpb_dir()
    date_str = get_yesterday_date_str(ref)
    recipient = os.getenv("GPB_VALIDATION_RECIPIENT") or os.getenv("MAIL_ADDRESS", "")

    print("=" * 60)
    print("Ежедневная проверка файлов ГПБ")
    print("=" * 60)
    print(f"Папка: {base_gpb}")
    print(f"Дата (вчера): {date_str}")
    print("=" * 60)

    file_count = _count_files_in_dir(base_gpb)
    if file_count == 0:
        print(
            "[!] В папке нет файлов (0) — валидация (validation) и отправка письма (email) пропущены."
        )
        return

    d_i_r_count = count_d_i_r_files(base_gpb)
    rep_xls_count = count_rep_xls_files(base_gpb)
    print(
        f"Всего файлов в папке: {file_count}; "
        f".MSG D_/I_/R_: {d_i_r_count['D']}/{d_i_r_count['I']}/{d_i_r_count['R']}; "
        f"REP*.xls={rep_xls_count}"
    )

    missing_by_folder = collect_missing_codes(base_gpb, date_str)

    all_found = all(not missing_by_folder.get(f) for f in missing_by_folder)

    for folder in missing_by_folder:
        missing = missing_by_folder[folder]
        status = "+" if not missing else "-"
        print(f"{status} {folder}: {len(missing)} недостающих" + (f" — {', '.join(missing)}" if missing else ""))

    subject = "Ежедневная проверка файлов ГПБ"
    html_body = build_email_html(missing_by_folder, d_i_r_count, rep_xls_count)

    if recipient:
        send_email(subject, html_body, recipient)
    else:
        print("\n[!] GPB_VALIDATION_RECIPIENT или MAIL_ADDRESS не задан в .env - письмо не отправлено")
        print("Тело письма:")
        print(html_body)


if __name__ == "__main__":
    main()
