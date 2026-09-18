"""Чтение настроек из окружения / .env для живого прогона."""

from __future__ import annotations

import os
from pathlib import Path

from rvbcn_egrn.config import KeycloakConfig, SyncConfig


def load_dotenv(*paths: Path) -> None:
    """Подставить KEY=VAL из .env, не перетирая уже заданные переменные."""
    candidates = list(paths) or [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        for raw in resolved.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def env_csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def keycloak_from_env() -> KeycloakConfig | None:
    client_id = os.getenv("RVBCN_KK_CLIENT_ID", "").strip()
    client_secret = os.getenv("RVBCN_KK_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None

    token_url = os.getenv("RVBCN_KK_TOKEN_URL", "").strip()
    context_path = os.getenv("RVBCN_KK_CONTEXT_PATH", "/auth")
    port_raw = os.getenv("RVBCN_KK_PORT", "").strip()
    port = int(port_raw) if port_raw else None
    if not token_url:
        base = os.getenv("RVBCN_KK_BASE_URL", "").strip()
        realm = os.getenv("RVBCN_KK_REALM", "").strip()
        if not base or not realm:
            return None
        token_url = KeycloakConfig.token_url_for(
            base, realm, context_path=context_path, port=port
        )

    scope_raw = os.getenv("RVBCN_KK_SCOPE", "openid")
    scope = scope_raw.strip() or None
    verify = env_bool("RVBCN_KK_TLS_VERIFY", env_bool("RVBCN_TLS_VERIFY", False))
    return KeycloakConfig(
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
        verify=verify,
    )


def sync_from_env(*, authorization: str | None = None) -> SyncConfig | None:
    base_url = os.getenv("RVBCN_BASE_URL", "").strip()
    if not base_url:
        return None
    timeout_raw = os.getenv("RVBCN_TIMEOUT", "").strip()
    timeout = float(timeout_raw) if timeout_raw else 35.0
    auth = authorization or os.getenv("RVBCN_AUTH") or None
    return SyncConfig(
        base_url=base_url,
        path=os.getenv("RVBCN_PATH", "/query"),
        authorization=auth,
        verify=env_bool("RVBCN_TLS_VERIFY", False),
        timeout_seconds=timeout,
    )
