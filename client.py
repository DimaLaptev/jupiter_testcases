"""HTTP-клиент (HTTP client) CASD на requests.Session."""

from __future__ import annotations

from typing import Any

import requests
import urllib3

from region_lk.config import RegionLkConfig


class CasdClientError(RuntimeError):
    """Ошибка клиента CASD."""


class CasdAuthError(CasdClientError):
    """Ошибка авторизации (authentication)."""


class CasdClient:
    def __init__(self, config: RegionLkConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.trust_env = config.trust_env
        if config.proxies is not None:
            self.session.proxies.update(config.proxies)
        self.session.headers.update({"Accept": "application/json"})
        self.session.verify = config.ssl_verify
        if not config.ssl_verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._token: str | None = None

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> CasdClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.config.base_url}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        require_auth: bool = True,
    ) -> requests.Response:
        headers: dict[str, str] = {}
        if require_auth:
            if not self._token:
                raise CasdAuthError("AuthenticateToken не установлен: сначала вызовите login()")
            headers["AuthenticateToken"] = self._token

        response = self.session.request(
            method,
            self._url(path),
            params=params,
            json=json,
            headers=headers,
            timeout=self.config.timeout,
        )
        # 401/403 на login (require_auth=False) обрабатывает auth.login — с телом ответа.
        if require_auth and response.status_code in (401, 403):
            raise CasdAuthError(
                f"Доступ запрещён (HTTP {response.status_code}) для {method} {path}"
            )
        return response

    def set_token(self, token: str) -> None:
        self._token = token
        self.session.headers["AuthenticateToken"] = token
