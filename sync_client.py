"""Синхронный (synchronous) HTTP-клиент к адаптеру (adapter) RVBCN.EGRN."""

from __future__ import annotations

import httpx

from rvbcn_egrn.auth import bearer_authorization, fetch_keycloak_token
from rvbcn_egrn.config import KeycloakConfig, SyncConfig
from rvbcn_egrn.exceptions import AdapterError, AdapterTimeoutError, AdapterUpstreamError
from rvbcn_egrn.models import AdapterErrorBody, SyncExtractRequest, SyncExtractResponse, SyncSqlQuery

# Хвост аргументов extractbaseparams — из примера документации адаптера.
# Параметризуется только КН и тип документа (xml); остальные поля — заглушки примера.
_EXTRACTBASEPARAMS_TAIL = (
    "'002001001000', true, TIMESTAMP '2022-04-05 12:00:00', '', "
    "'12312312312', '', '1212', '121212', DATE '2012-01-14', '', '', '', '', 1, "
    "'', '12121212', '', '1@1.ru', '', '', 1, '', false, "
    "'', '', '', '', '', '', '', '', DATE '0001-01-01', "
    "'', '', '', '', '', '', '', '', '', '', DATE '2012-01-14', "
    "'', '', '', '', '', '', '', 0.0, '654454'"
)


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_extractbaseparams_sql(
    cadastral_number: str,
    *,
    doc_type: str = "xml",
    extract_type: str = "extractbaseparams",
) -> str:
    """Собрать SQL для POST /query по примеру документации."""
    function = extract_type if "." in extract_type else f"egrn2.1.1.{extract_type}"
    return (
        f"select * from {function}("
        f"{_sql_str(doc_type)}, {_sql_str(cadastral_number)}, {_EXTRACTBASEPARAMS_TAIL})"
    )


class EgrnSyncClient:
    """Клиент: Keycloak Bearer + POST /query?async=false."""

    def __init__(
        self,
        config: SyncConfig,
        *,
        keycloak: KeycloakConfig | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._keycloak = keycloak
        self._token: str | None = None
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=config.timeout_seconds,
            verify=config.verify,
            follow_redirects=True,
        )

    @classmethod
    def from_keycloak(
        cls,
        config: SyncConfig,
        keycloak: KeycloakConfig,
        *,
        client: httpx.Client | None = None,
    ) -> EgrnSyncClient:
        return cls(config, keycloak=keycloak, client=client)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> EgrnSyncClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _authorization_header(self) -> str | None:
        if self._config.authorization:
            return bearer_authorization(self._config.authorization)
        if self._keycloak is None:
            return None
        if self._token is None:
            self._token = fetch_keycloak_token(self._keycloak)
        return bearer_authorization(self._token)

    def request_extract(
        self,
        cadastral_number: str,
        *,
        extract_type: str = "extractbaseparams",
        doc_type: str = "xml",
    ) -> SyncExtractResponse:
        """Запросить выписку ЕГРН по одному кадастровому номеру."""
        payload = SyncExtractRequest(
            sql=SyncSqlQuery(
                sql=build_extractbaseparams_sql(
                    cadastral_number,
                    doc_type=doc_type,
                    extract_type=extract_type,
                )
            )
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._config.accept_version:
            headers["Accept-Version"] = self._config.accept_version
        authorization = self._authorization_header()
        if authorization:
            headers["Authorization"] = authorization
        headers.update(self._config.extra_headers)

        try:
            response = self._client.post(
                self._config.request_url(),
                params=self._config.request_params(),
                json=payload.model_dump(),
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(
                f"Таймаут (timeout) при обращении к адаптеру: {exc}",
                error_code="TIMEOUT",
            ) from exc
        except httpx.HTTPError as exc:
            raise AdapterError(f"Ошибка HTTP-транспорта: {exc}") from exc

        return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> SyncExtractResponse:
        if response.status_code == 200:
            try:
                return SyncExtractResponse.model_validate(response.json())
            except Exception as exc:
                raise AdapterError(
                    f"Не удалось разобрать успешный ответ адаптера: {exc}"
                ) from exc

        error_body = self._try_error_body(response)

        if response.status_code == 504:
            raise AdapterTimeoutError(
                error_body.message or "Gateway Timeout",
                error_code=error_body.error_code or "TIMEOUT",
            )

        if response.status_code in (502, 503):
            raise AdapterUpstreamError(
                error_body.message
                or f"Ошибка upstream адаптера (HTTP {response.status_code})",
                error_code=error_body.error_code,
                status_code=response.status_code,
            )

        raise AdapterError(
            error_body.message
            or f"Неожиданный HTTP-статус адаптера: {response.status_code}: {response.text}",
            error_code=error_body.error_code or f"HTTP_{response.status_code}",
        )

    @staticmethod
    def _try_error_body(response: httpx.Response) -> AdapterErrorBody:
        try:
            data = response.json()
            if isinstance(data, dict):
                return AdapterErrorBody.model_validate(data)
        except Exception:
            pass
        return AdapterErrorBody(message=response.text or None)
