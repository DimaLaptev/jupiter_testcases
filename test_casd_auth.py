
"""Тест аутентификации ЛК Region на requests.

  python scripts/test_casd_auth.py
"""

from __future__ import annotations

import sys

import requests

# --- заполните вручную ---
BASE_URL = "http://lk-test.region-dk.ru"
EMAIL = "xxx@xx.ru"
PASSWORD = "xxx"

PROXY_URL = "http://127.0.0.1:3128"
PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL,
}

TIMEOUT = 30
# Для http:// обычно не нужен; для https за MITM-прокси поставьте False
SSL_VERIFY = True
# -------------------------

AUTH_PATH = "/API/UsersCP/Tokens"


def main() -> int:
    url = f"{BASE_URL.rstrip('/')}{AUTH_PATH}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body = {"Email": EMAIL, "Password": PASSWORD}

    print(f"URL:     {url}")
    print(f"Proxy:   {PROXY_URL}")
    print(f"Email:   {EMAIL}")
    print("Password: (задано, длина", len(PASSWORD), ")")
    print("---")

    try:
        response = requests.post(
            url,
            json=body,
            headers=headers,
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

    token = None
    for key, value in response.headers.items():
        if key.lower() == "authenticatetoken" and value:
            token = value.strip()
            break

    print("---")
    if response.status_code != 200:
        print(f"AUTH FAIL: HTTP {response.status_code}")
        print(f"Body (first 500): {response.text[:500]}")
        return 1

    if not token:
        print("AUTH FAIL: HTTP 200, но AuthenticateToken в headers нет")
        print(f"Body (first 500): {response.text[:500]}")
        return 1

    print("AUTH OK")
    print(f"AuthenticateToken length: {len(token)}")
    print(f"AuthenticateToken: {token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
