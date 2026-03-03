# Путь запросов при поиске и выгрузке вложений (region_edo_download.py)

Описание последовательности вызовов SOAP API ЭДО Регион при запуске `region_edo_download.py`: от входа в систему до сохранения тела документа и вложений на диск.

---

## 1. Общая схема

```
main()
  → authenticate()                    — один раз
  → _resolve_contractor_ids()         — один раз (getContractors)
  → для каждого (контрагент × папка):
       _download_documents_from_folder()
         → build_filter_xml()         — локально, без запроса
         → get_total_documents_count() — SOAP: количество документов
         → цикл по страницам:
              get_document_info_from_folder() — SOAP: список документов (limit/offset)
              для каждого документа:
                get_document_by_id()   — SOAP: документ + тело + вложения (если есть)
                [при отсутствии тела] get_document_body() — SOAP: только тело
                сохранение тела и вложений на диск
```

---

## 2. Пошаговый путь запросов

### Шаг 1. Аутентификация (один раз за запуск)

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `main()` → `api.authenticate()` | `RegionApiClient.authenticate()` | **authentification** | `login`, `password` |

**Ответ:** идентификатор пользователя (integer) или 0.

**Пример запроса (тело SOAP):**
```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <authentification xmlns="...">
      <login>user_login</login>
      <password>user_password</password>
    </authentification>
  </soap:Body>
</soap:Envelope>
```

**Пример ответа:**
```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <authentificationResponse>12345</authentificationResponse>
  </soap:Body>
</soap:Envelope>
```
*(значение — integer, id пользователя или 0 при ошибке)*

---

### Шаг 2. Получение контрагентов (депозитариев)

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `main()` → `_resolve_contractor_ids(api, DEPOSITARY_DEPARTMENTS, DEPOSITARY_ORGANIZATIONS)` | `api.get_contractors()` | **getContractors** | `login`, `password` |

**Ответ:** XML со списком контрагентов (`ContractorsList` → элементы `Contractors` с атрибутами `ContractorId`, `DisplayName`).  
Дальше в коде по этому списку отбираются депозитарии (сопоставление по подразделению/организации), формируется словарь `{ DisplayName: ContractorId }`. Дополнительных запросов к API на этом шаге нет.

**Пример запроса (тело SOAP):**
```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <getContractors xmlns="...">
      <login>user_login</login>
      <password>user_password</password>
    </getContractors>
  </soap:Body>
</soap:Envelope>
```

**Пример ответа (фрагмент XML, возвращаемый методом):**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<ContractorsList>
  <Contractors ContractorId="1" DisplayName="АО &quot;ДОМ.РФ&quot;"/>
  <Contractors ContractorId="46" DisplayName="ООО &quot;ДОМ.РФ Ипотечный агент&quot;"/>
  <Contractors ContractorId="48" DisplayName="ЗАО Полет"/>
</ContractorsList>
```

---

### Шаг 3. Обход контрагентов и папок

Для каждой пары **(контрагент, папка)** вызывается `_download_documents_from_folder()`.  
Папки задаются в `config_region.EDO_FOLDERS`: `ReadyToRegister`, `InWork`, `Archive`.

Внутри одной такой итерации запросы идут так.

---

### Шаг 4. Построение фильтра (без запроса)

| Где в коде | Действие |
|------------|----------|
| `_download_documents_from_folder()` | `RegionApiClient.build_filter_xml(contractor_id, date_from=..., date_to=...)` |

Формируется XML-строка фильтра (`FilterInfo` / `Info`): контрагент, период (предыдущий день по МСК). В API не отправляется, используется в следующих вызовах.

**Пример сформированного фильтра (XML):**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<FilterInfo>
  <Info DocumentTypeId="" ContractorId="46" DocumentNumber=""
        DocumentDateFrom="2025-02-18" DocumentDateTo="2025-02-18"
        SortMode="DocumentDate" OrderMode="DESC"/>
</FilterInfo>
```

---

### Шаг 5. Получение количества документов в папке

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `_download_documents_from_folder()` | `api.get_total_documents_count(folder, filtr)` | **getTotalDocumentsCount** | `login`, `password`, `folder`, `filtr` (XML) |

**Ответ:** целое число — сколько документов в данной папке попадают под фильтр.  
Если 0, папка для этого контрагента пропускается (дальнейших запросов по ней нет).

**Пример запроса (тело SOAP):**
```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <getTotalDocumentsCount xmlns="...">
      <login>user_login</login>
      <password>user_password</password>
      <folder>InWork</folder>
      <filtr><![CDATA[<?xml version="1.0" encoding="UTF-8"?>
<FilterInfo>
  <Info DocumentTypeId="" ContractorId="46" DocumentNumber=""
        DocumentDateFrom="2025-02-18" DocumentDateTo="2025-02-18"
        SortMode="DocumentDate" OrderMode="DESC"/>
</FilterInfo>]]></filtr>
    </getTotalDocumentsCount>
  </soap:Body>
</soap:Envelope>
```

**Пример ответа:**
```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <getTotalDocumentsCountResponse>42</getTotalDocumentsCountResponse>
  </soap:Body>
</soap:Envelope>
```

---

### Шаг 6. Постраничное получение списка документов

Цикл `while offset < total` с шагом `PAGE_SIZE` (100):

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `_download_documents_from_folder()` | `api.get_document_info_from_folder(folder, filtr_xml, limit, offset)` | **getDocumentInfoFromFolderByParams** | `login`, `password`, `folder`, `filtr`, `limit`, `offset` |

**Ответ:** XML со списком документов (`DocumentInfoList` → элементы `DocumentInfo` с атрибутами в т.ч. `DocumentId`, `DocumentFileName`, `DocumentDisplayName`, `DocumentDate` и др.).  
Для каждого элемента этого списка далее запрашивается полный документ и выгружаются тело и вложения.

**Пример запроса (тело SOAP):**
```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <getDocumentInfoFromFolderByParams xmlns="...">
      <login>user_login</login>
      <password>user_password</password>
      <folder>InWork</folder>
      <filtr><![CDATA[<?xml version="1.0" encoding="UTF-8"?>
<FilterInfo><Info DocumentTypeId="" ContractorId="46" DocumentNumber=""
  DocumentDateFrom="2025-02-18" DocumentDateTo="2025-02-18"
  SortMode="DocumentDate" OrderMode="DESC"/></FilterInfo>]]></filtr>
      <limit>100</limit>
      <offset>0</offset>
    </getDocumentInfoFromFolderByParams>
  </soap:Body>
</soap:Envelope>
```

**Пример ответа (фрагмент XML, возвращаемый методом):**
```xml
<?xml version="1.0" encoding="utf-8"?>
<DocumentInfoList>
  <DocumentInfo DocumentId="41" DocumentTypeId="8" DocumentFileName="Реализация №1.htm"
                DocumentDisplayName="ТОРГ12 № КФП00000001 от 2011-09-13"
                DocumentDate="2011-09-13" ContractorId="48" AuthorId="100"
                DocumentNumber="КФП00000001" IncomDateTicks="2011-09-20 18:08:33">
    <Signers SignersId="100" ShouldSign="1" Responsable="1"/>
  </DocumentInfo>
  <DocumentInfo DocumentId="18" DocumentTypeId="21" DocumentFileName="report.pdf" .../>
</DocumentInfoList>
```

---

### Шаг 7. Получение полного документа (тело + вложения)

Для каждого `DocumentId` из списка с шага 6:

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `_download_documents_from_folder()` | `api.get_document_by_id(doc_id)` | **getDocumentById** | `login`, `password`, `documentid` |

**Ответ:** XML с описанием документа, элементом `Document` (тело в base64) и элементами `Signers`.  
В `region_api.py` из этого же ответа дополнительно извлекаются вложения: парсинг узлов `.//Attachments/*`, `.//Attachment`, `.//DocumentAttachment` (если они есть в ответе API). Результат кладётся в `doc_full['body_base64']` и `doc_full['attachments']` (список словарей с `id`, `file_name`, `body_base64`).

Это **единственный запрос, из которого берутся вложения** в текущей реализации.

**Пример запроса (тело SOAP):**
```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <getDocumentById xmlns="...">
      <login>user_login</login>
      <password>user_password</password>
      <documentid>41</documentid>
    </getDocumentById>
  </soap:Body>
</soap:Envelope>
```

**Пример ответа (фрагмент XML, возвращаемый методом):**
```xml
<?xml version="1.0" encoding="utf-8"?>
<DocumentInfo>
  <Document DocumentId="41">
    JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2Jq...
  </Document>
  <Signers SignersId="100" ShouldSign="1" Responsable="1" Signed="1" Declined="0" ReasonText="">
    MIIGkgYJKoZIhvcNAQcCoIIGgzCCBn8CAQExCzAJBgUrDgMCGgUAMIIB...
  </Signers>
  <Signers SignersId="95" ShouldSign="1" Responsable="0" Signed="1" Declined="0" ReasonText="">
    MIIGkzCCBHugAwIBAgIQDdG...
  </Signers>
  <!-- Вложения (если API их возвращает): -->
  <Attachments>
    <Attachment Id="101" FileName="дополнение.xlsx">
      UEsDBBQABgAIAAAAIQBi7p1oXgEAAJAEAAATAAgAcHJpbnRlcnMv...
    </Attachment>
  </Attachments>
</DocumentInfo>
```
*(содержимое Document и Attachment — base64; в документации API явно описан только Document и Signers)*

---

### Шаг 8. Резервное получение тела документа (если в getDocumentById тела не было)

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `_download_documents_from_folder()` | `api.get_document_body(doc_id)` | **getDocumentBody** | `login`, `password`, `documentid` |

Вызывается только если после `get_document_by_id` у документа нет `body_base64`.  
**Ответ:** строка base64 с телом документа или null.  
Вложений этот метод не возвращает.

**Пример запроса (тело SOAP):**
```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <getDocumentBody xmlns="...">
      <login>user_login</login>
      <password>user_password</password>
      <documentid>41</documentid>
    </getDocumentBody>
  </soap:Body>
</soap:Envelope>
```

**Пример ответа:**
```xml
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <getDocumentBodyResponse>
      JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2Jq...
    </getDocumentBodyResponse>
  </soap:Body>
</soap:Envelope>
```
*(значение — одна строка base64 с телом документа в бинарном виде)*

---

### Шаг 9. Сохранение на диск

- **Тело документа:** если есть `body_base64` (из `getDocumentById` или `getDocumentBody`), декодируется из base64 и сохраняется в `<YYYY_MM>/REGION/EDO/` под именем на основе `DocumentFileName` (при совпадении имени добавляется timestamp).
- **Вложения:** по списку `doc_full.get('attachments', [])` для каждого элемента с непустым `body_base64` сохраняется файл в ту же папку; имя формируется как `{имя_документа}_attachment_{idx}_{имя_вложения}` (при совпадении — timestamp).

Дополнительных запросов к API при сохранении нет.

---

## 3. Порядок SOAP-запросов в виде цепочки

При одном контрагенте и одной папке с документами запросы идут так:

1. **authentification** — 1 раз за запуск.
2. **getContractors** — 1 раз за запуск.
3. Для каждой пары (контрагент, папка):
   - **getTotalDocumentsCount** — 1 раз на (контрагент, папка).
   - **getDocumentInfoFromFolderByParams** — по одному запросу на каждую страницу (каждые 100 документов).
   - Для каждого документа из списка:
     - **getDocumentById** — 1 раз на документ (отсюда берётся тело и вложения).
     - **getDocumentBody** — только если у документа не оказалось тела в ответе getDocumentById (1 запрос на такой документ).

Итого: вложения получаются **только из ответа getDocumentById**; отдельного метода «только вложения» в текущем потоке нет.

---

## 4. Итоговая таблица SOAP-операций

*Примеры XML запросов и ответов по каждой операции — в разделе 2 (пошаговый путь).*

| № | SOAP-операция | Когда вызывается | Что даёт для вложений |
|---|----------------|------------------|------------------------|
| 1 | authentification | В начале, один раз | — |
| 2 | getContractors | В начале, один раз | — |
| 3 | getTotalDocumentsCount | На каждую (контрагент, папка) | — |
| 4 | getDocumentInfoFromFolderByParams | Постранично по документам в папке | Список DocumentId (сами вложения не отдаёт) |
| 5 | getDocumentById | На каждый документ из списка | Тело документа + вложения (если API их вернул в XML) |
| 6 | getDocumentBody | Только если у документа нет тела в getDocumentById | Только тело, не вложения |

---

## 5. Файлы и конфигурация

- **Скрипт:** `region_edo_download.py`
- **Клиент API:** `region_api.py` (SOAP через zeep, WSDL из `REGION_WSDL_URL`)
- **Конфиг:** `config_region.py` — `EDO_FOLDERS`, `DEPOSITARY_DEPARTMENTS`, `DEPOSITARY_ORGANIZATIONS`; период «предыдущий день» считается по таймзоне Europe/Moscow в `_yesterday_range()`.
