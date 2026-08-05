"""Документы (documents) заказа и сохранение содержимого из Base64."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from region_lk.client import CasdClient, CasdClientError

PAGE_SIZE = 250
_INVALID_WIN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class DocumentRef:
    file_id: int
    original_name: str
    extension: str | None
    size: int | None


def sanitize_filename(name: str) -> str:
    cleaned = _INVALID_WIN_CHARS.sub("_", name).strip().rstrip(".")
    return cleaned or "file"


def build_filename(doc: DocumentRef) -> str:
    original = (doc.original_name or "").strip()
    if original:
        return sanitize_filename(original)

    ext = (doc.extension or "").lstrip(".")
    if ext:
        return sanitize_filename(f"document_{doc.file_id}.{ext}")
    return sanitize_filename(f"document_{doc.file_id}")


def unique_path(directory: Path, filename: str, file_id: int) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    return directory / f"{stem}_{file_id}{suffix}"


def fetch_order_documents(
    client: CasdClient,
    order_id: int,
    *,
    page_size: int = PAGE_SIZE,
) -> list[DocumentRef]:
    """
    GET /API/CASD/Users/Current/Orders/{orderId}/Documents с пагинацией.
    documentId для скачивания = File.Id.
    """
    documents: list[DocumentRef] = []
    page = 0

    while True:
        response = client.request(
            "GET",
            f"/API/CASD/Users/Current/Orders/{order_id}/Documents",
            params={"page": page, "countToPage": page_size},
        )
        if response.status_code != 200:
            raise CasdClientError(
                f"Не удалось получить документы заказа {order_id}: "
                f"HTTP {response.status_code} {response.text[:300]}"
            )

        data = response.json()
        items = data.get("List") or []
        count_elements = int(data.get("CountElements") or 0)

        for item in items:
            file_obj = item.get("File") or {}
            file_id = file_obj.get("Id")
            if file_id is None:
                continue
            documents.append(
                DocumentRef(
                    file_id=int(file_id),
                    original_name=str(file_obj.get("OriginalName") or ""),
                    extension=(
                        str(file_obj["Extension"])
                        if file_obj.get("Extension") is not None
                        else None
                    ),
                    size=int(file_obj["Size"]) if file_obj.get("Size") is not None else None,
                )
            )

        if not items:
            break
        if len(items) < page_size:
            break
        if count_elements and (page + 1) * page_size >= count_elements:
            break
        page += 1

    return documents


def download_document_bytes(client: CasdClient, order_id: int, document_id: int) -> bytes:
    """
    GET /API/CASD/Orders/{orderId}/Documents/{documentId}
    → JSON Value (Base64) → bytes.
    """
    response = client.request(
        "GET",
        f"/API/CASD/Orders/{order_id}/Documents/{document_id}",
    )
    if response.status_code != 200:
        raise CasdClientError(
            f"Не удалось скачать документ {document_id} заказа {order_id}: "
            f"HTTP {response.status_code} {response.text[:300]}"
        )

    payload: dict[str, Any] = response.json()
    value = payload.get("Value")
    if value is None:
        raise CasdClientError(
            f"В ответе нет поля Value для документа {document_id} заказа {order_id}"
        )
    return base64.b64decode(value)


def save_document(
    client: CasdClient,
    order_id: int,
    doc: DocumentRef,
    order_dir: Path,
) -> tuple[Path, str]:
    """
    Скачивает документ и сохраняет в order_dir.
    Возвращает (path, status): saved | saved_renamed | skipped.
    """
    order_dir.mkdir(parents=True, exist_ok=True)
    filename = build_filename(doc)
    original_path = order_dir / filename

    if original_path.exists() and doc.size is not None and original_path.stat().st_size == doc.size:
        return original_path, "skipped"

    raw = download_document_bytes(client, order_id, doc.file_id)

    if original_path.exists() and original_path.stat().st_size == len(raw):
        return original_path, "skipped"

    if original_path.exists():
        target = unique_path(order_dir, filename, doc.file_id)
        if target.exists() and target.stat().st_size == len(raw):
            return target, "skipped"
        target.write_bytes(raw)
        return target, "saved_renamed"

    original_path.write_bytes(raw)
    return original_path, "saved"
