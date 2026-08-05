"""Конфигурация (configuration) клиента ЛК из переменных окружения (environment variables)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote, urlparse


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _proxy_url_with_auth(proxy_url: str, user: str, password: str) -> str:
    if not user:
        return proxy_url
    parsed = urlparse(proxy_url)
    if parsed.username:
        return proxy_url
    auth = quote(user, safe="")
    if password:
        auth = f"{auth}:{quote(password, safe='')}"
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{auth}@{host}{port}{parsed.path or ''}"


@dataclass(frozen=True)
class RegionLkConfig:
    base_url: str
    email: str
    password: str
    timeout: float
    ssl_verify: bool
    proxies: dict[str, str] | None
    trust_env: bool

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> RegionLkConfig:
        use_system = env_flag("REGION_LK_USE_SYSTEM_PROXY")
        no_proxy = env_flag("REGION_LK_NO_PROXY", default=not use_system)

        proxy_url = (
            os.environ.get("REGION_LK_HTTP_PROXY", "").strip()
            or os.environ.get("HTTPS_PROXY", "").strip()
            or os.environ.get("HTTP_PROXY", "").strip()
        )
        proxy_user = os.environ.get("REGION_LK_PROXY_USER", "").strip()
        proxy_password = os.environ.get("REGION_LK_PROXY_PASSWORD", "")

        proxies: dict[str, str] | None
        trust_env: bool

        if no_proxy and not proxy_url:
            proxies = {}
            trust_env = False
        elif proxy_url:
            full = _proxy_url_with_auth(proxy_url, proxy_user, proxy_password)
            proxies = {"http": full, "https": full}
            trust_env = False
        elif use_system:
            proxies = None
            trust_env = True
        else:
            proxies = {}
            trust_env = False

        return cls(
            base_url=(
                base_url
                or os.environ.get("REGION_LK_BASE_URL", "").strip()
                or "https://lk-test.region-dk.ru"
            ).rstrip("/"),
            email=os.environ.get("REGION_LK_EMAIL", "").strip(),
            password=os.environ.get("REGION_LK_PASSWORD", ""),
            timeout=float(timeout if timeout is not None else os.environ.get("REGION_LK_TIMEOUT", "30")),
            ssl_verify=env_flag("REGION_LK_SSL_VERIFY", default=True),
            proxies=proxies,
            trust_env=trust_env,
        )
