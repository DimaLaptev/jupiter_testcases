"""Конфигурация (config) клиента RVBCN.EGRN.

ASSUMPTION: имена JSON-полей и корреляция без requestId — по уточнениям
разработчиков; точная Schema всё ещё неизвестна.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SyncConfig:
    """Конфиг (config) синхронного (synchronous) HTTP-клиента.

    Контракт со скрина документации: POST /query?async=false,
    заголовок Accept-Version: 1, тело SQL extractbaseparams.
    """

    base_url: str
    path: str = "/query"
    async_query: bool = False
    # 30 с у адаптера до агента ПОДД + запас на сеть
    timeout_seconds: float = 35.0
    # Bearer-токен Keycloak (если уже получен снаружи)
    authorization: str | None = None
    accept_version: str | None = "1"
    # Тестовый контур часто с просроченным сертификатом — тогда False
    verify: bool | str = True
    extra_headers: dict[str, str] = field(default_factory=dict)

    def request_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.path}"

    def request_params(self) -> dict[str, str] | None:
        if "?" in self.path:
            return None
        return {"async": "true" if self.async_query else "false"}


@dataclass(frozen=True)
class KeycloakConfig:
    """Конфиг (config) получения токена Keycloak.

    Рабочий контур: POST {host}:443/auth/realms/{realm}/protocol/openid-connect/token
    с grant_type=client_credentials и scope=openid.
    """

    token_url: str
    client_id: str
    client_secret: str
    grant_type: str = "client_credentials"
    scope: str | None = "openid"
    timeout_seconds: float = 15.0
    verify: bool | str = True

    @staticmethod
    def token_url_for(
        base_url: str,
        realm: str,
        *,
        context_path: str = "/auth",
        port: int | None = None,
    ) -> str:
        base = base_url.strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = f"https://{base}"
        scheme, _, rest = base.partition("://")
        host = rest
        if port is not None and ":" not in host.rsplit("@", 1)[-1]:
            host = f"{host}:{port}"
        prefix = context_path.strip("/")
        mid = f"/{prefix}" if prefix else ""
        return f"{scheme}://{host}{mid}/realms/{realm}/protocol/openid-connect/token"

    @classmethod
    def from_parts(
        cls,
        base_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
        *,
        grant_type: str = "client_credentials",
        scope: str | None = "openid",
        context_path: str = "/auth",
        port: int | None = None,
        timeout_seconds: float = 15.0,
        verify: bool | str = True,
    ) -> KeycloakConfig:
        return cls(
            token_url=cls.token_url_for(
                base_url, realm, context_path=context_path, port=port
            ),
            client_id=client_id,
            client_secret=client_secret,
            grant_type=grant_type,
            scope=scope,
            timeout_seconds=timeout_seconds,
            verify=verify,
        )


@dataclass(frozen=True)
class DocstoreConfig:
    """Конфиг (config) докстора ДОМа. Роль и API неизвестны — stub без base_url."""

    base_url: str | None = None
    authorization: str | None = None
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class AsyncConfig:
    """Конфиг (config) асинхронного (asynchronous) Kafka-клиента."""

    bootstrap_servers: str
    # Подтверждено разработчиками
    request_topic: str = "topic.icb.rvbcn.kd-request"
    response_topic: str = "topic.icb.rvbcn.kd-response"
    group_id: str = "rvbcn-egrn-consumer"
    wait_timeout_seconds: float = 150.0
    poll_timeout_seconds: float = 1.0
    # ASSUMPTION: SASL только если явно задан (токен KK — для HTTP)
    kafka_config: dict[str, object] = field(default_factory=dict)
