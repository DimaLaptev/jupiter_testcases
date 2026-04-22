"""
Валидация файлов РСД: счёт депо (depo account) в имени; все файлы ищутся в YYYY_MM/RSD/EDO
(папка (folder) EDO на одном уровне с D, I, R, REP).
- D / I / R — отдельный справочник (MSG, RSD_DEPO_ACCOUNTS_MSG); шаблоны D_…/I_…/R_… .MSG.
- REP — RSD_DEPO_ACCOUNTS_REP; шаблон R-01_… .xlsx / .xls
Отправка отчёта — как validate_gpb_files.py.
Если в EDO нет файлов (0) — валидация (validation) и письмо (email) не выполняются.
"""

import os
import re
from datetime import datetime
from typing import Dict, List, Set, Tuple

from dotenv import load_dotenv

from file_handler_config_loader import load_validate_rsd_config

_validate_rsd = load_validate_rsd_config()
RSD_DEPO_ACCOUNTS_MSG: List[str] = _validate_rsd["RSD_DEPO_ACCOUNTS_MSG"]
RSD_DEPO_ACCOUNTS_REP: List[str] = _validate_rsd["RSD_DEPO_ACCOUNTS_REP"]
RSD_SUBFOLDERS: List[str] = _validate_rsd["RSD_SUBFOLDERS"]

# Логические группы (логика отчёта) из RSD_SUBFOLDERS; физически сканируется только EDO (см. ниже).
# Префикс имени (name prefix) для MSG; REP — отчёты Excel с R-01_
_MSG_SUBFOLDERS = frozenset({"D", "I", "R"})
# Имя каталога (folder) со всеми файлами: …/RSD/EDO (сосед D, I, R, REP).
RSD_FILES_SCAN_DIR = "EDO"


def _msg_pattern_for_prefix(file_prefix: str):
    """Имя: {prefix}_YYMMDD_<счёт>.MSG — YYMMDD не проверяется (любые 6 цифр)."""
    esc_p = re.escape(file_prefix)
    return re.compile(
        rf"^{esc_p}_\d{{6}}_(?P<depo>\d+)\.msg$",
        re.IGNORECASE,
    )


# R-01_260113_000300044001 ООО….xlsx — блок цифр счёта после второго «_»
_REP_NAME_RE = re.compile(r"^R-01_\d{6}_(?P<depo>\d+)", re.IGNORECASE)
_REP_EXTS = (".xlsx", ".xls")


def get_base_path() -> str:
    """Корневая папка (текущий месяц, напр. 2026_04)."""
    from config_ews import GPB_BASE_DIR

    return os.path.abspath(GPB_BASE_DIR or ".")


def get_rsd_month_path() -> str:
    """Путь к папке RSD за текущий месяц: YYYY_MM/RSD."""
    base = get_base_path()
    month_dir = datetime.now().strftime("%Y_%m")
    return os.path.join(base, month_dir, "RSD")


def count_files_by_rsd_type(edo_path: str) -> Dict[str, int]:
    """
    Сколько файлов (files) в EDO соответствуют шаблону типа (без фильтра по справочнику счетов).
    Ключи: D, I, R, R-01.
    """
    out = {"D": 0, "I": 0, "R": 0, "R-01": 0}
    if not os.path.isdir(edo_path):
        return out
    p_d = _msg_pattern_for_prefix("D")
    p_i = _msg_pattern_for_prefix("I")
    p_r = _msg_pattern_for_prefix("R")
    for name in os.listdir(edo_path):
        fp = os.path.join(edo_path, name)
        if not os.path.isfile(fp):
            continue
        lower = name.lower()
        if lower.endswith(_REP_EXTS) and _REP_NAME_RE.match(name):
            out["R-01"] += 1
            continue
        if p_d.match(name):
            out["D"] += 1
        elif p_i.match(name):
            out["I"] += 1
        elif p_r.match(name):
            out["R"] += 1
    return out


def _count_files_in_dir(dir_path: str) -> int:
    """Число обычных файлов (files) в каталоге; нет каталога — 0. Подпапки (subfolders) не считаем."""
    if not os.path.isdir(dir_path):
        return 0
    n = 0
    for name in os.listdir(dir_path):
        if os.path.isfile(os.path.join(dir_path, name)):
            n += 1
    return n


def _normalize_depo(depo_raw: str) -> str:
    if not depo_raw.isdigit():
        return ""
    return str(int(depo_raw))


def _expected_accounts_for_subfolder(subfolder: str) -> Set[str]:
    """Ожидаемые счета для логической группы (D/I/R/REP); REP — отдельный список, иначе MSG."""
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
    logical_type: str,
    expected_accounts: Set[str],
) -> Set[str]:
    """Сканирует folder_path с учётом логического типа: D/I/R/REP (шаблоны имён, не путь)."""
    found: Set[str] = set()
    if not os.path.isdir(folder_path):
        return found

    if logical_type == "REP":
        for name in os.listdir(folder_path):
            lower = name.lower()
            if not lower.endswith(_REP_EXTS):
                continue
            m = _REP_NAME_RE.match(name)
            if not m:
                continue
            normalized = _normalize_depo(m.group("depo"))
            if normalized and normalized in expected_accounts:
                found.add(normalized)
        return found

    if logical_type not in _MSG_SUBFOLDERS:
        return found

    pattern = _msg_pattern_for_prefix(logical_type)
    for name in os.listdir(folder_path):
        m = pattern.match(name)
        if not m:
            continue
        normalized = _normalize_depo(m.group("depo"))
        if normalized and normalized in expected_accounts:
            found.add(normalized)
    return found


def collect_missing_accounts(base_rsd: str) -> Dict[str, List[str]]:
    """Недостающие счета: для каждой логической группы из RSD_SUBFOLDERS — файлы в …/RSD/EDO."""
    edo_path = os.path.join(base_rsd, RSD_FILES_SCAN_DIR)
    result: Dict[str, List[str]] = {sub: [] for sub in RSD_SUBFOLDERS}
    for sub in RSD_SUBFOLDERS:
        expected = _expected_accounts_for_subfolder(sub)
        ordered = _ordered_expected_for_subfolder(sub)
        found = find_depo_accounts_in_folder(edo_path, sub, expected)
        missing = [a for a in ordered if a not in found]
        result[sub] = missing
    return result


def _html_file_counts_table(file_counts: Dict[str, int]) -> str:
    """Сводка по количеству (count) найденных файлов по шаблону."""
    order: List[Tuple[str, str]] = [
        ("D", "D"),
        ("I", "I"),
        ("R", "R"),
        ("R-01", "R-01"),
    ]
    rows = [f"<tr><td>{label}</td><td>{file_counts.get(key, 0)}</td></tr>" for key, label in order]
    return f"""<p>Найдено файлов по шаблону (pattern):</p>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Тип</th><th>Количество</th></tr>
{chr(10).join(rows)}
</table>"""


def build_email_html(
    file_counts: Dict[str, int],
    missing_by_folder: Dict[str, List[str]],
) -> str:
    """HTML письма: сводка по файлам, затем либо успех, либо таблица пропусков."""
    count_block = _html_file_counts_table(file_counts)
    if all(not missing_by_folder.get(f) for f in RSD_SUBFOLDERS):
        return f"""<html><body>
{count_block}
<p>Проверка РСД пройдена успешно: по всем счетам депо из справочника в папке EDO
найдены ожидаемые файлы.</p>
</body></html>"""
    rows = []
    for folder in RSD_SUBFOLDERS:
        accs = missing_by_folder.get(folder, [])
        accs_str = ", ".join(accs) if accs else "—"
        rows.append(f"<tr><td>{folder}</td><td>{accs_str}</td></tr>")
    miss_table = f"""<p>Недостающие счета:</p>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Группа (шаблон)</th><th>Недостающие счета депо</th></tr>
{chr(10).join(rows)}
</table>"""
    return f"""<html><body>
{count_block}
{miss_table}
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
    recipient = os.getenv("RSD_VALIDATION_RECIPIENT") or os.getenv("MAIL_ADDRESS", "")

    print("=" * 60)
    print("Проверка файлов РСД (счёт депо в имени)")
    print("=" * 60)
    edo = os.path.join(base_rsd, RSD_FILES_SCAN_DIR)
    print(f"Корень RSD: {base_rsd}")
    print(f"Сканирование: {edo} (группы по шаблону: {', '.join(RSD_SUBFOLDERS)})")
    print("Шаблоны: D/I/R → {префикс}_YYMMDD_<счёт>.MSG; REP → R-01_*_<счёт>*.xlsx")
    print("=" * 60)

    file_count = _count_files_in_dir(edo)
    if file_count == 0:
        print(
            f"[!] В папке {RSD_FILES_SCAN_DIR} нет файлов (0) — валидация (validation) "
            "и отправка письма (email) пропущены."
        )
        return

    file_counts = count_files_by_rsd_type(edo)
    missing_by_folder = collect_missing_accounts(base_rsd)

    print(
        "Файлов по шаблону: "
        f"D={file_counts['D']}, I={file_counts['I']}, R={file_counts['R']}, R-01={file_counts['R-01']}"
    )
    for folder in RSD_SUBFOLDERS:
        missing = missing_by_folder[folder]
        status = "+" if not missing else "-"
        print(
            f"{status} {folder}: {len(missing)} недостающих"
            + (f" — {', '.join(missing)}" if missing else "")
        )

    subject = "Проверка файлов РСД (счета депо)"
    html_body = build_email_html(file_counts, missing_by_folder)

    if recipient:
        send_email(subject, html_body, recipient)
    else:
        print("\n[!] RSD_VALIDATION_RECIPIENT или MAIL_ADDRESS не задан в .env — письмо не отправлено")
        print("Тело письма:")
        print(html_body)


if __name__ == "__main__":
    main()
