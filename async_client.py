"""Асинхронный (asynchronous) Kafka-клиент к адаптеру (adapter) RVBCN.EGRN."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Protocol

from rvbcn_egrn.config import AsyncConfig
from rvbcn_egrn.exceptions import (
    AdapterBatchFailedError,
    AdapterError,
    AdapterPartialResultError,
    AdapterTimeoutError,
)
from rvbcn_egrn.models import AsyncBatchRequest, AsyncBatchResponse, BatchStatus


class _KafkaProducer(Protocol):
    def send(self, topic: str, value: bytes, key: bytes | None = None) -> Any: ...

    def flush(self, timeout: float | None = None) -> None: ...

    def close(self) -> None: ...


class _KafkaConsumer(Protocol):
    def poll(self, timeout_ms: int = ...) -> dict[Any, list[Any]]: ...

    def close(self) -> None: ...

    def subscribe(self, topics: list[str]) -> None: ...


class EgrnAsyncClient:
    """Клиент (client): produce массив КН в Kafka + ожидание ответов по КН."""

    def __init__(
        self,
        config: AsyncConfig,
        *,
        producer: _KafkaProducer | None = None,
        consumer: _KafkaConsumer | None = None,
    ) -> None:
        self._config = config
        self._owns_producer = producer is None
        self._owns_consumer = consumer is None
        self._producer = producer
        self._consumer = consumer

    def _ensure_producer(self) -> _KafkaProducer:
        if self._producer is None:
            from kafka import KafkaProducer

            kwargs: dict[str, Any] = {
                "bootstrap_servers": self._config.bootstrap_servers,
                "acks": "all",
                **self._config.kafka_config,
            }
            self._producer = KafkaProducer(**kwargs)
        return self._producer

    def _ensure_consumer(self) -> _KafkaConsumer:
        if self._consumer is None:
            from kafka import KafkaConsumer

            kwargs: dict[str, Any] = {
                "bootstrap_servers": self._config.bootstrap_servers,
                "group_id": self._config.group_id,
                "enable_auto_commit": True,
                "auto_offset_reset": "earliest",
                **self._config.kafka_config,
            }
            consumer = KafkaConsumer(**kwargs)
            consumer.subscribe([self._config.response_topic])
            self._consumer = consumer
        return self._consumer

    def close(self) -> None:
        if self._owns_producer and self._producer is not None:
            self._producer.close()
            self._producer = None
        if self._owns_consumer and self._consumer is not None:
            self._consumer.close()
            self._consumer = None

    def __enter__(self) -> EgrnAsyncClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def submit_batch(
        self,
        cadastral_numbers: list[str],
        *,
        request_id: str | None = None,
        extract_type: str | None = None,
    ) -> list[str]:
        """Опубликовать массив КН в Kafka. Возвращает список КН (как ключ корреляции)."""
        if not cadastral_numbers:
            raise AdapterError("Список cadastralNumbers не должен быть пустым")

        message = AsyncBatchRequest(
            cadastralNumbers=cadastral_numbers,
            requestId=request_id,
            extractType=extract_type,
        )
        body = message.model_dump(by_alias=True, exclude_none=True)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        key = (request_id or cadastral_numbers[0]).encode("utf-8")

        producer = self._ensure_producer()
        future = producer.send(self._config.request_topic, value=payload, key=key)
        try:
            future.get(timeout=30)
        except Exception as exc:
            raise AdapterError(f"Не удалось опубликовать сообщение в Kafka: {exc}") from exc
        producer.flush(timeout=30)
        return list(cadastral_numbers)

    def wait_result(
        self,
        cadastral_numbers: list[str],
        *,
        request_id: str | None = None,
        timeout_seconds: float | None = None,
        raise_on_partial: bool = False,
    ) -> AsyncBatchResponse:
        """Читать response-топик, пока не появятся все запрошенные КН (или timeout)."""
        wanted = set(cadastral_numbers)
        if not wanted:
            raise AdapterError("Список кадастровых номеров для ожидания пуст")

        deadline = time.monotonic() + (
            timeout_seconds
            if timeout_seconds is not None
            else self._config.wait_timeout_seconds
        )
        consumer = self._ensure_consumer()
        poll_ms = int(self._config.poll_timeout_seconds * 1000)
        collected = AsyncBatchResponse()

        while time.monotonic() < deadline:
            remaining_ms = int(max(0.0, (deadline - time.monotonic()) * 1000))
            if remaining_ms == 0:
                break
            records = consumer.poll(timeout_ms=min(poll_ms, remaining_ms))
            for _tp, messages in records.items():
                for msg in messages:
                    parsed = self._parse_message(msg.value)
                    if parsed is None:
                        continue
                    if request_id and parsed.request_id and parsed.request_id != request_id:
                        continue
                    filtered = self._filter_wanted(parsed, wanted)
                    if filtered is None:
                        continue
                    collected = collected.merge(filtered)
                    if wanted <= collected.cadastral_numbers():
                        return self._handle_status(
                            collected, raise_on_partial=raise_on_partial
                        )

        missing = wanted - collected.cadastral_numbers()
        raise AdapterTimeoutError(
            f"Таймаут ожидания ответа Kafka, нет КН: {sorted(missing)}",
            error_code="TIMEOUT",
        )

    def submit_and_wait(
        self,
        cadastral_numbers: list[str],
        *,
        request_id: str | None = None,
        extract_type: str | None = None,
        timeout_seconds: float | None = None,
        raise_on_partial: bool = False,
    ) -> AsyncBatchResponse:
        """Опубликовать batch и дождаться ответов по всем КН."""
        self.submit_batch(
            cadastral_numbers,
            request_id=request_id,
            extract_type=extract_type,
        )
        return self.wait_result(
            cadastral_numbers,
            request_id=request_id,
            timeout_seconds=timeout_seconds,
            raise_on_partial=raise_on_partial,
        )

    @staticmethod
    def _filter_wanted(
        parsed: AsyncBatchResponse,
        wanted: set[str],
    ) -> AsyncBatchResponse | None:
        if not parsed.items:
            return parsed
        relevant = [
            item
            for item in parsed.items
            if item.cadastral_number is None or item.cadastral_number in wanted
        ]
        known = [item.cadastral_number for item in parsed.items if item.cadastral_number]
        if known and not relevant:
            return None
        if known and not any(kn in wanted for kn in known):
            return None
        return parsed.model_copy(update={"items": relevant})

    @staticmethod
    def _parse_message(raw: bytes | str | None) -> AsyncBatchResponse | None:
        if raw is None:
            return None
        try:
            if isinstance(raw, bytes):
                text = raw.decode("utf-8")
            else:
                text = raw
            data = json.loads(text)
            return AsyncBatchResponse.from_payload(data)
        except Exception:
            return None

    @staticmethod
    def _handle_status(
        result: AsyncBatchResponse,
        *,
        raise_on_partial: bool,
    ) -> AsyncBatchResponse:
        if result.status == BatchStatus.FAILED:
            code = result.error_code or "FAILED"
            raise AdapterBatchFailedError(
                result.message or f"Пакетный запрос завершился со status=FAILED ({code})",
                error_code=code,
            )
        if result.status == BatchStatus.PARTIAL and raise_on_partial:
            raise AdapterPartialResultError(
                result.message or "Пакетный запрос завершился со status=PARTIAL",
                result=result,
            )
        return result


def new_request_id() -> str:
    return str(uuid.uuid4())
