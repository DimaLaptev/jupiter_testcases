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

EDO_FOLDERS = [
    'На регистрацию',
    'В работе\\Входящие',
    'Архив\\Входящие',
]

DEPOSITARY_DEPARTMENTS = [
    'ДОМ.РФ',
    'ИЦБ-Райффайзенбанк',
    'Ипотечный агент ТФБ1, ЗАО',
    'ЗАО "Ипотечный агент ИНТЕХ"',
    'ИЦБ-ВТБ',
    'ИЦБ-ДельтаКредит',
    'ИЦБ-Металинвестбанк',
    'ИЦБ-НФИ',
    'ИЦБ - Банк ДОМ.РФ',
    'ИЦБ-ГПБ',
    'ИА ДОМ РФ',
    'ИЦБ-Абсолют',
    'ИЦБ Совкомбанк',
    'Фабрика Банк "ДОМ.РФ"',
    'Фабрика ГПБ',
]
