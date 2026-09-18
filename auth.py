"""Получение токена Keycloak для HTTP (адаптер / докстор)."""

from __future__ import annotations

import httpx

from rvbcn_egrn.config import KeycloakConfig
from rvbcn_egrn.exceptions import AdapterError

keycloak_token_url = KeycloakConfig.token_url_for


def bearer_authorization(token: str) -> str:
    """Нормализовать значение заголовка Authorization."""
    value = token.strip()
    if value.lower().startswith("bearer "):
        return value
    return f"Bearer {value}"


def fetch_keycloak_token(
    config: KeycloakConfig,
    *,
    client: httpx.Client | None = None,
) -> str:
    """POST application/x-www-form-urlencoded, возвращает access_token."""
    owns = client is None
    http = client or httpx.Client(timeout=config.timeout_seconds, verify=config.verify)
    data = {
        "grant_type": config.grant_type,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
    }
    if config.scope:
        data["scope"] = config.scope
    try:
        response = http.post(
            config.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except httpx.HTTPError as exc:
        raise AdapterError(f"Ошибка запроса токена Keycloak: {exc}") from exc
    finally:
        if owns:
            http.close()

    if response.status_code >= 400:
        raise AdapterError(
            f"Keycloak вернул HTTP {response.status_code}: {response.text}",
            error_code="KEYCLOAK_ERROR",
        )
    try:
        payload = response.json()
        token = payload.get("access_token")
    except Exception as exc:
        raise AdapterError(f"Не удалось разобрать ответ Keycloak: {exc}") from exc
    if not token:
        raise AdapterError("В ответе Keycloak нет access_token", error_code="KEYCLOAK_ERROR")
    return str(token)
