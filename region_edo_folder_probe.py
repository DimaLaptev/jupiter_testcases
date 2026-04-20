"""
Один SOAP-вызов (single SOAP call): getDocumentInfoFromFolderByParams.
Скрипт автономен от region_api.py — только zeep (zeep) + WSDL (WSDL).

При отправке в stdout выводится XML тела SOAP-запроса (SOAP request envelope),
после ответа — XML тела SOAP-ответа (SOAP response envelope). Краткие сообщения — в stderr (logging).

Переменные окружения (environment):
  REGION_LOGIN, REGION_PASSWORD, REGION_WSDL_URL;
  REGION_EDO_DOCUMENT_DATE_FROM / TO — опционально, иначе «вчера» по МСК (pytz);
  VERIFY_SSL=0 — только для отладки (небезопасно).

Пример (example):
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


def _envelope_to_unicode(env) -> str:
    return lxml_etree.tostring(env, encoding="unicode", pretty_print=True)


def _print_stdout(title: str, xml_text: str) -> None:
    """Полный XML в stdout (stdout), без обрезки — для отладки SOAP."""
    sys.stdout.write(f"\n=== {title} ===\n{xml_text}")
    if not xml_text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


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
        description="Один вызов getDocumentInfoFromFolderByParams + вывод XML запроса/ответа в stdout.",
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
        default="ReadyToRegister",
        choices=EDO_FOLDERS,
        help="Папка ЭДО (folder)",
    )
    parser.add_argument(
        "--contractor-id",
        dest="contractor_id",
        required=True,
        help="ContractorId в фильтре (filter) — обязателен (без второго запроса getContractors).",
    )
    parser.add_argument("--date-from", dest="date_from", default="", help="YYYY-MM-DD")
    parser.add_argument("--date-to", dest="date_to", default="", help="YYYY-MM-DD")
    parser.add_argument("--limit", default="100", help="limit (строка)")
    parser.add_argument("--offset", default="0", help="offset (строка)")
    args = parser.parse_args()

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

    filtr_xml = build_filter_xml(
        contractor_id=args.contractor_id.strip(),
        date_from=date_from,
        date_to=date_to,
    )

    logger.info("WSDL: %s", wsdl_url)
    logger.info("Логин (login): %s", login)
    logger.info("Папка (folder): %s", args.folder)
    logger.info("Период (period): %s — %s", date_from, date_to)

    verify_ssl = _env_bool("VERIFY_SSL", True)
    session = Session()
    session.verify = verify_ssl
    transport = Transport(session=session, timeout=120)
    history = HistoryPlugin()

    logger.info("Загрузка WSDL и один вызов getDocumentInfoFromFolderByParams…")
    try:
        client = Client(wsdl=wsdl_url, transport=transport, plugins=[history])
        service = client.service
    except req_exc.RequestException as exc:
        logger.error("Сеть при загрузке WSDL / создании Client: %s", exc)
        raise SystemExit(1) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка Client: %s: %s", type(exc).__name__, exc)
        raise SystemExit(1) from exc

    xml_result: str | None = None
    try:
        xml_result = service.getDocumentInfoFromFolderByParams(
            login,
            password,
            args.folder,
            filtr_xml,
            str(args.limit),
            str(args.offset),
        )
    except Fault as exc:
        _log_fault(exc)
        raise SystemExit(1) from exc
    except req_exc.RequestException as exc:
        logger.error("Сеть при SOAP: %s", exc)
        raise SystemExit(1) from exc

    if history.last_sent and "envelope" in history.last_sent:
        _print_stdout(
            "SOAP XML запроса (outgoing request envelope)",
            _envelope_to_unicode(history.last_sent["envelope"]),
        )
    else:
        logger.warning("HistoryPlugin: нет last_sent envelope — XML запроса не выведен.")

    if history.last_received and "envelope" in history.last_received:
        _print_stdout(
            "SOAP XML ответа (incoming response envelope)",
            _envelope_to_unicode(history.last_received["envelope"]),
        )
    else:
        logger.warning("HistoryPlugin: нет last_received envelope.")

    docs = _parse_document_infos(xml_result or "")
    logger.info("Разбор тела ответа (payload): DocumentInfo записей: %d", len(docs))
    for i, meta in enumerate(docs[:20], 1):
        logger.info(
            "  %d. id=%s file=%s",
            i,
            meta.get("DocumentId", ""),
            (meta.get("DocumentFileName") or meta.get("DocumentDisplayName") or "")[:80],
        )
    if len(docs) > 20:
        logger.info("  … и ещё %d (truncated list in log)", len(docs) - 20)

    logger.info("Готово (done).")


if __name__ == "__main__":
    main()
