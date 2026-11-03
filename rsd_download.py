"""
Выгрузка файлов RSD с /mnt/share_rsd в REPORS_DEPO_DIRECTORY.

По рабочим дням копируются файлы с датой изменения предыдущего рабочего дня
из DOM/INBOX и IA/INBOX в <YYYY_MM>/RSD/EDO. Архивы не распаковываются.
В первую рабочую дату месяца месяц назначения берётся из первой даты
YYMMDD или YYYYMMDD в имени файла (у zip — внутри архива, не из его имени).
Нет такой даты — файл остаётся в текущем месяце, на почту уходит письмо.

Запуск: python rsd_download.py
"""

from __future__ import annotations

import io
import logging
import re
import shutil
import zipfile
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Callable, Optional

import pytz

from config_ews import GPB_VALIDATION_RECIPIENT, REPORS_DEPO_DIRECTORY
from vtb_download import (
    is_first_working_day_of_month,
    is_immediately_previous_month,
    month_dir_name,
    moscow_today,
    previous_month,
    previous_working_day,
)

logger = logging.getLogger(__name__)

RSD_SHARE_ROOT = "/mnt/share_rsd"
_INBOXES = ("DOM/INBOX", "IA/INBOX")
_MOSCOW = pytz.timezone("Europe/Moscow")
_DATE_TOKEN = re.compile(r"(?<!\d)(\d{8}|\d{6})(?!\d)")
_MAX_ZIP_DEPTH = 5
_MAX_NESTED_ZIP_BYTES = 512 * 1024 * 1024

SendMail = Callable[[str, str, str], object]


def mtime_day(path: Path) -> date:
    """Дата изменения файла по Москве."""
    moment = datetime.fromtimestamp(path.stat().st_mtime, _MOSCOW)
    return moment.date()


def parse_name_token(token: str) -> Optional[date]:
    """YYYYMMDD или YYMMDD. Неразборчивый набор цифр — None."""
    fmt = "%Y%m%d" if len(token) == 8 else "%y%m%d"
    try:
        return datetime.strptime(token, fmt).date()
    except ValueError:
        return None


def first_date_in_name(name: str) -> Optional[date]:
    """Первая подходящая дата в имени. Более длинный токен не режется на короткий."""
    for match in _DATE_TOKEN.finditer(Path(name).name):
        found = parse_name_token(match.group(1))
        if found is not None:
            return found
    return None


def _first_date_in_zipfile(bundle: zipfile.ZipFile, depth: int) -> Optional[date]:
    infos = [info for info in bundle.infolist() if Path(info.filename).name]
    for info in infos:
        base = Path(info.filename).name
        if info.is_dir() or base.lower().endswith(".zip"):
            continue
        found = first_date_in_name(base)
        if found is not None:
            return found
    if depth >= _MAX_ZIP_DEPTH:
        return None
    for info in infos:
        base = Path(info.filename).name
        if info.is_dir() or not base.lower().endswith(".zip"):
            continue
        if info.file_size > _MAX_NESTED_ZIP_BYTES:
            logger.warning("RSD: вложенный архив слишком большой, пропущен: %s", base)
            continue
        try:
            with bundle.open(info, "r") as raw:
                payload = raw.read()
            with zipfile.ZipFile(io.BytesIO(payload)) as nested:
                found = _first_date_in_zipfile(nested, depth + 1)
        except zipfile.BadZipFile:
            logger.warning("RSD: не читается вложенный архив %s", base)
            continue
        if found is not None:
            return found
    for info in infos:
        if not info.is_dir():
            continue
        found = first_date_in_name(Path(info.filename).name)
        if found is not None:
            return found
    return None


def first_date_in_zip(path: Path) -> Optional[date]:
    """Первая дата во вложенных файлах. Имя самого архива не учитывается."""
    try:
        with zipfile.ZipFile(path) as bundle:
            return _first_date_in_zipfile(bundle, 1)
    except zipfile.BadZipFile:
        logger.warning("RSD: не читается архив %s", path.name)
        return None


def route_date(path: Path) -> Optional[date]:
    """Дата для раскладки: у zip из содержимого, у остальных из своего имени."""
    if path.suffix.lower() == ".zip":
        return first_date_in_zip(path)
    return first_date_in_name(path.name)


def _copy_file(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / src.name
    if target.exists():
        logger.warning("RSD: перезапись %s", target)
    shutil.copy2(src, target)
    return target


def _download_inbox(
    share_root: Path,
    reports_root: Path,
    relative_inbox: str,
    source_day: date,
    boundary: bool,
) -> tuple[Optional[str], list[str]]:
    """
    Скопировать файлы одного INBOX.

    Возвращает текст отсутствующего каталога (или None) и имена без даты.
    """
    inbox = share_root.joinpath(*relative_inbox.split("/"))
    if not inbox.is_dir():
        missing = str(inbox)
        logger.warning("RSD: нет каталога %s", missing)
        return missing, []

    chosen = sorted(
        path for path in inbox.iterdir() if path.is_file() and mtime_day(path) == source_day
    )
    logger.info("RSD: %s — файлов с датой изменения %s: %d", inbox, source_day.isoformat(), len(chosen))
    undated: list[str] = []
    current_month = month_dir_name(source_day)
    for src in chosen:
        dest_month = current_month
        if boundary:
            found = route_date(src)
            if found is None:
                undated.append(src.name)
                logger.warning("RSD: %s — нет даты в имени, остаётся в %s", src.name, current_month)
            elif is_immediately_previous_month(found, source_day):
                dest_month = month_dir_name(previous_month(source_day))
                logger.info("RSD: %s дата %s → месяц %s", src.name, found.isoformat(), dest_month)
            else:
                logger.info("RSD: %s дата %s остаётся в %s", src.name, found.isoformat(), current_month)
        copied = _copy_file(src, reports_root / dest_month / "RSD" / "EDO")
        logger.info("RSD: %s → %s", src, copied)
    return None, undated


def _notify(items: list[str], source_day: date, recipient: str, send_mail: SendMail) -> None:
    subject = f"RSD: выгрузка за {source_day.isoformat()}"
    rows = "".join(f"<li>{escape(item)}</li>" for item in items)
    body = (
        "<html><body>"
        f"<p>Выгрузка RSD за {source_day.isoformat()}. "
        "Файл без даты в имени оставлен в папке текущего месяца.</p>"
        f"<ul>{rows}</ul>"
        "</body></html>"
    )
    if not recipient:
        logger.warning(
            "RSD: GPB_VALIDATION_RECIPIENT не задан — письмо не отправлено. %s",
            "; ".join(items),
        )
        return
    send_mail(subject, body, recipient)


def run_rsd_download(
    today: Optional[date] = None,
    share_root: Optional[Path] = None,
    reports_root: Optional[Path] = None,
    is_non_working: Optional[Callable[[date], bool]] = None,
    recipient: Optional[str] = None,
    send_mail: Optional[SendMail] = None,
) -> None:
    """Скопировать файлы предыдущего рабочего дня. В нерабочий день сразу выходит."""
    if today is None:
        today = moscow_today()
    if is_non_working is None:
        from get_month_name_dir import _is_non_working_day

        is_non_working = _is_non_working_day
    if is_non_working(today):
        logger.info("RSD: %s нерабочий день — выгрузка пропущена", today.isoformat())
        return

    source_day = previous_working_day(today, is_non_working)
    boundary = is_first_working_day_of_month(source_day, is_non_working)
    logger.info(
        "RSD: сегодня %s, дата изменения %s, стык месяца=%s",
        today.isoformat(),
        source_day.isoformat(),
        boundary,
    )

    reports = reports_root
    if reports is None:
        if not REPORS_DEPO_DIRECTORY:
            logger.error("RSD: REPORS_DEPO_DIRECTORY не задан")
            return
        reports = Path(REPORS_DEPO_DIRECTORY)
    share = share_root if share_root is not None else Path(RSD_SHARE_ROOT)

    notes: list[str] = []
    for relative in _INBOXES:
        try:
            absent, undated = _download_inbox(share, reports, relative, source_day, boundary)
        except Exception:
            logger.exception("RSD: ошибка каталога %s", relative)
            continue
        if absent:
            notes.append(f"нет каталога: {absent}")
        notes.extend(f"нет даты в имени: {name}" for name in undated)

    if not notes:
        return
    mail = send_mail
    if mail is None:
        from validate_gpb_files import send_email

        mail = send_email
    mail_to = (GPB_VALIDATION_RECIPIENT or "").strip() if recipient is None else recipient.strip()
    _notify(notes, source_day, mail_to, mail)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_rsd_download()


if __name__ == "__main__":
    main()
