"""Публичный API пакета rvbcn_egrn."""

from rvbcn_egrn.async_client import EgrnAsyncClient
from rvbcn_egrn.auth import fetch_keycloak_token
from rvbcn_egrn.config import AsyncConfig, DocstoreConfig, KeycloakConfig, SyncConfig
from rvbcn_egrn.docstore import DocstoreClient, DocstoreDownload
from rvbcn_egrn.exceptions import (
    AdapterBatchFailedError,
    AdapterError,
    AdapterPartialResultError,
    AdapterTimeoutError,
    AdapterUpstreamError,
)
from rvbcn_egrn.models import (
    AsyncBatchRequest,
    AsyncBatchResponse,
    AsyncObjectResult,
    BatchStatus,
    SyncExtractRequest,
    SyncExtractResponse,
)
from rvbcn_egrn.sync_client import EgrnSyncClient

__all__ = [
    "AdapterBatchFailedError",
    "AdapterError",
    "AdapterPartialResultError",
    "AdapterTimeoutError",
    "AdapterUpstreamError",
    "AsyncBatchRequest",
    "AsyncBatchResponse",
    "AsyncConfig",
    "AsyncObjectResult",
    "BatchStatus",
    "DocstoreClient",
    "DocstoreConfig",
    "DocstoreDownload",
    "EgrnAsyncClient",
    "EgrnSyncClient",
    "KeycloakConfig",
    "SyncConfig",
    "SyncExtractRequest",
    "SyncExtractResponse",
    "fetch_keycloak_token",
]
