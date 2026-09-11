"""Клиент докстора ДОМа: stub без URL, иначе GET по UUID."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from rvbcn_egrn.config import DocstoreConfig
from rvbcn_egrn.exceptions import AdapterError


@dataclass(frozen=True)
class DocstoreDownload:
    """Результат скачивания (или stub, если нет base_url)."""

    uuid: str
    content: bytes | None
    stub: bool


class DocstoreClient:
    """Скачивание XML по UUID. API/роль неизвестны — без URL не ходим в сеть."""

    def __init__(
        self,
        config: DocstoreConfig | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config or DocstoreConfig()
        self._owns_client = client is None
        self._client = client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def download(self, file_uuid: str) -> DocstoreDownload:
        if not self._config.base_url:
            return DocstoreDownload(uuid=file_uuid, content=None, stub=True)

        http = self._ensure_client()
        url = f"{self._config.base_url.rstrip('/')}/{file_uuid}"
        headers: dict[str, str] = {}
        if self._config.authorization:
            headers["Authorization"] = self._config.authorization
        try:
            response = http.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise AdapterError(f"Ошибка скачивания из докстора: {exc}") from exc
        if response.status_code >= 400:
            raise AdapterError(
                f"Докстор вернул HTTP {response.status_code} для {file_uuid}",
                error_code="DOCSTORE_ERROR",
            )
        return DocstoreDownload(uuid=file_uuid, content=response.content, stub=False)

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._config.timeout_seconds)
        return self._client
