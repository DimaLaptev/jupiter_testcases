"""
Сценарий отладки SOAP СЭД Регион без region_api.py (только zeep (zeep) + WSDL (WSDL)).

Порядок (sequence):
  1. getContractors — список ContractorId / DisplayName;
  2. для каждого контрагента (contractor) и каждой папки из config_region.EDO_FOLDERS —
     getDocumentInfoFromFolderByParams (наличие документов в папках (folders));
  3. при флаге --download — перед [y/N] печать в stdout предпросмотра SOAP
     (Client.create_message (zeep) — тот же XML, что уйдёт в getDocumentById / getDocumentBody),
     затем подтверждение (yes) и реальный вызов API (API call).

В stdout — полный XML SOAP envelope запроса и ответа на каждый вызов списков (getContractors / getDocumentInfoFromFolderByParams).
Вызовы скачивания не дублируют envelope в stdout (только краткий лог в stderr).
Краткие сообщения — в stderr (logging), с обрезкой строк (truncation).

Переменные окружения (environment):
  REGION_LOGIN, REGION_PASSWORD, REGION_WSDL_URL;
  REGION_EDO_DOCUMENT_DATE_FROM / TO — опционально, иначе «вчера» по МСК (pytz);
  REGION_CONTRACTOR_ID — опционально: обработать только этот ContractorId (после getContractors);
  VERIFY_SSL=0 — только для отладки (небезопасно).

Пример (example):
  python region_edo_folder_probe.py
  python region_edo_folder_probe.py --download --output ./out
  python region_edo_folder_probe.py --contractor-id 12345 --folder InWork --download
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Tuple
from xml.etree import ElementTree as ET

import pytz
import requests.exceptions as req_exc
from dotenv import load_dotenv
from lxml import etree as lxml_etree
from requests import Session
from zeep import Client
from zeep.exceptions import Fault
from zeep.plugins import HistoryPlugin
from zeep.transports import Transport

from config_region import (
    EDO_FOLDERS,
    REGION_EDO_DOCUMENT_DATE_FROM,
    REGION_EDO_DOCUMENT_DATE_TO,
    REGION_LOGINS,
    REGION_PASSWORD,
    REGION_WSDL_URL,
)

TERMINAL_LOG_MAX_CHARS = 300
DOWNLOAD_LOG_MAX_CHARS = 200

logger = logging.getLogger(__name__)


def _truncate_download_output(text: str, max_len: int = DOWNLOAD_LOG_MAX_CHARS) -> str:
    """Обрезка строки для логов при скачивании (download) — не длиннее max_len символов (characters)."""
    s = "" if text is None else str(text)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _log_fault_download(exc: Fault) -> None:
    """SOAP Fault при getDocumentById / getDocumentBody — сообщение не длиннее DOWNLOAD_LOG_MAX_CHARS."""
    msg = _truncate_download_output(
        " ".join(
            (
                f"code={getattr(exc, 'code', None)!r}",
                f"message={(getattr(exc, 'message', None) or str(exc))!r}",
                f"detail={getattr(exc, 'detail', None)!r}",
            ),
        ),
    )
    logger.error("SOAP Fault (download): %s", msg)


class _TruncatingTerminalFormatter(logging.Formatter):
    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: str = "%",
        *,
        max_chars: int = TERMINAL_LOG_MAX_CHARS,
        validate: bool = True,
    ) -> None:
        super().__init__(fmt, datefmt, style=style, validate=validate)
        self._max_chars = max_chars

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if len(text) <= self._max_chars:
            return text
        return text[: self._max_chars]


def _configure_terminal_log_limit(max_chars: int = TERMINAL_LOG_MAX_CHARS) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(
        _TruncatingTerminalFormatter(
            "%(asctime)s  %(levelname)-8s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            max_chars=max_chars,
        ),
    )
    root.addHandler(h)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _yesterday_moscow() -> Tuple[str, str]:
    moscow = pytz.timezone("Europe/Moscow")
    today = datetime.now(moscow).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    fmt = "%Y-%m-%d"
    return yesterday.strftime(fmt), yesterday.strftime(fmt)


def _document_date_range() -> Tuple[str, str]:
    has_from = bool(REGION_EDO_DOCUMENT_DATE_FROM)
    has_to = bool(REGION_EDO_DOCUMENT_DATE_TO)
    if has_from != has_to:
        logger.error(
            "Задайте оба REGION_EDO_DOCUMENT_DATE_FROM и REGION_EDO_DOCUMENT_DATE_TO "
            "или ни одного.",
        )
        raise SystemExit(1)
    if has_from and has_to:
        return REGION_EDO_DOCUMENT_DATE_FROM, REGION_EDO_DOCUMENT_DATE_TO
    return _yesterday_moscow()


def build_filter_xml(
    contractor_id: str = "",
    document_type_id: str = "",
    document_number: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_mode: str = "DocumentDate",
    order_mode: str = "DESC",
) -> str:
    """XML фильтра (filter) для getDocumentInfoFromFolderByParams (как в документации API)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<FilterInfo>"
        "<Info"
        f' DocumentTypeId="{document_type_id}"'
        f' ContractorId="{contractor_id}"'
        f' DocumentNumber="{document_number}"'
        f' DocumentDateFrom="{date_from}"'
        f' DocumentDateTo="{date_to}"'
        f' SortMode="{sort_mode}"'
        f' OrderMode="{order_mode}"'
        "/>"
        "</FilterInfo>"
    )


def _parse_document_infos(xml_str: str) -> list[dict]:
    if not xml_str:
        return []
    root = ET.fromstring(xml_str)
    return [dict(elem.attrib) for elem in root.findall(".//DocumentInfo")]


def _parse_contractors(xml_str: str) -> list[dict]:
    """Разбор ответа getContractors (как в region_api, без импорта)."""
    if not xml_str:
        return []
    root = ET.fromstring(xml_str)
    rows: list[dict] = []
    for elem in root.findall(".//Contractors"):
        rows.append({
            "ContractorId": (elem.get("ContractorId") or "").strip(),
            "DisplayName": (elem.get("DisplayName") or "").strip(),
        })
    return rows


def _safe_filename(name: str, document_id: str) -> str:
    if not name:
        name = f"document_{document_id}"
    for ch in r'<>:"/\|?*':
        name = name.replace(ch, "_")
    return name


def _unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    directory, base = os.path.dirname(path), os.path.basename(path)
    name_part, ext = os.path.splitext(base)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(directory, f"{name_part}_{ts}{ext}")


def _prompt_yes(stderr_question: str) -> bool:
    """Подтверждение в терминале (terminal): y/yes/д/да — да (читает stdin (stdin))."""
    sys.stderr.write(f"{stderr_question} [y/N]: ")
    sys.stderr.flush()
    try:
        line = sys.stdin.readline()
    except (EOFError, KeyboardInterrupt):
        return False
    if not line:
        return False
    return line.strip().lower() in ("y", "yes", "д", "да")


def _parse_document_by_id_xml(xml_str: str) -> dict | None:
    """Разбор ответа getDocumentById (как в region_api, без импорта)."""
    if not xml_str:
        return None
    root = ET.fromstring(xml_str)
    doc_elem = root.find(".//Document")
    if doc_elem is None:
        return None
    result: dict = dict(doc_elem.attrib)
    result["body_base64"] = (doc_elem.text or "").strip()
    signers = [dict(s.attrib) for s in root.findall(".//Signers")]
    result["signers"] = signers
    attachments: list[dict] = []
    for xpath in (".//Attachments/*", ".//Attachment", ".//DocumentAttachment"):
        for att in root.findall(xpath):
            att_dict = dict(att.attrib)
            body = (att.text or "").strip()
            file_name = (
                att_dict.get("FileName")
                or att_dict.get("Name")
                or att_dict.get("DocumentFileName")
                or ""
            )
            att_id = (
                att_dict.get("Id")
                or att_dict.get("AttachmentId")
                or att_dict.get("DocumentId")
                or ""
            )
            if body or file_name or att_id:
                attachments.append({
                    "id": att_id,
                    "file_name": file_name,
                    "body_base64": body,
                })
    if attachments:
        result["attachments"] = attachments
    return result


def _fetch_document_by_id(
    service,
    login: str,
    password: str,
    document_id: str,
) -> dict | None:
    try:
        xml_str = service.getDocumentById(login, password, document_id)
    except Fault as exc:
        _log_fault_download(exc)
        return None
    except req_exc.RequestException as exc:
        logger.error(
            "Сеть при getDocumentById(%s): %s",
            document_id,
            _truncate_download_output(exc),
        )
        return None
    except ET.ParseError as exc:
        logger.error(
            "XML parse getDocumentById(%s): %s",
            document_id,
            _truncate_download_output(exc),
        )
        return None
    try:
        return _parse_document_by_id_xml(xml_str)
    except ET.ParseError as exc:
        logger.error(
            "XML parse ответа getDocumentById(%s): %s",
            document_id,
            _truncate_download_output(exc),
        )
        return None


def _fetch_document_body(service, login: str, password: str, document_id: str) -> str | None:
    try:
        result = service.getDocumentBody(login, password, document_id)
    except Fault as exc:
        _log_fault_download(exc)
        return None
    except req_exc.RequestException as exc:
        logger.error(
            "Сеть при getDocumentBody(%s): %s",
            document_id,
            _truncate_download_output(exc),
        )
        return None
    if not result:
        return None
    return result


def _unique_contractors_by_id(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        cid = r.get("ContractorId") or ""
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(r)
    return out


def _envelope_to_unicode(env) -> str:
    return lxml_etree.tostring(env, encoding="unicode", pretty_print=True)


def _print_stdout(title: str, xml_text: str) -> None:
    sys.stdout.write(f"\n=== {title} ===\n{xml_text}")
    if not xml_text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def _print_soap_request_preview(
    client: Client,
    operation_name: str,
    heading: str,
    args: tuple,
) -> None:
    """
    Тот же payload (payload), что уйдёт в zeep в service.<operation_name>(*args),
    без сети: Client.create_message (см. zeep) строит envelope (SOAP envelope).
    """
    try:
        envelope = client.create_message(client.service, operation_name, *args)
        xml_text = lxml_etree.tostring(
            envelope, encoding="unicode", pretty_print=True,
        )
        _print_stdout(heading, xml_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "%s",
            _truncate_download_output(
                f"Предпросмотр SOAP (preview) {operation_name} не сформирован: {exc}",
            ),
        )


def _print_get_document_id_preview(
    client: Client,
    login: str,
    password: str,
    document_id: str,
    heading: str,
    *,
    stderr_note: str | None = None,
) -> None:
    """GET getDocumentById: показ XML запроса (request), затем вопрос [y/N] в отдельной строке."""
    if stderr_note:
        sys.stderr.write(stderr_note + "\n")
        sys.stderr.flush()
    _print_soap_request_preview(
        client, "getDocumentById", heading, (login, password, document_id),
    )


def _print_get_document_body_preview(
    client: Client,
    login: str,
    password: str,
    document_id: str,
    heading: str,
) -> None:
    _print_soap_request_preview(
        client, "getDocumentBody", heading, (login, password, document_id),
    )


def _print_soap_roundtrip(history: HistoryPlugin, label: str) -> None:
    """Печать последнего запроса/ответа из HistoryPlugin (после одного RPC (remote procedure call))."""
    if history.last_sent and "envelope" in history.last_sent:
        _print_stdout(
            f"{label} — SOAP XML запроса (request envelope)",
            _envelope_to_unicode(history.last_sent["envelope"]),
        )
    else:
        logger.warning("%s: нет last_sent envelope.", label)

    if history.last_received and "envelope" in history.last_received:
        _print_stdout(
            f"{label} — SOAP XML ответа (response envelope)",
            _envelope_to_unicode(history.last_received["envelope"]),
        )
    else:
        logger.warning("%s: нет last_received envelope.", label)


def _log_fault(exc: Fault) -> None:
    logger.error(
        "SOAP Fault: code=%s message=%s detail=%s",
        getattr(exc, "code", None),
        getattr(exc, "message", None) or str(exc),
        getattr(exc, "detail", None),
    )


def _interactive_save_document_files(
    client: Client,
    service,
    login: str,
    password: str,
    meta: dict,
    output_dir: str,
    context: str,
) -> None:
    """
    Перед каждым [y/N] — в stdout предпросмотр SOAP-запроса (getDocumentById / getDocumentBody)
    через client.create_message (без сети). После согласия — реальный вызов service.*.
    """
    doc_id = (meta.get("DocumentId") or "").strip()
    if not doc_id:
        return
    file_name = meta.get("DocumentFileName", "") or ""
    display = (meta.get("DocumentDisplayName") or file_name) or doc_id
    doc_full: dict | None = None

    _print_get_document_id_preview(
        client,
        login,
        password,
        doc_id,
        f"[{context}] Предпросмотр getDocumentById (основной файл, main), documentId={doc_id!r}",
    )
    if _prompt_yes(
        f"[{context}] Скачать основной файл (main file) документа id={doc_id} «{display}»",
    ):
        doc_full = _fetch_document_by_id(service, login, password, doc_id)
        if doc_full:
            body_b64 = (doc_full.get("body_base64") or "").strip()
            if not body_b64:
                _print_get_document_body_preview(
                    client,
                    login,
                    password,
                    doc_id,
                    f"[{context}] Предпросмотр getDocumentBody (тело пусто в getDocumentById), documentId={doc_id!r}",
                )
                body_b64 = (
                    _fetch_document_body(service, login, password, doc_id) or ""
                ).strip()
            if body_b64:
                safe = _safe_filename(file_name, doc_id)
                path = _unique_path(os.path.join(output_dir, safe))
                try:
                    with open(path, "wb") as f:
                        f.write(base64.b64decode(body_b64))
                    logger.info(
                        "%s",
                        _truncate_download_output(
                            f"Сохранено: {path} ({os.path.getsize(path)} байт)",
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "%s",
                        _truncate_download_output(f"Ошибка записи {path}: {exc}"),
                    )
            else:
                logger.warning(
                    "%s",
                    _truncate_download_output(
                        f"Нет base64 тела (body) для id={doc_id}",
                    ),
                )

    atts: list[dict] = list((doc_full or {}).get("attachments") or [])
    if not atts and doc_full is None:
        _print_get_document_id_preview(
            client,
            login,
            password,
            doc_id,
            f"[{context}] Предпросмотр getDocumentById (список вложений, attachments), documentId={doc_id!r}",
        )
        if not _prompt_yes(
            f"[{context}] Запросить getDocumentById для списка вложений (attachments) id={doc_id}?",
        ):
            return
        doc_full = _fetch_document_by_id(service, login, password, doc_id)
        if doc_full:
            atts = list(doc_full.get("attachments") or [])

    for idx, att in enumerate(atts):
        att_name = (att.get("file_name") or f"attachment_{idx}") or f"attachment_{idx}"
        att_id = att.get("id") or str(idx)
        cached_note: str | None = None
        if doc_full is not None:
            cached_note = (
                f"[{context}] Справка: вложение из уже полученного ответа getDocumentById; "
                f"ниже — тот же шаблон запроса, повторно SOAP при сохранении вложения не отправляется. "
                f"documentId={doc_id!r} attachmentIndex={idx}"
            )
        _print_get_document_id_preview(
            client,
            login,
            password,
            doc_id,
            f"[{context}] Предпросмотр getDocumentById (вложение (attachment) #{idx} «{att_name}»), documentId={doc_id!r}",
            stderr_note=cached_note,
        )
        if not _prompt_yes(
            f"[{context}] Скачать вложение (attachment) #{idx} «{att_name}» (id={att_id}) к документу id={doc_id}",
        ):
            continue
        if doc_full is None:
            doc_full = _fetch_document_by_id(service, login, password, doc_id)
        if not doc_full:
            break
        att_b64 = (att.get("body_base64") or "").strip()
        if not att_b64:
            logger.warning(
                "%s",
                _truncate_download_output(
                    f"Пустое тело вложения idx={idx} doc={doc_id}",
                ),
            )
            continue
        base_safe = _safe_filename(file_name, doc_id)
        name_part, _ = os.path.splitext(base_safe)
        att_safe = _safe_filename(att_name, att_id)
        safe_att = f"{name_part}_attachment_{idx}_{att_safe}"
        path = _unique_path(os.path.join(output_dir, safe_att))
        try:
            with open(path, "wb") as f:
                f.write(base64.b64decode(att_b64))
            logger.info(
                "%s",
                _truncate_download_output(
                    f"Сохранено вложение: {path} ({os.path.getsize(path)} байт)",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "%s",
                _truncate_download_output(f"Ошибка вложения {path}: {exc}"),
            )


def _resolve_login_password(args: argparse.Namespace) -> tuple[str, str]:
    login = (args.login or "").strip() or (REGION_LOGINS[0] if REGION_LOGINS else "")
    password = (args.password or "").strip() or (REGION_PASSWORD or "")
    if not login or not password:
        logger.error(
            "Укажите --login и --password или задайте REGION_LOGIN и REGION_PASSWORD в .env.",
        )
        raise SystemExit(1)
    return login, password


def main() -> None:
    _configure_terminal_log_limit(TERMINAL_LOG_MAX_CHARS)
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="getContractors, затем getDocumentInfoFromFolderByParams по папкам EDO_FOLDERS.",
    )
    parser.add_argument("--login", help="Логин (login); иначе REGION_LOGIN")
    parser.add_argument("--password", help="Пароль (password); иначе REGION_PASSWORD")
    parser.add_argument(
        "--wsdl",
        default=REGION_WSDL_URL,
        help="URL WSDL (по умолчанию REGION_WSDL_URL)",
    )
    parser.add_argument(
        "--folder",
        default=None,
        choices=EDO_FOLDERS,
        help="Одна папка ЭДО (folder); если не задано — все из config_region.EDO_FOLDERS",
    )
    parser.add_argument(
        "--contractor-id",
        dest="contractor_id",
        default="",
        help="Только этот ContractorId; иначе все из getContractors (или REGION_CONTRACTOR_ID)",
    )
    parser.add_argument("--date-from", dest="date_from", default="", help="YYYY-MM-DD")
    parser.add_argument("--date-to", dest="date_to", default="", help="YYYY-MM-DD")
    parser.add_argument("--limit", default="100", help="limit (строка)")
    parser.add_argument("--offset", default="0", help="offset (строка)")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Скачивание тел/вложений: перед каждым файлом запрос yes в терминале (terminal)",
    )
    parser.add_argument(
        "--output",
        default="region_edo_probe_out",
        help="Каталог сохранения файлов при --download (output directory)",
    )
    args = parser.parse_args()

    explicit_filter = (args.contractor_id or "").strip() or (
        os.getenv("REGION_CONTRACTOR_ID") or ""
    ).strip()

    login, password = _resolve_login_password(args)
    wsdl_url = (args.wsdl or REGION_WSDL_URL or "").strip()
    if not wsdl_url:
        logger.error("Пустой WSDL URL.")
        raise SystemExit(1)

    if args.date_from and args.date_to:
        date_from, date_to = args.date_from.strip(), args.date_to.strip()
    elif not args.date_from and not args.date_to:
        date_from, date_to = _document_date_range()
    else:
        logger.error("Задайте оба --date-from и --date-to или ни одного.")
        raise SystemExit(1)

    folders: list[str] = [args.folder] if args.folder is not None else list(EDO_FOLDERS)

    logger.info("WSDL: %s", wsdl_url)
    logger.info("Логин (login): %s", login)
    logger.info("Папки (folders): %s", folders)
    logger.info("Период (period) DocumentDate: %s — %s", date_from, date_to)
    logger.info("EDO_FOLDERS из config_region: %s", list(EDO_FOLDERS))
    if args.download:
        os.makedirs(args.output, exist_ok=True)
        logger.info(
            "%s",
            _truncate_download_output(
                f"Скачивание (download): каталог {os.path.abspath(args.output)}",
            ),
        )

    verify_ssl = _env_bool("VERIFY_SSL", True)
    session = Session()
    session.verify = verify_ssl
    transport = Transport(session=session, timeout=120)
    history = HistoryPlugin()

    logger.info("Загрузка WSDL…")
    try:
        client = Client(wsdl=wsdl_url, transport=transport, plugins=[history])
        service = client.service
    except req_exc.RequestException as exc:
        logger.error("Сеть при загрузке WSDL / создании Client: %s", exc)
        raise SystemExit(1) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка Client: %s: %s", type(exc).__name__, exc)
        raise SystemExit(1) from exc

    contractors_xml: str | None = None
    try:
        contractors_xml = service.getContractors(login, password)
    except Fault as exc:
        _log_fault(exc)
        raise SystemExit(1) from exc
    except req_exc.RequestException as exc:
        logger.error("Сеть при getContractors: %s", exc)
        raise SystemExit(1) from exc

    _print_soap_roundtrip(history, "getContractors")

    raw_rows = _parse_contractors(contractors_xml or "")
    contractors = _unique_contractors_by_id(raw_rows)
    logger.info("Контрагентов в ответе (rows): %d, уникальных ContractorId: %d", len(raw_rows), len(contractors))
    for r in contractors:
        logger.info("  ContractorId=%s DisplayName=%s", r.get("ContractorId"), r.get("DisplayName"))

    if not contractors:
        logger.error("Список контрагентов пуст — запросы по папкам не выполняются.")
        raise SystemExit(1)

    if explicit_filter:
        contractors = [c for c in contractors if c.get("ContractorId") == explicit_filter]
        if not contractors:
            logger.error(
                "ContractorId=%r не найден среди записей getContractors — проверьте фильтр.",
                explicit_filter,
            )
            raise SystemExit(1)
        logger.info("Фильтр: только ContractorId=%s", explicit_filter)

    for c in contractors:
        cid = c.get("ContractorId") or ""
        cname = c.get("DisplayName") or ""
        filtr_xml = build_filter_xml(contractor_id=cid, date_from=date_from, date_to=date_to)
        logger.info("Контрагент (contractor): id=%s name=%s", cid, cname)
        logger.info("XML фильтра (filter): %s", filtr_xml[:200] + ("…" if len(filtr_xml) > 200 else ""))

        for folder in folders:
            label = f"getDocumentInfoFromFolderByParams contractor={cid!r} folder={folder!r}"
            try:
                xml_result = service.getDocumentInfoFromFolderByParams(
                    login,
                    password,
                    folder,
                    filtr_xml,
                    str(args.limit),
                    str(args.offset),
                )
            except Fault as exc:
                _log_fault(exc)
                logger.error("Пропуск папки из-за Fault: %s", folder)
                continue
            except req_exc.RequestException as exc:
                logger.error("Сеть при %s: %s", label, exc)
                continue

            _print_soap_roundtrip(history, label)

            docs = _parse_document_infos(xml_result or "")
            logger.info(
                "DocumentInfo в папке (folder) %s для contractor %s: %d",
                folder,
                cid,
                len(docs),
            )
            for i, meta in enumerate(docs[:10], 1):
                logger.info(
                    "  %d. id=%s file=%s",
                    i,
                    meta.get("DocumentId", ""),
                    (meta.get("DocumentFileName") or meta.get("DocumentDisplayName") or "")[:80],
                )
            if len(docs) > 10:
                logger.info("  … ещё %d записей", len(docs) - 10)

            if args.download:
                ctx = f"contractor={cid} folder={folder}"
                for meta in docs:
                    _interactive_save_document_files(
                        client,
                        service,
                        login,
                        password,
                        meta,
                        args.output,
                        ctx,
                    )

    logger.info("Готово (done).")


if __name__ == "__main__":
    main()
