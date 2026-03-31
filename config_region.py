"""
Конфигурация (configuration) подключения к SOAP API СЭД Регион.
Загружает переменные окружения (environment variables) из .env файла.
"""

import os
from dotenv import load_dotenv

load_dotenv()

REGION_LOGIN = os.getenv('REGION_LOGIN')
REGION_PASSWORD = os.getenv('REGION_PASSWORD')
REGION_WSDL_URL = os.getenv(
    'REGION_WSDL_URL',
    'https://edo.region.ru/soap/soapdotnet/soap?wsdl'
)
REGION_DEBUG_XML = os.getenv('REGION_DEBUG_XML', '').lower() in ('1', 'true', 'yes')

EDO_FOLDERS = [
    'ReadyToRegister',
    'InWork',
    'Archive',
]
