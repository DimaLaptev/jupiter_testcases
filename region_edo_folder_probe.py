"""
Сценарий отладки SOAP СЭД Регион без region_api.py (только zeep (zeep) + WSDL (WSDL)).

Порядок (sequence):
  1. getContractors — список ContractorId / DisplayName;
  2. для каждого контрагента (contractor) и каждой папки из config_region.EDO_FOLDERS —
     getDocumentInfoFromFolderByParams (наличие документов в папках (folders)).

В stdout — полный XML SOAP envelope запроса и ответа на каждый вызов.
Краткие сообщения — в stderr (logging), с обрезкой строк (truncation).

Переменные окружения (environment):
  REGION_LOGIN, REGION_PASSWORD, REGION_WSDL_URL;
  REGION_EDO_DOCUMENT_DATE_FROM / TO — опционально, иначе «вчера» по МСК (pytz);
  REGION_CONTRACTOR_ID — опционально: обработать только этот ContractorId (после getContractors);
  VERIFY_SSL=0 — только для отладки (небезопасно).

Пример (example):
  python region_edo_folder_probe.py
  python region_edo_folder_probe.py --contractor-id 12345 --folder InWork
"""

from __future__ import annotations

import argparse
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

logger = logging.getLogger(__name__)


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

    logger.info("Готово (done).")


if __name__ == "__main__":
    main()
