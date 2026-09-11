"""Pydantic-модели запросов/ответов RVBCN.EGRN.

Имена полей Kafka-ответа: КН + дата + UUID докстора (уточнение разработчиков).
Точная JSON Schema неизвестна — AliasChoices.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class BatchStatus(str, Enum):
    """Статус пакетного (batch) ответа (если адаптер его присылает)."""

    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class SyncExtractRequest(BaseModel):
    """Тело HTTP POST /request-egrn (синхронный сценарий)."""

    model_config = ConfigDict(populate_by_name=True)

    cadastral_number: str = Field(alias="cadastralNumber")
    extract_type: str = Field(alias="extractType", default="extractbaseparams")


class AdapterErrorBody(BaseModel):
    """Нормализованная ошибка адаптера (adapter)."""

    model_config = ConfigDict(populate_by_name=True)

    error_code: str | None = Field(default=None, alias="errorCode")
    message: str | None = None


class SyncExtractResponse(BaseModel):
    """Успешный HTTP 200: UID + структурированные поля, без raw base64."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    uid: str = Field(validation_alias=AliasChoices("uid", "UID"))
    cadastral_number: str | None = Field(default=None, alias="cadastralNumber")
    data: dict[str, Any] | None = None


class AsyncBatchRequest(BaseModel):
    """Сообщение в Kafka request-топик: массив КН.

    requestId опционален — в уточнениях разработчиков его нет.
    extractType опционален: default на стороне адаптера — основные характеристики
    и зарегистрированные права.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    cadastral_numbers: list[str] = Field(alias="cadastralNumbers")
    request_id: str | None = Field(default=None, alias="requestId")
    extract_type: str | None = Field(default=None, alias="extractType")


class ObjectError(BaseModel):
    """Ошибка по отдельному объекту в пакетном ответе."""

    model_config = ConfigDict(populate_by_name=True)

    cadastral_number: str | None = Field(default=None, alias="cadastralNumber")
    uid: str | None = Field(default=None, alias="UID")
    error_code: str | None = Field(default=None, alias="errorCode")
    message: str | None = None


class AsyncObjectResult(BaseModel):
    """Элемент ответа: КН, дата получения, UUID файла в доксторе."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    cadastral_number: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "cadastralNumber", "cadastral_number", "kn", "KN", "KH", "kh"
        ),
    )
    uuid: str | None = Field(
        default=None,
        validation_alias=AliasChoices("uuid", "UUID", "fileUuid", "fileUUID"),
    )
    received_at: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "receivedAt", "received_at", "date", "datetime", "responseTime"
        ),
    )


class BatchSummary(BaseModel):
    """Сводка по пакету (batch), если адаптер её присылает."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    object_count: int | None = Field(default=None, alias="objectCount")
    success_count: int | None = Field(default=None, alias="successCount")
    error_count: int | None = Field(default=None, alias="errorCount")


class AsyncBatchResponse(BaseModel):
    """Сообщение(я) из Kafka response-топика.

    ASSUMPTION: одно сообщение на пакет или по одному на КН (многопоток).
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    items: list[AsyncObjectResult] = Field(default_factory=list)
    request_id: str | None = Field(default=None, alias="requestId")
    status: BatchStatus | None = None
    summary: BatchSummary | None = None
    errors: list[ObjectError] = Field(default_factory=list)
    error_code: str | None = Field(default=None, alias="errorCode")
    message: str | None = None

    @property
    def uids(self) -> list[str]:
        return [item.uuid for item in self.items if item.uuid]

    def cadastral_numbers(self) -> set[str]:
        return {item.cadastral_number for item in self.items if item.cadastral_number}

    def merge(self, other: AsyncBatchResponse) -> AsyncBatchResponse:
        merged_items = list(self.items)
        seen = {(i.cadastral_number, i.uuid) for i in merged_items}
        for item in other.items:
            key = (item.cadastral_number, item.uuid)
            if key not in seen:
                merged_items.append(item)
                seen.add(key)
        return AsyncBatchResponse(
            items=merged_items,
            requestId=other.request_id or self.request_id,
            status=other.status or self.status,
            summary=other.summary or self.summary,
            errors=list(self.errors) + list(other.errors),
            errorCode=other.error_code or self.error_code,
            message=other.message or self.message,
        )

    @classmethod
    def from_payload(cls, data: Any) -> AsyncBatchResponse:
        if isinstance(data, list):
            return cls(items=[AsyncObjectResult.model_validate(row) for row in data])
        if not isinstance(data, dict):
            raise ValueError(f"Неожиданный JSON ответа Kafka: {type(data)!r}")

        for key in ("items", "results", "data", "objects"):
            nested = data.get(key)
            if isinstance(nested, list):
                base = cls.model_validate({k: v for k, v in data.items() if k != key})
                return base.model_copy(
                    update={"items": [AsyncObjectResult.model_validate(row) for row in nested]}
                )

        if _looks_like_object_result(data):
            item = AsyncObjectResult.model_validate(data)
            rest = cls.model_validate(data)
            return rest.model_copy(update={"items": [item]})

        parsed = cls.model_validate(data)
        if not parsed.items and data.get("UIDs"):
            parsed = parsed.model_copy(
                update={
                    "items": [
                        AsyncObjectResult(uuid=uid) for uid in data.get("UIDs") or []
                    ]
                }
            )
        return parsed


def _looks_like_object_result(data: dict[str, Any]) -> bool:
    keys = {str(k).lower() for k in data}
    has_kn = bool(keys & {"cadastralnumber", "cadastral_number", "kn", "kh"})
    has_uuid = bool(keys & {"uuid", "fileuuid"})
    return has_kn or has_uuid
