#!/usr/bin/env python3
"""GET /API/CASD/Users/Current/Organizations/{organizationId}/AccountsSections

Токен вставьте как константу AUTHENTICATE_TOKEN.

  python scripts/test_casd_accounts_sections.py
"""

from __future__ import annotations

import json
import sys

import requests

# --- заполните вручную ---
BASE_URL = "http://lk-test.region-dk.ru"
AUTHENTICATE_TOKEN = "xxxxxxxx"

PROXY_URL = "http://127.0.0.1:3128"
PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL,
}

TIMEOUT = 30
SSL_VERIFY = True

ORGANIZATION_ID = 13

# Query как в браузере / Swagger
PAGE = 0
COUNT_TO_PAGE = 10
ADD_EMPTY_SECTIONS = False
SORT_BY = ""
SORTING_DIRECTION = "ASC"

# Опциональные фильтры Swagger (None = не передавать)
ACCOUNT_NUMBER = None
ACCOUNT_TYPE_CODE = None
NAME = None
SECTION_NUMBER = None
SECTION_NAME = None
SECTION_SECURITY_TYPE_ID = None  # 0 в Swagger = не фильтр; None не шлём
SECTION_PURPOSE_ID = None
CHANGED_DATE_FROM = None  # строка, как в API
CHANGED_DATE_TO = None
# -------------------------

PATH = f"/API/CASD/Users/Current/Organizations/{ORGANIZATION_ID}/AccountsSections"


def _params() -> dict[str, str | int | bool]:
    params: dict[str, str | int | bool] = {
        "page": PAGE,
        "countToPage": COUNT_TO_PAGE,
        "addEmptySections": ADD_EMPTY_SECTIONS,
        "sortBy": SORT_BY,
        "sortingDirection": SORTING_DIRECTION,
    }
    optional = {
        "accountNumber": ACCOUNT_NUMBER,
        "accountTypeCode": ACCOUNT_TYPE_CODE,
        "name": NAME,
        "sectionNumber": SECTION_NUMBER,
        "sectionName": SECTION_NAME,
        "sectionSecurityTypeId": SECTION_SECURITY_TYPE_ID,
        "sectionPurposeId": SECTION_PURPOSE_ID,
        "changedDateFrom": CHANGED_DATE_FROM,
        "changedDateTo": CHANGED_DATE_TO,
    }
    for key, value in optional.items():
        if value is not None and value != "":
            params[key] = value
    return params


def main() -> int:
    url = f"{BASE_URL.rstrip('/')}{PATH}"
    headers = {
        "Accept": "application/json",
        "AuthenticateToken": AUTHENTICATE_TOKEN,
    }
    params = _params()

    print(f"URL:     {url}")
    print(f"Proxy:   {PROXY_URL}")
    print(f"Token:   задан, длина {len(AUTHENTICATE_TOKEN)}")
    print(f"Params:  {params}")
    print("---")

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            proxies=PROXIES,
            timeout=TIMEOUT,
            verify=SSL_VERIFY,
        )
    except requests.RequestException as exc:
        print(f"NETWORK ERROR: {exc}")
        return 1

    print(f"Status:  {response.status_code}")
    print("Response headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    print("---")

    text = response.text or ""
    try:
        payload = response.json()
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
        if isinstance(payload, dict):
            items = payload.get("List") or []
            print("---")
            print(f"Page={payload.get('Page')} CountToPage={payload.get('CountToPage')} "
                  f"CountElements={payload.get('CountElements')} List={len(items)}")
    except ValueError:
        print(text[:2000])

    if response.status_code != 200:
        print(f"FAIL: HTTP {response.status_code}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
