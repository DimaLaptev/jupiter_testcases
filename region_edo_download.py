"""
Выгрузка вложений (attachments) к электронным документам из ЭДО СЭД Регион
за предыдущий день по МСК (или за период REGION_EDO_DOCUMENT_DATE_FROM/TO в .env)
по всем логинам из REGION_LOGIN (через запятую в .env) и контрагентам (contractors), возвращаемым API.

Алгоритм (algorithm):
  1. Аутентификация (authentication) через SOAP API.
  2. Получение списка контрагентов (contractors) через getContractors —
     обработка каждого уникального ContractorId.
  3. Для каждого контрагента:
     - папки ЭДО (ReadyToRegister, InWork, Archive): getDocumentInfoFromFolderByParams;
     - архив: getDocumentInfoByParams.
     Для каждого документа — скачивание тела и вложений (base64 → файл).
  4. Сохранение файлов в папку <YYYY_MM>/REGION/EDO/.

Запуск (run):
    python region_edo_download.py
"""

import base64
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Tuple

import pytz

from config_region import (
    REGION_LOGINS,
    REGION_PASSWORD,
    REGION_WSDL_URL,
    REGION_EDO_DOCUMENT_DATE_FROM,
    REGION_EDO_DOCUMENT_DATE_TO,
    EDO_FOLDERS,
)
from region_api import RegionApiClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

PAGE_SIZE = 100


def _yesterday_range() -> Tuple[str, str]:
    """Возвращает (date_from, date_to) для предыдущего дня по МСК (UTC+3)."""
    moscow = pytz.timezone('Europe/Moscow')
    today = datetime.now(moscow).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    fmt = '%Y-%m-%d'
    return yesterday.strftime(fmt), yesterday.strftime(fmt)


def _document_date_range() -> Tuple[str, str]:
    """
    Период фильтра DocumentDateFrom / DocumentDateTo.
    Если заданы оба REGION_EDO_DOCUMENT_DATE_* в .env — используются они (тест / sanity).
    Иначе — предыдущий день по МСК.
    """
    has_from = bool(REGION_EDO_DOCUMENT_DATE_FROM)
    has_to = bool(REGION_EDO_DOCUMENT_DATE_TO)
    if has_from != has_to:
        logger.error(
            "Задайте оба REGION_EDO_DOCUMENT_DATE_FROM и REGION_EDO_DOCUMENT_DATE_TO "
            "или ни одного (сейчас задан только один).",
        )
        raise SystemExit(1)
    if has_from and has_to:
        return REGION_EDO_DOCUMENT_DATE_FROM, REGION_EDO_DOCUMENT_DATE_TO
    return _yesterday_range()


def _log_skipped_attachment(att: dict, idx: int, doc_id: str) -> None:
    """Предупреждение, если вложение (attachment) есть в ответе API, но без base64-тела."""
    att_id = (att.get('id') or '').strip()
    att_name = (att.get('file_name') or '').strip()
    if att_id or att_name:
        logger.warning(
            "    Вложение (attachment) idx=%d к документу id=%s: id=%r name=%r — "
            "пустое тело в getDocumentById, файл не сохранён "
            "(при REGION_DEBUG_XML смотрите сырой XML ответа).",
            idx, doc_id, att_id or '?', att_name or '?',
        )


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


def _contractor_map_from_api(api: RegionApiClient) -> dict[str, str]:
    """
    Возвращает {DisplayName: ContractorId} для всех записей getContractors
    с непустым ContractorId, без дубликатов по ContractorId (первое имя сохраняется).
    """
    contractors = api.get_contractors()
    if not contractors:
        logger.error("Не удалось получить список контрагентов (contractors)")
        return {}

    logger.info("Записей в ответе getContractors: %d", len(contractors))

    name_to_id: dict[str, str] = {}
    seen_ids: set[str] = set()

    for c in contractors:
        contractor_id = (c.get("ContractorId") or "").strip()
        display_name = (c.get("DisplayName") or "").strip()
        if not contractor_id:
            logger.warning(
                "Пропуск записи без ContractorId (DisplayName=%r)", display_name or "(пусто)",
            )
            continue
        if contractor_id in seen_ids:
            logger.debug(
                "Пропуск дубликата ContractorId=%s (DisplayName=%r)", contractor_id, display_name,
            )
            continue
        seen_ids.add(contractor_id)
        label = display_name if display_name else f"(без имени, id={contractor_id})"
        name_to_id[label] = contractor_id

    logger.info("Уникальных ContractorId к обработке: %d", len(name_to_id))
    return name_to_id


def _download_documents_from_folder(
    api: RegionApiClient,
    folder: str,
    contractor_id: str,
    contractor_name: str,
    date_from: str,
    date_to: str,
    output_dir: str,
    region_login: str,
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

    total_api = api.get_total_documents_count(folder, filtr)
    logger.info(
        "  [%s] папка '%s' — getTotalDocumentsCount (API)=%d",
        contractor_name, folder, total_api,
    )

    downloaded: list[dict] = []
    offset = 0
    fetched_meta_count = 0

    while True:
        docs = api.get_document_info_from_folder(
            folder=folder,
            filtr_xml=filtr,
            limit=str(PAGE_SIZE),
            offset=str(offset),
        )
        if not docs:
            if offset == 0:
                logger.debug(
                    "  [%s] папка '%s' — документов нет", contractor_name, folder,
                )
            break

        fetched_meta_count += len(docs)

        if offset == 0:
            logger.info("  [%s] папка '%s' — загрузка документов...", contractor_name, folder)

        for doc_meta in docs:
            doc_id = doc_meta.get('DocumentId', '')
            file_name = doc_meta.get('DocumentFileName', '')
            display_name = doc_meta.get('DocumentDisplayName', file_name)

            logger.info(
                "    Скачивание: id=%s  '%s'", doc_id, display_name,
            )

            doc_full = api.get_document_by_id(doc_id)
            body_b64 = None
            if doc_full:
                body_b64 = doc_full.get('body_base64')
            if not body_b64:
                body_b64 = api.get_document_body(doc_id)

            saved_count = 0
            if body_b64:
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
                    'login': region_login,
                    'contractor': contractor_name,
                    'folder': folder,
                    'display_name': display_name,
                    'document_date': doc_meta.get('DocumentDate', ''),
                })
                saved_count += 1

            for idx, att in enumerate(doc_full.get('attachments', []) if doc_full else []):
                att_b64 = att.get('body_base64')
                if not att_b64:
                    _log_skipped_attachment(att, idx, doc_id)
                    continue
                att_name = att.get('file_name') or f"attachment_{idx}"
                base_safe = _safe_filename(file_name, doc_id)
                name_part, _ = os.path.splitext(base_safe)
                att_safe = _safe_filename(att_name, att.get('id', str(idx)))
                safe_att_name = f"{name_part}_attachment_{idx}_{att_safe}"
                att_path = os.path.join(output_dir, safe_att_name)
                if os.path.exists(att_path):
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    safe_att_name = f"{name_part}_attachment_{idx}_{ts}_{att_safe}"
                    att_path = os.path.join(output_dir, safe_att_name)
                with open(att_path, 'wb') as f:
                    f.write(base64.b64decode(att_b64))
                att_size = os.path.getsize(att_path)
                logger.info("    Сохранено вложение: %s (%d байт)", att_path, att_size)
                downloaded.append({
                    'document_id': doc_id,
                    'filename': safe_att_name,
                    'filepath': att_path,
                    'size': att_size,
                    'login': region_login,
                    'contractor': contractor_name,
                    'folder': folder,
                    'display_name': display_name,
                    'document_date': doc_meta.get('DocumentDate', ''),
                })
                saved_count += 1

            if saved_count == 0:
                logger.warning(
                    "    Тело документа (body) id=%s пустое и вложений не найдено — пропуск", doc_id,
                )

        offset += PAGE_SIZE

    if total_api != fetched_meta_count:
        logger.warning(
            "  [%s] папка '%s' — расхождение (mismatch): getTotalDocumentsCount=%d, "
            "собрано элементов DocumentInfo по страницам=%d "
            "(пагинация (pagination) limit/offset или ответ сервера).",
            contractor_name, folder, total_api, fetched_meta_count,
        )

    return downloaded


def _download_documents_from_archive(
    api: RegionApiClient,
    contractor_id: str,
    contractor_name: str,
    date_from: str,
    date_to: str,
    output_dir: str,
    region_login: str,
) -> list[dict]:
    """
    Скачивает документы из архива "СЭД Регион" (getDocumentInfoByParams)
    для данного контрагента за указанный период.
    """
    filtr = RegionApiClient.build_filter_xml(
        contractor_id=contractor_id,
        date_from=date_from,
        date_to=date_to,
    )

    docs = api.get_document_info_by_params(filtr_xml=filtr, limit=str(PAGE_SIZE))
    if not docs:
        logger.debug("  [%s] архив — документов нет", contractor_name)
        return []

    if len(docs) >= PAGE_SIZE:
        logger.warning(
            "  [%s] архив (getDocumentInfoByParams): получено %d документов (limit=%d). "
            "В WSDL нет параметра offset для этой операции — при большем числе записей по фильтру "
            "список может быть обрезан.",
            contractor_name, len(docs), PAGE_SIZE,
        )

    logger.info(
        "  [%s] архив (getDocumentInfoByParams) — найдено документов: %d",
        contractor_name, len(docs),
    )

    downloaded: list[dict] = []
    archive_label = "Archive"

    for doc_meta in docs:
        doc_id = doc_meta.get('DocumentId', '')
        file_name = doc_meta.get('DocumentFileName', '')
        display_name = doc_meta.get('DocumentDisplayName', file_name)

        logger.info("    Скачивание: id=%s  '%s'", doc_id, display_name)

        doc_full = api.get_document_by_id(doc_id)
        body_b64 = None
        if doc_full:
            body_b64 = doc_full.get('body_base64')
        if not body_b64:
            body_b64 = api.get_document_body(doc_id)

        saved_count = 0
        if body_b64:
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
                'login': region_login,
                'contractor': contractor_name,
                'folder': archive_label,
                'display_name': display_name,
                'document_date': doc_meta.get('DocumentDate', ''),
            })
            saved_count += 1

        for idx, att in enumerate(doc_full.get('attachments', []) if doc_full else []):
            att_b64 = att.get('body_base64')
            if not att_b64:
                _log_skipped_attachment(att, idx, doc_id)
                continue
            att_name = att.get('file_name') or f"attachment_{idx}"
            base_safe = _safe_filename(file_name, doc_id)
            name_part, _ = os.path.splitext(base_safe)
            att_safe = _safe_filename(att_name, att.get('id', str(idx)))
            safe_att_name = f"{name_part}_attachment_{idx}_{att_safe}"
            att_path = os.path.join(output_dir, safe_att_name)
            if os.path.exists(att_path):
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                safe_att_name = f"{name_part}_attachment_{idx}_{ts}_{att_safe}"
                att_path = os.path.join(output_dir, safe_att_name)
            with open(att_path, 'wb') as f:
                f.write(base64.b64decode(att_b64))
            att_size = os.path.getsize(att_path)
            logger.info("    Сохранено вложение: %s (%d байт)", att_path, att_size)
            downloaded.append({
                'document_id': doc_id,
                'filename': safe_att_name,
                'filepath': att_path,
                'size': att_size,
                'login': region_login,
                'contractor': contractor_name,
                'folder': archive_label,
                'display_name': display_name,
                'document_date': doc_meta.get('DocumentDate', ''),
            })
            saved_count += 1

        if saved_count == 0:
            logger.warning(
                "    Тело документа (body) id=%s пустое и вложений не найдено — пропуск", doc_id,
            )

    return downloaded


def main():
    logger.info("=" * 70)
    logger.info("Выгрузка вложений ЭДО Регион")
    logger.info("=" * 70)

    if not REGION_LOGINS or not REGION_PASSWORD:
        logger.error(
            "Не заданы REGION_LOGIN (список логинов через запятую) / REGION_PASSWORD в .env. "
            "Скопируйте env_template.txt → .env и заполните значения."
        )
        sys.exit(1)

    date_from, date_to = _document_date_range()
    if REGION_EDO_DOCUMENT_DATE_FROM and REGION_EDO_DOCUMENT_DATE_TO:
        logger.info(
            "Период (period) из .env REGION_EDO_DOCUMENT_DATE_*: %s — %s",
            date_from, date_to,
        )
    else:
        logger.info("Период (period): %s — %s (предыдущий день по МСК)", date_from, date_to)

    output_dir = _output_dir()
    logger.info("Папка выгрузки (output): %s", os.path.abspath(output_dir))
    logger.info("Логинов к обходу (logins): %d", len(REGION_LOGINS))

    all_downloaded: list[dict] = []

    for region_login in REGION_LOGINS:
        logger.info("=" * 60)
        logger.info("Учётная запись (login): %s", region_login)

        api = RegionApiClient(
            wsdl_url=REGION_WSDL_URL,
            login=region_login,
            password=REGION_PASSWORD,
        )

        user_id = api.authenticate()
        if not user_id:
            logger.warning(
                "Аутентификация (authentication) не пройдена для логина %s — пропуск, следующий.",
                region_login,
            )
            continue

        contractor_map = _contractor_map_from_api(api)
        if not contractor_map:
            logger.warning(
                "Для логина %s в ответе getContractors нет контрагентов с ContractorId — пропуск.",
                region_login,
            )
            continue

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
                    region_login=region_login,
                )
                all_downloaded.extend(downloaded)

            downloaded = _download_documents_from_archive(
                api=api,
                contractor_id=contractor_id,
                contractor_name=contractor_name,
                date_from=date_from,
                date_to=date_to,
                output_dir=output_dir,
                region_login=region_login,
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
                "  %3d. [%s][%s] %s  (%d байт)",
                i, d['login'], d['contractor'], d['filename'], d['size'],
            )
    else:
        logger.info("  Вложений (attachments) за %s не найдено.", date_from)

    logger.info("=" * 70)
    logger.info("Готово (done).")


if __name__ == '__main__':
    main()
