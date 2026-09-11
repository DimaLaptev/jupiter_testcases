"""Конфигурация (config) клиента RVBCN.EGRN.

ASSUMPTION: имена JSON-полей и корреляция без requestId — по уточнениям
разработчиков; точная Schema всё ещё неизвестна.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SyncConfig:
    """Конфиг (config) синхронного (synchronous) HTTP-клиента."""

    # ASSUMPTION: base URL адаптера без завершающего слэша (хост rr-rvbcn-service)
    base_url: str
    # ASSUMPTION: путь из диаграммы последовательности
    path: str = "/request-egrn"
    # ASSUMPTION: 30 с у адаптера до агента ПОДД + запас на сеть
    timeout_seconds: float = 35.0
    # Bearer-токен Keycloak (если получен)
    authorization: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)

    def request_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.path}"


@dataclass(frozen=True)
class KeycloakConfig:
    """Конфиг (config) получения токена Keycloak. URL замазан — из env."""

    token_url: str
    client_id: str
    client_secret: str
    grant_type: str = "client_credentials"
    timeout_seconds: float = 15.0


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
