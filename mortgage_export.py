"""Экспорт закладных (Mortgages Export) в Excel через CASD API."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from region_lk.client import CasdClient, CasdClientError

# По наблюдениям UI: StatusId=2 и ExecutedDate заполнены → экспорт готов.
DEFAULT_READY_STATUS_IDS = frozenset({2})

DEFAULT_EXPORT_BODY: dict[str, bool] = {
    "addWithoutDrafts": True,
    "addCurrentUserDrafts": True,
    "addOtherUsersDrafts": True,
    "addIncludedInOrders": True,
}


@dataclass(frozen=True)
class ExportStatus:
    account_id: int
    section_id: int
    user_id: int | None
    filter_id: int | None
    status_id: int | None
    data: str | None
    created_date: str | None
    executed_date: str | None
    raw: dict[str, Any]


def export_path(account_id: int, section_id: int) -> str:
    return f"/API/CASD/Export/Mortgages/Accounts/{account_id}/Sections/{section_id}"


def export_data_path(account_id: int, section_id: int) -> str:
    return (
        f"/API/CASD/Export/Mortgages/Data/Accounts/{account_id}/Sections/{section_id}"
    )


def parse_export_status(payload: dict[str, Any]) -> ExportStatus:
    return ExportStatus(
        account_id=int(payload.get("AccountId") or 0),
        section_id=int(payload.get("SectionId") or 0),
        user_id=int(payload["UserId"]) if payload.get("UserId") is not None else None,
        filter_id=int(payload["FilterId"]) if payload.get("FilterId") is not None else None,
        status_id=int(payload["StatusId"]) if payload.get("StatusId") is not None else None,
        data=payload.get("Data"),
        created_date=payload.get("CreatedDate"),
        executed_date=payload.get("ExecutedDate"),
        raw=payload,
    )


def is_export_ready(
    status: ExportStatus,
    *,
    ready_status_ids: frozenset[int] = DEFAULT_READY_STATUS_IDS,
) -> bool:
    if status.data:
        return True
    if status.status_id in ready_status_ids and status.executed_date:
        return True
    if status.status_id in ready_status_ids:
        return True
    return False


def start_mortgage_export(
    client: CasdClient,
    account_id: int,
    section_id: int,
    *,
    body: dict[str, Any] | None = None,
) -> ExportStatus | None:
    """POST старт экспорта. Тело — camelCase, как в браузере."""
    payload = dict(body or DEFAULT_EXPORT_BODY)
    response = client.request(
        "POST",
        export_path(account_id, section_id),
        json=payload,
    )
    if response.status_code not in (200, 201, 202, 204):
        raise CasdClientError(
            f"Старт экспорта не удался: HTTP {response.status_code} {response.text[:300]}"
        )
    if response.status_code == 204 or not (response.text or "").strip():
        return None
    try:
        return parse_export_status(response.json())
    except Exception:
        return None


def get_mortgage_export_status(
    client: CasdClient,
    account_id: int,
    section_id: int,
) -> ExportStatus | None:
    """GET статус экспорта. 204 = ещё нет данных."""
    response = client.request("GET", export_path(account_id, section_id))
    if response.status_code == 204:
        return None
    if response.status_code != 200:
        raise CasdClientError(
            f"Статус экспорта: HTTP {response.status_code} {response.text[:300]}"
        )
    return parse_export_status(response.json())


def wait_mortgage_export_ready(
    client: CasdClient,
    account_id: int,
    section_id: int,
    *,
    poll_interval: float = 2.0,
    timeout: float = 120.0,
    ready_status_ids: frozenset[int] = DEFAULT_READY_STATUS_IDS,
) -> ExportStatus:
    deadline = time.monotonic() + timeout
    last: ExportStatus | None = None
    while time.monotonic() < deadline:
        last = get_mortgage_export_status(client, account_id, section_id)
        if last is not None and is_export_ready(last, ready_status_ids=ready_status_ids):
            return last
        time.sleep(poll_interval)
    raise CasdClientError(
        f"Таймаут ожидания экспорта account={account_id} section={section_id}; "
        f"last={last.raw if last else None}"
    )


def download_mortgage_export_bytes(
    client: CasdClient,
    account_id: int,
    section_id: int,
) -> bytes:
    """GET .../Export/Mortgages/Data/... → JSON Value (Base64) → bytes."""
    response = client.request("GET", export_data_path(account_id, section_id))
    if response.status_code != 200:
        raise CasdClientError(
            f"Скачивание Data: HTTP {response.status_code} {response.text[:300]}"
        )
    payload = response.json()
    value = payload.get("Value")
    if value is None:
        raise CasdClientError(
            f"В ответе Data нет поля Value: keys={list(payload.keys())}"
        )
    return base64.b64decode(value)


def delete_mortgage_export(
    client: CasdClient,
    account_id: int,
    section_id: int,
) -> None:
    """DELETE статус/файл экспорта (как после клика в UI)."""
    response = client.request("DELETE", export_path(account_id, section_id))
    if response.status_code not in (200, 204):
        raise CasdClientError(
            f"Удаление экспорта: HTTP {response.status_code} {response.text[:300]}"
        )


def save_mortgage_export(
    client: CasdClient,
    account_id: int,
    section_id: int,
    out_dir: Path,
    *,
    start: bool = True,
    cleanup: bool = True,
    poll_interval: float = 2.0,
    wait_timeout: float = 120.0,
    body: dict[str, Any] | None = None,
    filename: str | None = None,
) -> Path:
    """
    Полный цикл: POST (опционально) → poll GET → GET Data → файл.
    Имя по умолчанию: export-{sectionId}.xlsx (как в UI).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if start:
        start_mortgage_export(client, account_id, section_id, body=body)

    wait_mortgage_export_ready(
        client,
        account_id,
        section_id,
        poll_interval=poll_interval,
        timeout=wait_timeout,
    )
    raw = download_mortgage_export_bytes(client, account_id, section_id)
    name = filename or f"export-{section_id}.xlsx"
    target = out_dir / name
    target.write_bytes(raw)

    if cleanup:
        try:
            delete_mortgage_export(client, account_id, section_id)
        except CasdClientError:
            # файл уже сохранён — cleanup best-effort
            pass

    return target
