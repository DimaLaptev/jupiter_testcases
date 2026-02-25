"""
Выгрузка вложений (attachments) к электронным документам из ЭДО СЭД Регион
за предыдущий день от подразделений-депозитариев.

Алгоритм (algorithm):
  1. Аутентификация (authentication) через SOAP API.
  2. Получение списка контрагентов (contractors) — определение ContractorId
     для каждого депозитария (depositary).
  3. Для каждого контрагента и каждой папки (folder) ЭДО:
     - формирование XML-фильтра (filter) по дате предыдущего дня;
     - получение количества (count) документов;
     - постраничная (paginated) выгрузка списка документов;
     - скачивание тела (body) каждого документа (base64 → файл).
  4. Сохранение файлов в папку <YYYY_MM>/REGION/EDO/.

Запуск (run):
    python region_edo_download.py
"""

import base64
import logging
import os
import sys
from datetime import datetime, timedelta

import pytz

from config_region import (
    REGION_LOGIN,
    REGION_PASSWORD,
    REGION_WSDL_URL,
    EDO_FOLDERS,
    DEPOSITARY_DEPARTMENTS,
)
from region_api import RegionApiClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

PAGE_SIZE = 100


def _yesterday_range() -> tuple[str, str]:
    """Возвращает (date_from, date_to) для предыдущего дня по МСК (UTC+3)."""
    moscow = pytz.timezone('Europe/Moscow')
    today = datetime.now(moscow).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    fmt = '%Y-%m-%d'
    return yesterday.strftime(fmt), yesterday.strftime(fmt)


def _output_dir() -> str:
    """Путь (path) к папке выгрузки: <YYYY_MM>/REGION/EDO."""
    moscow = pytz.timezone('Europe/Moscow')
    month_folder = datetime.now(moscow).strftime('%Y_%m')
    path = os.path.join(month_folder, 'REGION', 'EDO')
    os.makedirs(path, exist_ok=True)
    return path


def _safe_filename(name: str, document_id: str) -> str:
    """Безопасное имя файла (filename): убирает недопустимые символы (characters)."""
    if not name:
        name = f"document_{document_id}"
    for ch in r'<>:"/\|?*':
        name = name.replace(ch, '_')
    return name


def _resolve_contractor_ids(
    api: RegionApiClient,
    department_names: list[str],
) -> dict[str, str]:
    """
    Получает список контрагентов (contractors) через API и находит
    ContractorId для каждого названия депозитария (depositary).
    Возвращает {DisplayName: ContractorId}.
    """
    contractors = api.get_contractors()
    if not contractors:
        logger.error("Не удалось получить список контрагентов (contractors)")
        return {}

    logger.info("Всего контрагентов в системе: %d", len(contractors))

    name_to_id: dict[str, str] = {}
    lower_lookup = {c['DisplayName'].lower(): c for c in contractors}

    for dept in department_names:
        dept_lower = dept.lower()
        matched = lower_lookup.get(dept_lower)
        if matched:
            name_to_id[matched['DisplayName']] = matched['ContractorId']
            logger.info(
                "  Депозитарий '%s' → ContractorId=%s",
                matched['DisplayName'], matched['ContractorId'],
            )
        else:
            for c in contractors:
                if dept_lower in c['DisplayName'].lower():
                    name_to_id[c['DisplayName']] = c['ContractorId']
                    logger.info(
                        "  Депозитарий '%s' (частичное совпадение) → '%s' ContractorId=%s",
                        dept, c['DisplayName'], c['ContractorId'],
                    )
                    break
            else:
                logger.warning("  Депозитарий '%s' — не найден среди контрагентов", dept)

    return name_to_id


def _download_documents_from_folder(
    api: RegionApiClient,
    folder: str,
    contractor_id: str,
    contractor_name: str,
    date_from: str,
    date_to: str,
    output_dir: str,
) -> list[dict]:
    """
    Скачивает все документы (documents) из указанной папки (folder)
    для данного контрагента (contractor) за указанный период (period).
    Возвращает список описаний (descriptions) скачанных файлов.
    """
    filtr = RegionApiClient.build_filter_xml(
        contractor_id=contractor_id,
        date_from=date_from,
        date_to=date_to,
    )

    total = api.get_total_documents_count(folder, filtr)
    if total == 0:
        logger.debug(
            "  [%s] папка '%s' — документов нет", contractor_name, folder,
        )
        return []

    logger.info(
        "  [%s] папка '%s' — найдено документов: %d",
        contractor_name, folder, total,
    )

    downloaded: list[dict] = []
    offset = 0

    while offset < total:
        docs = api.get_document_info_from_folder(
            folder=folder,
            filtr_xml=filtr,
            limit=str(PAGE_SIZE),
            offset=str(offset),
        )
        if not docs:
            break

        for doc_meta in docs:
            doc_id = doc_meta.get('DocumentId', '')
            file_name = doc_meta.get('DocumentFileName', '')
            display_name = doc_meta.get('DocumentDisplayName', file_name)

            logger.info(
                "    Скачивание: id=%s  '%s'", doc_id, display_name,
            )

            body_b64 = api.get_document_body(doc_id)
            if not body_b64:
                doc_full = api.get_document_by_id(doc_id)
                if doc_full:
                    body_b64 = doc_full.get('body_base64')

            if not body_b64:
                logger.warning(
                    "    Тело документа (body) id=%s пустое — пропуск", doc_id,
                )
                continue

            safe_name = _safe_filename(file_name, doc_id)
            filepath = os.path.join(output_dir, safe_name)

            if os.path.exists(filepath):
                name_part, ext = os.path.splitext(safe_name)
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                safe_name = f"{name_part}_{ts}{ext}"
                filepath = os.path.join(output_dir, safe_name)

            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(body_b64))

            size = os.path.getsize(filepath)
            logger.info("    Сохранён: %s (%d байт)", filepath, size)

            downloaded.append({
                'document_id': doc_id,
                'filename': safe_name,
                'filepath': filepath,
                'size': size,
                'contractor': contractor_name,
                'folder': folder,
                'display_name': display_name,
                'document_date': doc_meta.get('DocumentDate', ''),
            })

        offset += PAGE_SIZE

    return downloaded


def main():
    logger.info("=" * 70)
    logger.info("Выгрузка вложений ЭДО Регион за предыдущий день")
    logger.info("=" * 70)

    if not REGION_LOGIN or not REGION_PASSWORD:
        logger.error(
            "Не заданы REGION_LOGIN / REGION_PASSWORD в .env файле. "
            "Скопируйте env_template.txt → .env и заполните значения."
        )
        sys.exit(1)

    date_from, date_to = _yesterday_range()
    logger.info("Период (period): %s — %s", date_from, date_to)

    output_dir = _output_dir()
    logger.info("Папка выгрузки (output): %s", os.path.abspath(output_dir))

    api = RegionApiClient(
        wsdl_url=REGION_WSDL_URL,
        login=REGION_LOGIN,
        password=REGION_PASSWORD,
    )

    user_id = api.authenticate()
    if not user_id:
        logger.error("Аутентификация (authentication) не пройдена — выход.")
        sys.exit(1)

    contractor_map = _resolve_contractor_ids(api, DEPOSITARY_DEPARTMENTS)
    if not contractor_map:
        logger.error("Ни один депозитарий (depositary) не найден — выход.")
        sys.exit(1)

    logger.info(
        "Найдено депозитариев (depositaries): %d из %d",
        len(contractor_map), len(DEPOSITARY_DEPARTMENTS),
    )

    all_downloaded: list[dict] = []

    for contractor_name, contractor_id in contractor_map.items():
        logger.info("-" * 60)
        logger.info("Контрагент (contractor): %s (id=%s)", contractor_name, contractor_id)

        for folder in EDO_FOLDERS:
            downloaded = _download_documents_from_folder(
                api=api,
                folder=folder,
                contractor_id=contractor_id,
                contractor_name=contractor_name,
                date_from=date_from,
                date_to=date_to,
                output_dir=output_dir,
            )
            all_downloaded.extend(downloaded)

    logger.info("=" * 70)
    logger.info("ИТОГО (total):")
    logger.info("  Файлов скачано (downloaded): %d", len(all_downloaded))
    if all_downloaded:
        total_size = sum(d['size'] for d in all_downloaded)
        logger.info("  Общий размер (total size): %d байт", total_size)
        logger.info("  Папка (folder): %s", os.path.abspath(output_dir))

        logger.info("-" * 60)
        for i, d in enumerate(all_downloaded, 1):
            logger.info(
                "  %3d. [%s] %s  (%d байт)",
                i, d['contractor'], d['filename'], d['size'],
            )
    else:
        logger.info("  Вложений (attachments) за %s не найдено.", date_from)

    logger.info("=" * 70)
    logger.info("Готово (done).")


if __name__ == '__main__':
    main()
