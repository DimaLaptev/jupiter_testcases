"""
SOAP-клиент (client) для web-службы интеграции СЭД Регион.

Обёртка над zeep для вызова функций (functions) API:
  - authentification
  - getContractors
  - getDocumentInfoFromFolderByParams
  - getTotalDocumentsCount
  - getDocumentById / getDocumentBody
"""

import logging
from xml.etree import ElementTree as ET

from zeep import Client
from zeep.transports import Transport
from requests import Session

logger = logging.getLogger(__name__)


class RegionApiClient:
    """Клиент (client) SOAP API СЭД Регион."""

    def __init__(self, wsdl_url: str, login: str, password: str,
                 timeout: int = 120, verify_ssl: bool = True):
        self.login = login
        self.password = password

        session = Session()
        session.verify = verify_ssl
        transport = Transport(session=session, timeout=timeout)

        logger.info("Подключение к WSDL: %s", wsdl_url)
        self.client = Client(wsdl=wsdl_url, transport=transport)
        self.service = self.client.service

    # ------------------------------------------------------------------
    # 1. Аутентификация (authentication)
    # ------------------------------------------------------------------
    def authenticate(self) -> int:
        """
        Вызывает authentification(login, password).
        Возвращает id пользователя (user id) или 0 при неудаче.
        """
        result = self.service.authentification(self.login, self.password)
        user_id = int(result) if result else 0
        if user_id:
            logger.info("Аутентификация успешна, user_id=%s", user_id)
        else:
            logger.error("Аутентификация не удалась")
        return user_id

    # ------------------------------------------------------------------
    # 2.2  Контрагенты (contractors)
    # ------------------------------------------------------------------
    def get_contractors(self) -> list[dict]:
        """
        Вызывает getContractors(login, password).
        Возвращает список словарей (list of dicts):
            [{'ContractorId': '1', 'DisplayName': 'ЗАО ...'}, ...]
        """
        xml_str = self.service.getContractors(self.login, self.password)
        if not xml_str:
            logger.warning("getContractors вернул пустой ответ (empty response)")
            return []

        root = ET.fromstring(xml_str)
        contractors = []
        for elem in root.findall('.//Contractors'):
            contractors.append({
                'ContractorId': elem.get('ContractorId'),
                'DisplayName': elem.get('DisplayName'),
            })
        logger.info("Получено контрагентов (contractors): %d", len(contractors))
        return contractors

    # ------------------------------------------------------------------
    # 5.2  Количество документов (documents count)
    # ------------------------------------------------------------------
    def get_total_documents_count(self, folder: str, filtr_xml: str) -> int:
        """
        Вызывает getTotalDocumentsCount(login, password, folder, filtr).
        Возвращает целое число (integer) — количество документов.
        """
        result = self.service.getTotalDocumentsCount(
            self.login, self.password, folder, filtr_xml
        )
        count = int(result) if result else 0
        logger.debug("Документов в папке '%s': %d", folder, count)
        return count

    # ------------------------------------------------------------------
    # 5.1  Список документов из папки (documents list from folder)
    # ------------------------------------------------------------------
    def get_document_info_from_folder(
        self, folder: str, filtr_xml: str,
        limit: str = '100', offset: str = '0'
    ) -> list[dict]:
        """
        Вызывает getDocumentInfoFromFolderByParams(login, password, folder,
            filtr, limit, offset).
        Возвращает список метаданных (metadata) документов.
        """
        xml_str = self.service.getDocumentInfoFromFolderByParams(
            self.login, self.password, folder, filtr_xml, limit, offset
        )
        if not xml_str:
            return []

        root = ET.fromstring(xml_str)
        documents = []
        for doc in root.findall('.//DocumentInfo'):
            documents.append(dict(doc.attrib))
        return documents

    # ------------------------------------------------------------------
    # 5.3  Получение документа с подписями (document with signatures)
    # ------------------------------------------------------------------
    def get_document_by_id(self, document_id: str) -> dict | None:
        """
        Вызывает getDocumentById(login, password, documentid).
        Возвращает словарь (dict) с ключами:
            - 'DocumentId', прочие атрибуты (attributes)
            - 'body_base64' — тело документа в base64
            - 'signers' — список подписантов (signers)
        Или None при неудаче.
        """
        xml_str = self.service.getDocumentById(
            self.login, self.password, document_id
        )
        if not xml_str:
            logger.warning("getDocumentById(%s) вернул null", document_id)
            return None

        root = ET.fromstring(xml_str)
        doc_elem = root.find('.//Document')
        if doc_elem is None:
            return None

        result = dict(doc_elem.attrib)
        result['body_base64'] = (doc_elem.text or '').strip()

        signers = []
        for s in root.findall('.//Signers'):
            signers.append(dict(s.attrib))
        result['signers'] = signers

        return result

    # ------------------------------------------------------------------
    # 4.2  Тело документа (document body) — base64
    # ------------------------------------------------------------------
    def get_document_body(self, document_id: str) -> str | None:
        """
        Вызывает getDocumentBody(login, password, documentid).
        Возвращает строку base64 с телом документа или None.
        """
        result = self.service.getDocumentBody(
            self.login, self.password, document_id
        )
        if not result:
            logger.warning("getDocumentBody(%s) вернул null", document_id)
            return None
        return result

    # ------------------------------------------------------------------
    # 4.1  Список документов из архива (archive documents list)
    # ------------------------------------------------------------------
    def get_document_info_by_params(
        self, filtr_xml: str, limit: str = '100'
    ) -> list[dict]:
        """
        Вызывает getDocumentInfoByParams(login, password, filtr, limit).
        Возвращает список метаданных (metadata) документов из архива.
        """
        xml_str = self.service.getDocumentInfoByParams(
            self.login, self.password, filtr_xml, limit
        )
        if not xml_str:
            return []

        root = ET.fromstring(xml_str)
        documents = []
        for doc in root.findall('.//DocumentInfo'):
            documents.append(dict(doc.attrib))
        return documents

    # ------------------------------------------------------------------
    # Утилита: построение XML-фильтра (filter builder)
    # ------------------------------------------------------------------
    @staticmethod
    def build_filter_xml(
        contractor_id: str = '',
        document_type_id: str = '',
        document_number: str = '',
        date_from: str = '',
        date_to: str = '',
        sort_mode: str = 'DocumentDate',
        order_mode: str = 'DESC',
    ) -> str:
        """
        Формирует XML-строку фильтра (filter) для функций
        getDocumentInfoByParams / getDocumentInfoFromFolderByParams.
        """
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<FilterInfo>'
            '<Info'
            f' DocumentTypeId="{document_type_id}"'
            f' ContractorId="{contractor_id}"'
            f' DocumentNumber="{document_number}"'
            f' DocumentDateFrom="{date_from}"'
            f' DocumentDateTo="{date_to}"'
            f' SortMode="{sort_mode}"'
            f' OrderMode="{order_mode}"'
            '/>'
            '</FilterInfo>'
        )
