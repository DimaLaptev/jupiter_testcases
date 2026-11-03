"""
Выгрузка файлов VTB с /mnt/share_vtb в REPORS_DEPO_DIRECTORY.

По рабочим дням берётся папка предыдущего рабочего дня (календарь depo_validation):
F750 → <YYYY_MM>/VTBSD/SPR, F752 → <YYYY_MM>/VTBSD/REP.
Для первой рабочей папки месяца дата в XML может переложить комплект в предыдущий месяц.
Скопированные zip распаковываются, файлам даётся имя архива, архив удаляется.

Запуск: python vtb_download.py
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Callable, Optional
from xml.etree import ElementTree

import pytz

from config_ews import GPB_VALIDATION_RECIPIENT, REPORS_DEPO_DIRECTORY

logger = logging.getLogger(__name__)

VTB_SHARE_ROOT = "/mnt/share_vtb"
_MOSCOW = pytz.timezone("Europe/Moscow")

# Код шары → подпапка VTBSD.
_BRANCHES = (
    ("F750", "SPR"),
    ("F752", "REP"),
)

SendMail = Callable[[str, str, str], object]


def moscow_today() -> date:
    """Сегодня по Москве."""
    return datetime.now(_MOSCOW).date()


def previous_working_day(today: date, is_non_working: Callable[[date], bool]) -> date:
    """Ближайший рабочий день строго раньше today."""
    current = today - timedelta(days=1)
    steps = 0
    while is_non_working(current):
        current -= timedelta(days=1)
        steps += 1
        if steps > 800:
            raise RuntimeError(
                f"Не удалось найти рабочий день перед {today.isoformat()}: проверьте календарь."
            )
    return current


def day_folder_names(day: date) -> list[str]:
    """Имена дневной папки: сначала с нулями, затем без (2026-11-01 и 2026-11-1)."""
    padded = day.strftime("%Y-%m-%d")
    plain = f"{day.year}-{day.month}-{day.day}"
    if plain == padded:
        return [padded]
    return [padded, plain]


def find_day_folder(parent: Path, day: date) -> Optional[Path]:
    """Папка дня внутри F750/F752. Нет каталога — None."""
    if not parent.is_dir():
        return None
    for name in day_folder_names(day):
        candidate = parent / name
        if candidate.is_dir():
            return candidate
    return None


def describe_missing_folder(parent: Path, day: date) -> str:
    """Текст для письма: какие имена папки искали."""
    names = day_folder_names(day)
    first = str(parent / names[0])
    if len(names) == 1:
        return first
    return f"{first} или {parent / names[1]}"


def month_dir_name(day: date) -> str:
    """Имя месячной папки reports_depo: 2026_10."""
    return f"{day.year}_{day.month:02d}"


def previous_month(day: date) -> date:
    """Первое число месяца, предшествующего day."""
    if day.month == 1:
        return date(day.year - 1, 12, 1)
    return date(day.year, day.month - 1, 1)


def is_immediately_previous_month(value: date, source_day: date) -> bool:
    """value лежит в календарном месяце сразу перед месяцем source_day."""
    prev = previous_month(source_day)
    return value.year == prev.year and value.month == prev.month


def is_first_working_day_of_month(day: date, is_non_working: Callable[[date], bool]) -> bool:
    """В этом месяце нет рабочего дня раньше day. 1-е число, если оно рабочее, тоже подходит."""
    current = date(day.year, day.month, 1)
    while current < day:
        if not is_non_working(current):
            return False
        current += timedelta(days=1)
    return True


def parse_date(value: str) -> Optional[date]:
    """YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS и DD.MM.YYYY."""
    text = value.strip()
    if not text:
        return None
    head = text.split("T", 1)[0].split(" ", 1)[0].rstrip("Z")
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def _local_name(tag: str) -> str:
    if not tag:
        return ""
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag


def _element_text(node: ElementTree.Element) -> str:
    return "".join(node.itertext()).strip()


def _field_in(block: ElementTree.Element, name: str) -> str:
    """Непустое поле внутри блока: потомок или атрибут, без учёта пространства имён."""
    for node in block.iter():
        if node is block:
            continue
        if _local_name(node.tag) == name:
            value = _element_text(node)
            if value:
                return value
    for key, raw in block.attrib.items():
        local = key.rsplit("}", 1)[-1]
        if local == name and (raw or "").strip():
            return raw.strip()
    return ""


def _first_field(root: ElementTree.Element, name: str) -> str:
    """Первое непустое поле name в порядке документа."""
    for node in root.iter():
        if _local_name(node.tag) != name:
            continue
        value = _element_text(node)
        if value:
            return value
    return ""


def resolve_report_date(root: ElementTree.Element) -> tuple[Optional[date], Optional[str]]:
    """
    Дата отчёта и предупреждение.

    Сначала OverlayDepositaryDate последнего ClientCashDataTable, где поле непустое.
    Затем ExecutionDate, затем OrderDate.
    Предупреждение — если значение есть, но не разбирается как дата.
    (None, None) — полей нет.
    """
    raw = ""
    source = ""
    for node in root.iter():
        if _local_name(node.tag) != "ClientCashDataTable":
            continue
        value = _field_in(node, "OverlayDepositaryDate")
        if value:
            raw = value
            source = "OverlayDepositaryDate"
    if not raw:
        raw = _first_field(root, "ExecutionDate")
        source = "ExecutionDate" if raw else ""
    if not raw:
        raw = _first_field(root, "OrderDate")
        source = "OrderDate" if raw else ""
    if not raw:
        return None, None
    parsed = parse_date(raw)
    if parsed is None:
        return None, f"{source}={raw!r} не разобрана как дата"
    return parsed, None


def xml_report_date(path: Path) -> tuple[Optional[date], Optional[str]]:
    """Дата из XML-файла. Битый XML — предупреждение, без даты."""
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        return None, f"XML не разобран: {exc}"
    return resolve_report_date(root)


def names_for_extensions(stem: str, extensions: list[str]) -> list[str]:
    """Имя архива + исходное расширение. Повтор расширения получает суффикс _2, _3, …"""
    seen: dict[str, int] = {}
    names: list[str] = []
    for ext in extensions:
        key = ext.lower()
        seen[key] = seen.get(key, 0) + 1
        count = seen[key]
        if count == 1:
            names.append(f"{stem}{ext}")
        else:
            names.append(f"{stem}_{count}{ext}")
    return names


def unpack_archive(archive: Path) -> None:
    """
    Распаковать zip в его каталог, выровнять вложенные пути.
    После успеха архив удаляется. При ошибке архив остаётся.
    """
    directory = archive.parent
    stem = archive.stem
    with zipfile.ZipFile(archive) as bundle:
        members = []
        for info in bundle.infolist():
            if info.is_dir():
                continue
            base = Path(info.filename).name
            if not base:
                continue
            members.append(info)
        extensions = [Path(Path(info.filename).name).suffix for info in members]
        targets = names_for_extensions(stem, extensions)
        for info, name in zip(members, targets):
            target = directory / name
            with bundle.open(info, "r") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            logger.info("VTB: %s → %s", archive.name, target.name)
    archive.unlink()
    logger.info("VTB: архив удалён %s", archive.name)


def _copy_file(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / src.name
    shutil.copy2(src, target)
    return target


def _destination_month(
    group: list[Path],
    source_day: date,
    is_non_working: Callable[[date], bool],
) -> str:
    """Месяц назначения. В первую рабочую папку месяца смотрит XML."""
    dest_month = month_dir_name(source_day)
    if not is_first_working_day_of_month(source_day, is_non_working):
        return dest_month
    xmls = [path for path in group if path.suffix.lower() == ".xml"]
    if not xmls:
        return dest_month
    xml_path = xmls[0]
    found, warning = xml_report_date(xml_path)
    if warning:
        logger.warning("VTB: %s — %s", xml_path.name, warning)
        return dest_month
    if found is None:
        logger.warning(
            "VTB: %s — нет OverlayDepositaryDate, ExecutionDate и OrderDate",
            xml_path.name,
        )
        return dest_month
    if is_immediately_previous_month(found, source_day):
        dest_month = month_dir_name(previous_month(source_day))
        logger.info(
            "VTB: %s дата %s → месяц %s",
            xml_path.name,
            found.isoformat(),
            dest_month,
        )
        return dest_month
    logger.info(
        "VTB: %s дата %s остаётся в %s",
        xml_path.name,
        found.isoformat(),
        dest_month,
    )
    return dest_month


def _download_branch(
    share_root: Path,
    reports_root: Path,
    code: str,
    subfolder: str,
    source_day: date,
    is_non_working: Callable[[date], bool],
) -> tuple[Optional[str], list[Path]]:
    """
    Скопировать одну ветку F750/F752.

    Возвращает описание отсутствующей папки (или None) и пути скопированных zip.
    """
    day_dir = find_day_folder(share_root / code, source_day)
    if day_dir is None:
        missing = describe_missing_folder(share_root / code, source_day)
        logger.warning("VTB: нет папки %s", missing)
        return missing, []

    files = sorted(path for path in day_dir.iterdir() if path.is_file())
    logger.info("VTB: %s — файлов %d", day_dir, len(files))
    groups: dict[str, list[Path]] = {}
    for path in files:
        groups.setdefault(path.stem, []).append(path)

    copied_zips: list[Path] = []
    for group in groups.values():
        dest_month = _destination_month(group, source_day, is_non_working)
        dest_dir = reports_root / dest_month / "VTBSD" / subfolder
        for src in group:
            copied = _copy_file(src, dest_dir)
            logger.info("VTB: %s → %s", src, copied)
            if copied.suffix.lower() == ".zip":
                copied_zips.append(copied)
    return None, copied_zips


def _notify_missing(items: list[str], source_day: date, recipient: str, send_mail: SendMail) -> None:
    subject = f"VTB: нет папки за {source_day.isoformat()}"
    rows = "".join(f"<li>{escape(item)}</li>" for item in items)
    body = (
        "<html><body>"
        f"<p>Не найдена папка VTB за {source_day.isoformat()}.</p>"
        f"<ul>{rows}</ul>"
        "</body></html>"
    )
    if not recipient:
        logger.warning(
            "VTB: GPB_VALIDATION_RECIPIENT не задан — письмо не отправлено. %s",
            "; ".join(items),
        )
        return
    send_mail(subject, body, recipient)


def run_vtb_download(
    today: Optional[date] = None,
    share_root: Optional[Path] = None,
    reports_root: Optional[Path] = None,
    is_non_working: Optional[Callable[[date], bool]] = None,
    recipient: Optional[str] = None,
    send_mail: Optional[SendMail] = None,
) -> None:
    """Скачать папку предыдущего рабочего дня. В нерабочий день сразу выходит."""
    if today is None:
        today = moscow_today()
    if is_non_working is None:
        from get_month_name_dir import _is_non_working_day

        is_non_working = _is_non_working_day
    if is_non_working(today):
        logger.info("VTB: %s нерабочий день — выгрузка пропущена", today.isoformat())
        return

    source_day = previous_working_day(today, is_non_working)
    logger.info(
        "VTB: сегодня %s, папка источника %s",
        today.isoformat(),
        source_day.isoformat(),
    )

    reports = reports_root
    if reports is None:
        if not REPORS_DEPO_DIRECTORY:
            logger.error("VTB: REPORS_DEPO_DIRECTORY не задан")
            return
        reports = Path(REPORS_DEPO_DIRECTORY)
    share = share_root if share_root is not None else Path(VTB_SHARE_ROOT)

    missing: list[str] = []
    archives: list[Path] = []
    for code, subfolder in _BRANCHES:
        try:
            absent, zips = _download_branch(
                share, reports, code, subfolder, source_day, is_non_working
            )
        except Exception:
            logger.exception("VTB: ошибка ветки %s", code)
            continue
        if absent:
            missing.append(absent)
        archives.extend(zips)

    for archive in archives:
        try:
            unpack_archive(archive)
        except Exception:
            logger.exception("VTB: не распакован %s", archive)

    if not missing:
        return
    mail = send_mail
    if mail is None:
        from validate_gpb_files import send_email

        mail = send_email
    mail_to = (GPB_VALIDATION_RECIPIENT or "").strip() if recipient is None else recipient.strip()
    _notify_missing(missing, source_day, mail_to, mail)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_vtb_download()


if __name__ == "__main__":
    main()
