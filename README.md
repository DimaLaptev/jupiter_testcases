# CASD / ЛК Region — скачивание вложений

CLI: [`scripts/casd_download_attachments.py`](../scripts/casd_download_attachments.py)  
Пакет: [`src/region_lk/`](../src/region_lk/)

## Запуск

```bash
set REGION_LK_EMAIL=user@example.com
set REGION_LK_PASSWORD=secret
python scripts/casd_download_attachments.py --out-dir ./casd_downloads
```

Опционально: `--base-url https://lk.region-dk.ru`, `--timeout 60`.

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `REGION_LK_BASE_URL` | По умолчанию `https://lk-test.region-dk.ru` |
| `REGION_LK_EMAIL` / `REGION_LK_PASSWORD` | Учётка ЛК |
| `REGION_LK_HTTP_PROXY` | Явный прокси, например `http://127.0.0.1:3128` |
| `REGION_LK_PROXY_USER` / `REGION_LK_PROXY_PASSWORD` | Auth прокси |
| `REGION_LK_NO_PROXY` | `1` — не использовать системный прокси (по умолчанию, если нет явного) |
| `REGION_LK_USE_SYSTEM_PROXY` | `1` — доверять системным `HTTP(S)_PROXY` |
| `REGION_LK_SSL_VERIFY` | `0`/`false` — отключить проверку SSL (только отладка) |
| `REGION_LK_TIMEOUT` | Таймаут секунд (по умолчанию 30) |

## Результат

```text
casd_downloads/
  {Num}/
    {OriginalName}
```

Заказы без документов пропускаются. Ошибка одного файла не останавливает остальные.
