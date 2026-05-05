"""Параметры подключения к SOAP API СЭД Регион из .env."""

import os
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()


def _parse_region_logins(value: Optional[str]) -> List[str]:
    """Список логинов REGION_LOGIN: через запятую, пробелы обрезаются."""
    if not value or not str(value).strip():
        return []
    return [part.strip() for part in str(value).split(',') if part.strip()]


REGION_LOGINS: List[str] = _parse_region_logins(os.getenv('REGION_LOGIN'))
REGION_PASSWORD = os.getenv('REGION_PASSWORD')
REGION_WSDL_URL = os.getenv(
    'REGION_WSDL_URL',
    'https://edo.region.ru/soap/soapdotnet/soap?wsdl'
)

# Опционально для region_edo_download: диапазон DocumentDate YYYY-MM-DD.
# Если заданы оба поля — вместо предыдущего дня по МСК; иначе — оба должны быть пустыми.
REGION_EDO_DOCUMENT_DATE_FROM = (os.getenv('REGION_EDO_DOCUMENT_DATE_FROM') or '').strip()
REGION_EDO_DOCUMENT_DATE_TO = (os.getenv('REGION_EDO_DOCUMENT_DATE_TO') or '').strip()

EDO_FOLDERS = [
    'ReadyToRegister',
    'InWork',
    'Archive',
]
