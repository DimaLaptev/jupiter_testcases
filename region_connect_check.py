"""
Проверка подключения (connectivity) к SOAP API СЭД Регион: только authentification.

Переменные окружения (environment) — из .env в текущей директории или из среды:
  REGION_USERNAME, REGION_PASSWORD — обязательны
  REGION_WSDL_URL — опционально (есть значение по умолчанию)
  VERIFY_SSL — опционально (по умолчанию true)
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from requests import Session
from zeep import Client
from zeep.exceptions import Fault
from zeep.transports import Transport

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_DEFAULT_WSDL = "https://edo.region.ru/soap/soapdotnet/soap?wsdl"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _log_last_http(last_http: dict[str, object]) -> None:
    """Печатает код HTTP (HTTP status) и фрагмент тела ответа (response body), если были перехвачены."""
    if not last_http:
        logger.error("HTTP: последний ответ не перехвачен.")
        return
    code = last_http.get("status_code")
    reason = last_http.get("reason") or ""
    if code is not None:
        logger.error("HTTP код ответа (status_code): %s %s", code, reason.strip())
    preview = last_http.get("body_preview")
    if preview:
        logger.error("Описание/тело ответа (response body, превью): %s", preview)


def main() -> None:
    load_dotenv()

    login = (os.getenv("REGION_USERNAME") or "").strip()
    password = (os.getenv("REGION_PASSWORD") or "").strip()
    wsdl_url = (os.getenv("REGION_WSDL_URL") or _DEFAULT_WSDL).strip()
    verify_ssl = _env_bool("VERIFY_SSL", True)

    if not login or not password:
        logger.error(
            "Задайте REGION_USERNAME и REGION_PASSWORD в .env или в окружении."
        )
        sys.exit(1)

    logger.info("WSDL: %s", wsdl_url)
    logger.info("Логин (login): %s", login)

    last_http: dict[str, object] = {}

    def _on_response(resp, **_kwargs):
        last_http["status_code"] = resp.status_code
        last_http["reason"] = getattr(resp, "reason", None) or ""
        try:
            text = resp.text or ""
            last_http["body_preview"] = text[:100] + ("..." if len(text) > 100 else "")
        except Exception as exc:  # noqa: BLE001
            last_http["body_preview"] = f"(не удалось прочитать тело ответа: {exc})"
        return resp

    session = Session()
    session.verify = verify_ssl
    session.hooks["response"].append(_on_response)
    transport = Transport(session=session, timeout=120)
    logger.info("Подключение к WSDL...")
    client = Client(wsdl=wsdl_url, transport=transport)
    service = client.service

    try:
        result = service.authentification(login, password)
    except Fault as fault:
        logger.error(
            "SOAP Fault: code=%s message=%s detail=%s",
            getattr(fault, "code", None),
            getattr(fault, "message", None) or str(fault),
            getattr(fault, "detail", None),
        )
        _log_last_http(last_http)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка вызова (exception): %s: %s", type(exc).__name__, exc)
        _log_last_http(last_http)
        sys.exit(1)

    user_id = int(result) if result else 0

    if user_id:
        logger.info("OK: аутентификация успешна, user_id=%s", user_id)
        sys.exit(0)

    logger.error("Аутентификация не удалась: user_id=0 (логин/пароль или учётная запись).")
    _log_last_http(last_http)
    sys.exit(1)


if __name__ == "__main__":
    main()
