"""
Валидация файлов ГПБ: проверка, что коды выписок из справочника встречаются в именах файлов
(D_/I_/R_) в папке GPB_BASE_DIR / DECODE (без даты в имени). Отчёт (email) в Outlook/Exchange.
Если в папке нет файлов (0) — валидация (validation) и письмо (email) не выполняются.
В письме: количества .MSG (MSG) D_/I_/R_, файлов REP*.xls; недостающие коды — отдельно по D, I, R.
"""

import os
from dotenv import load_dotenv
import re
from typing import Dict, List, Set

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


# Сегменты из ровно 5 цифр (5-digit), не часть более длинного числа
_STATEMENT_CODE_TOKEN = re.compile(r"(?<![0-9])(?P<code>\d{5})(?![0-9])")


def _codes_from_filename(name: str, allowed: Set[str]) -> Set[str]:
    """Коды выписки из справочника, найденные в имени файла (file name) как 5-значные (5-digit) числа."""
    return {
        m.group("code")
        for m in _STATEMENT_CODE_TOKEN.finditer(name)
        if m.group("code") in allowed
    }


def collect_missing_codes(check_dir: str) -> Dict[str, List[str]]:
    """
    Недостающие коды отдельно по префиксам (prefix) D_, I_, R_: в каждом соответствующем файле
    ищем все вхождения 5-значных кодов из справочника в имени (дата в имени не требуется).
    """
    found_d: Set[str] = set()
    found_i: Set[str] = set()
    found_r: Set[str] = set()
    allowed = set(GPB_STATEMENT_CODES)
    if os.path.isdir(check_dir):
        for name in os.listdir(check_dir):
            if not os.path.isfile(os.path.join(check_dir, name)):
                continue
            n = name.lower()
            if not (n.startswith("d_") or n.startswith("i_") or n.startswith("r_")):
                continue
            in_name = _codes_from_filename(name, allowed)
            if not in_name:
                continue
            if n.startswith("d_"):
                found_d |= in_name
            elif n.startswith("i_"):
                found_i |= in_name
            elif n.startswith("r_"):
                found_r |= in_name
    return {
        "D": sorted([c for c in GPB_STATEMENT_CODES if c not in found_d]),
        "I": sorted([c for c in GPB_STATEMENT_CODES if c not in found_i]),
        "R": sorted([c for c in GPB_STATEMENT_CODES if c not in found_r]),
    }


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


_GPB_MISS_ORDER = ("D", "I", "R")


def build_email_html(
    missing_by_folder: Dict[str, List[str]],
    d_i_r_count: Dict[str, int],
    rep_xls_count: int,
) -> str:
    """HTML письма: таблица D/I/R/REP*, затем успех или пропуски по кодам по префиксам D_/I_/R_."""
    count_block = _html_gpb_file_counts_table(d_i_r_count, rep_xls_count)
    all_ok = all(not missing_by_folder.get(f) for f in _GPB_MISS_ORDER)
    if all_ok:
        return f"""<html><body>
{count_block}
<p>Проверка ГПБ пройдена успешно: по всем префиксам (prefix) D_/I_/R_ все коды выписок из справочника
встречаются в именах файлов (file names).</p>
</body></html>"""
    rows = []
    for key in _GPB_MISS_ORDER:
        codes = missing_by_folder.get(key, [])
        codes_str = ", ".join(codes) if codes else "—"
        label = f"{key}_*"
        rows.append(f"<tr><td>{label}</td><td>{codes_str}</td></tr>")
    miss_table = f"""<p>Недостающие коды (файлы .msg с префиксом (prefix) D_, I_, R_; код — 5 цифр в имени):</p>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Тип</th><th>Недостающие коды</th></tr>
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
        from config_ews import (
            MAIL_1_ADDRESS,
            MAIL_1_PASSWORD,
            MAIL_1_USERNAME,
            MAIL_SERVER_NAME,
            USE_AUTODISCOVER,
        )
    except ImportError:
        return False

    if not MAIL_1_ADDRESS or not MAIL_1_PASSWORD or not MAIL_1_USERNAME:
        return False

    try:
        creds = Credentials(username=MAIL_1_USERNAME, password=MAIL_1_PASSWORD)
        if USE_AUTODISCOVER:
            account = Account(
                primary_smtp_address=MAIL_1_ADDRESS,
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
                primary_smtp_address=MAIL_1_ADDRESS,
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

    base_gpb = get_validate_gpb_dir()
    recipient = os.getenv("GPB_VALIDATION_RECIPIENT") or os.getenv("MAIL_ADDRESS", "")

    print("=" * 60)
    print("Ежедневная проверка файлов ГПБ")
    print("=" * 60)
    print(f"Папка: {base_gpb} (коды в именах, без фиксированной даты)")
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

    missing_by_folder = collect_missing_codes(base_gpb)

    for key in _GPB_MISS_ORDER:
        missing = missing_by_folder.get(key, [])
        status = "+" if not missing else "-"
        print(
            f"{status} префикс (prefix) {key}_: {len(missing)} недостающих"
            + (f" — {', '.join(missing)}" if missing else "")
        )

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
