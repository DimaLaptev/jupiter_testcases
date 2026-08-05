"""Авторизация (authentication) в ЛК Region."""

from __future__ import annotations

from region_lk.client import CasdAuthError, CasdClient


def extract_authenticate_token(headers: dict[str, str] | object) -> str | None:
    """Достаёт AuthenticateToken из headers (case-insensitive)."""
    items = getattr(headers, "items", None)
    if not callable(items):
        return None
    for key, value in items():
        if str(key).lower() == "authenticatetoken" and value:
            return str(value).strip()
    return None


def login(client: CasdClient, email: str | None = None, password: str | None = None) -> str:
    """
    POST /API/UsersCP/Tokens → токен из response header AuthenticateToken.
    """
    email = (email if email is not None else client.config.email).strip()
    password = password if password is not None else client.config.password
    if not email or not password:
        raise CasdAuthError(
            "Не заданы учётные данные: REGION_LK_EMAIL / REGION_LK_PASSWORD"
        )

    response = client.request(
        "POST",
        "/API/UsersCP/Tokens",
        json={"Email": email, "Password": password},
        require_auth=False,
    )
    if response.status_code != 200:
        raise CasdAuthError(
            f"Авторизация не удалась: HTTP {response.status_code} {response.text[:300]}"
        )

    token = extract_authenticate_token(response.headers)
    if not token:
        raise CasdAuthError(
            "HTTP 200, но заголовок AuthenticateToken отсутствует в ответе"
        )

    client.set_token(token)
    return token
