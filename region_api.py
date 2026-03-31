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
import os
from typing import List, Optional

from xml.etree import ElementTree as ET

from lxml import etree as lxml_etree
from zeep import Client
from zeep.plugins import HistoryPlugin
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

        self._history = HistoryPlugin()
        logger.info("Подключение к WSDL: %s", wsdl_url)
        self.client = Client(
            wsdl=wsdl_url, transport=transport, plugins=[self._history]
        )
        self.service = self.client.service

    # ------------------------------------------------------------------
    # Отладка: список операций WSDL (debug: list WSDL operations)
    # ------------------------------------------------------------------
    def list_wsdl_operations(self, keywords: Optional[List[str]] = None) -> List[str]:
        """
        Возвращает список имён операций SOAP из WSDL. Если заданы keywords
        (например, ['attachment', 'document', 'body']), логируются только
        операции, в имени которых встречается хотя бы одно ключевое слово.
        """
        operations = []
        try:
            for service in self.client.wsdl.services.values():
                for port in service.ports.values():
                    for op in getattr(port.binding, "_operations", {}).values():
                        name = getattr(op, "name", None)
                        if name and name not in operations:
                            operations.append(name)
        except Exception as e:
            logger.warning("Не удалось получить операции WSDL: %s", e)
            return []
        operations = sorted(operations)
        logger.info("Всего операций в WSDL: %d", len(operations))
        if keywords:
            kw_lower = [k.lower() for k in keywords]
            filtered = [op for op in operations if any(k in op.lower() for k in kw_lower)]
            logger.info("Операции по ключевым словам %s: %s", keywords, filtered)
            return filtered
        logger.info("Операции: %s", operations)
        return operations

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
        Соответствует разделу 5.2 документации (папки «На подпись», «На регистрацию», «В работе», «Архив»).
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

        if os.getenv("REGION_DEBUG_XML", "").lower() in ("1", "true", "yes"):
            if self._history.last_sent and "envelope" in self._history.last_sent:
                req_xml = lxml_etree.tostring(
                    self._history.last_sent["envelope"],
                    encoding="unicode",
                    pretty_print=True,
                )
                print("\n=== getDocumentInfoFromFolderByParams ЗАПРОС ===\n" + req_xml)
            if self._history.last_received and "envelope" in self._history.last_received:
                resp_xml = lxml_etree.tostring(
                    self._history.last_received["envelope"],
                    encoding="unicode",
                    pretty_print=True,
                )
                print("\n=== getDocumentInfoFromFolderByParams ОТВЕТ ===\n" + resp_xml)

        if not xml_str:
            return []

        root = ET.fromstring(xml_str)
        documents = []
        for doc in root.findall('.//DocumentInfo'):
            documents.append(dict(doc.attrib))
        if documents and os.getenv("REGION_DEBUG_XML", "").lower() in ("1", "true", "yes"):
            logger.info(
                "[REGION_DEBUG_XML] getDocumentInfoFromFolderByParams first DocumentInfo attrib: %s",
                documents[0],
            )
        return documents

    # ------------------------------------------------------------------
    # 5.3  Получение документа с подписями (document with signatures)
    # ------------------------------------------------------------------
    def get_document_by_id(self, document_id: str) -> Optional[dict]:
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

        if os.getenv("REGION_DEBUG_XML", "").lower() in ("1", "true", "yes"):
            preview = xml_str[:4000] + ("..." if len(xml_str) > 4000 else "")
            logger.info(
                "[REGION_DEBUG_XML] getDocumentById(%s) raw XML (first 4000 chars): %s",
                document_id, preview,
            )

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

        attachments = []
        for xpath in ('.//Attachments/*', './/Attachment', './/DocumentAttachment'):
            for att in root.findall(xpath):
                att_dict = dict(att.attrib)
                body = (att.text or '').strip()
                file_name = att_dict.get('FileName') or att_dict.get('Name') or att_dict.get('DocumentFileName') or ''
                att_id = att_dict.get('Id') or att_dict.get('AttachmentId') or att_dict.get('DocumentId') or ''
                if body or file_name or att_id:
                    attachments.append({
                        'id': att_id,
                        'file_name': file_name,
                        'body_base64': body,
                    })
        if attachments:
            result['attachments'] = attachments
            logger.debug("getDocumentById(%s): найдено вложений (attachments): %d", document_id, len(attachments))

        return result

    # ------------------------------------------------------------------
    # 4.2  Тело документа (document body) — base64
    # ------------------------------------------------------------------
    def get_document_body(self, document_id: str) -> Optional[str]:
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
        В WSDL нет параметра offset — постраничная выборка недоступна на стороне API.
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


if __name__ == "__main__":
    """Вывод списка операций WSDL (для проверки методов вложений и документов)."""
    from dotenv import load_dotenv
    load_dotenv()
    url = os.getenv("REGION_WSDL_URL", "https://edo.region.ru/soap/soapdotnet/soap?wsdl")
    client = RegionApiClient(
        wsdl_url=url,
        login=os.getenv("REGION_LOGIN", ""),
        password=os.getenv("REGION_PASSWORD", ""),
    )
    client.list_wsdl_operations(keywords=["attachment", "document", "body"])
