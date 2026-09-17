"""Живой синхронный запрос: токен Keycloak + POST /query?async=false.

    python -m rvbcn_egrn

Читает .env / переменные окружения (см. .env.example).
"""

from __future__ import annotations

import sys

from rvbcn_egrn.env import env_csv, keycloak_from_env, load_dotenv, sync_from_env
from rvbcn_egrn.exceptions import AdapterError
from rvbcn_egrn.sync_client import EgrnSyncClient


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    kns = list(argv[1:] if argv is not None else sys.argv[1:])
    if not kns:
        kns = env_csv("RVBCN_TEST_CAD_NUMBERS")
    if not kns:
        print(
            "Укажите кадастровый номер: python -m rvbcn_egrn 49:09:040101:1253",
            file=sys.stderr,
        )
        return 2

    keycloak = keycloak_from_env()
    if keycloak is None:
        print(
            "Нет Keycloak: задайте RVBCN_KK_CLIENT_ID, RVBCN_KK_CLIENT_SECRET "
            "и RVBCN_KK_TOKEN_URL либо RVBCN_KK_BASE_URL + RVBCN_KK_REALM",
            file=sys.stderr,
        )
        return 2

    sync = sync_from_env()
    if sync is None:
        print("Нет RVBCN_BASE_URL", file=sys.stderr)
        return 2

    cadastral_number = kns[0]
    print(f"Keycloak token URL: {keycloak.token_url}")
    print(f"POST {sync.request_url()} async={sync.async_query}")
    print(f"КН: {cadastral_number}")
    if sync.verify is False:
        print("TLS verify=False (просроченный сертификат тестового контура)")

    try:
        with EgrnSyncClient.from_keycloak(sync, keycloak) as client:
            result = client.request_extract(cadastral_number)
    except AdapterError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    print(f"query_id: {result.query_id}")
    print(f"created_at: {result.created_at}")
    print(f"docType: {result.doc_type}")
    print(f"fileName: {result.file_name}")
    content = result.content_bytes()
    if content is None:
        print("content: пусто")
        return 1
    print(f"content: {len(content)} байт")
    preview = content.decode("utf-8", errors="replace").splitlines()[:5]
    for line in preview:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
