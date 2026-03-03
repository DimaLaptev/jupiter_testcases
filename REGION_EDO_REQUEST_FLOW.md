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

---

### Шаг 2. Получение контрагентов (депозитариев)

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `main()` → `_resolve_contractor_ids(api, DEPOSITARY_DEPARTMENTS, DEPOSITARY_ORGANIZATIONS)` | `api.get_contractors()` | **getContractors** | `login`, `password` |

**Ответ:** XML со списком контрагентов (`ContractorsList` → элементы `Contractors` с атрибутами `ContractorId`, `DisplayName`).  
Дальше в коде по этому списку отбираются депозитарии (сопоставление по подразделению/организации), формируется словарь `{ DisplayName: ContractorId }`. Дополнительных запросов к API на этом шаге нет.

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

---

### Шаг 5. Получение количества документов в папке

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `_download_documents_from_folder()` | `api.get_total_documents_count(folder, filtr)` | **getTotalDocumentsCount** | `login`, `password`, `folder`, `filtr` (XML) |

**Ответ:** целое число — сколько документов в данной папке попадают под фильтр.  
Если 0, папка для этого контрагента пропускается (дальнейших запросов по ней нет).

---

### Шаг 6. Постраничное получение списка документов

Цикл `while offset < total` с шагом `PAGE_SIZE` (100):

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `_download_documents_from_folder()` | `api.get_document_info_from_folder(folder, filtr_xml, limit, offset)` | **getDocumentInfoFromFolderByParams** | `login`, `password`, `folder`, `filtr`, `limit`, `offset` |

**Ответ:** XML со списком документов (`DocumentInfoList` → элементы `DocumentInfo` с атрибутами в т.ч. `DocumentId`, `DocumentFileName`, `DocumentDisplayName`, `DocumentDate` и др.).  
Для каждого элемента этого списка далее запрашивается полный документ и выгружаются тело и вложения.

---

### Шаг 7. Получение полного документа (тело + вложения)

Для каждого `DocumentId` из списка с шага 6:

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `_download_documents_from_folder()` | `api.get_document_by_id(doc_id)` | **getDocumentById** | `login`, `password`, `documentid` |

**Ответ:** XML с описанием документа, элементом `Document` (тело в base64) и элементами `Signers`.  
В `region_api.py` из этого же ответа дополнительно извлекаются вложения: парсинг узлов `.//Attachments/*`, `.//Attachment`, `.//DocumentAttachment` (если они есть в ответе API). Результат кладётся в `doc_full['body_base64']` и `doc_full['attachments']` (список словарей с `id`, `file_name`, `body_base64`).

Это **единственный запрос, из которого берутся вложения** в текущей реализации.

---

### Шаг 8. Резервное получение тела документа (если в getDocumentById тела не было)

| Где в коде | Метод Python | SOAP-операция | Параметры |
|------------|--------------|---------------|-----------|
| `_download_documents_from_folder()` | `api.get_document_body(doc_id)` | **getDocumentBody** | `login`, `password`, `documentid` |

Вызывается только если после `get_document_by_id` у документа нет `body_base64`.  
**Ответ:** строка base64 с телом документа или null.  
Вложений этот метод не возвращает.

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
