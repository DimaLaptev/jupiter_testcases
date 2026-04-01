"""
Конфигурация (configuration) подключения к SOAP API СЭД Регион.
Загружает переменные окружения (environment variables) из .env файла.
"""

import os
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()


def _parse_region_logins(value: Optional[str]) -> List[str]:
    """Список логинов из REGION_LOGIN: через запятую (comma-separated), пробелы обрезаются."""
    if not value or not str(value).strip():
        return []
    return [part.strip() for part in str(value).split(',') if part.strip()]


REGION_LOGINS: List[str] = _parse_region_logins(os.getenv('REGION_LOGIN'))
REGION_PASSWORD = os.getenv('REGION_PASSWORD')
REGION_WSDL_URL = os.getenv(
    'REGION_WSDL_URL',
    'https://edo.region.ru/soap/soapdotnet/soap?wsdl'
)
REGION_DEBUG_XML = os.getenv('REGION_DEBUG_XML', '').lower() in ('1', 'true', 'yes')

# Опционально: период фильтра DocumentDate (YYYY-MM-DD) для region_edo_download.py.
# Если заданы оба — вместо «вчера» по МСК используется этот диапазон (sanity / тест фильтра).
REGION_EDO_DOCUMENT_DATE_FROM = (os.getenv('REGION_EDO_DOCUMENT_DATE_FROM') or '').strip()
REGION_EDO_DOCUMENT_DATE_TO = (os.getenv('REGION_EDO_DOCUMENT_DATE_TO') or '').strip()

EDO_FOLDERS = [
    'ReadyToRegister',
    'InWork',
    'Archive',
]
