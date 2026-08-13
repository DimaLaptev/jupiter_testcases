"""Справочник счетов (Accounts) и разделов (Sections) CASD."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from region_lk.client import CasdClient, CasdClientError


@dataclass(frozen=True)
class AccountRef:
    id: int
    number: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class SectionRef:
    id: int
    account_id: int
    number: str | None = None
    purpose: str | None = None


def _as_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        nested = payload.get("List")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        if payload.get("Id") is not None:
            return [payload]
    return []


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_user_accounts(client: CasdClient, user_id: int) -> list[AccountRef]:
    """GET /API/CASD/Users/{userId}/Accounts."""
    response = client.request("GET", f"/API/CASD/Users/{user_id}/Accounts")
    if response.status_code != 200:
        raise CasdClientError(
            f"Не удалось получить счета userId={user_id}: "
            f"HTTP {response.status_code} {response.text[:300]}"
        )
    accounts: list[AccountRef] = []
    for item in _as_items(response.json()):
        account_id = _optional_int(item.get("Id"))
        if account_id is None:
            continue
        org = item.get("Organization") if isinstance(item.get("Organization"), dict) else {}
        number = item.get("Number")
        name = item.get("Name") or (org.get("Name") if org else None)
        accounts.append(
            AccountRef(
                id=account_id,
                number=str(number).strip() if number else None,
                name=str(name).strip() if name else None,
            )
        )
    return accounts


def fetch_account_sections(
    client: CasdClient,
    account_id: int,
    *,
    security_type_id: int | None = None,
) -> list[SectionRef]:
    """GET /API/CASD/Account/{accountId}/Sections."""
    params: dict[str, Any] = {}
    if security_type_id is not None:
        params["securityTypeId"] = security_type_id
    response = client.request(
        "GET",
        f"/API/CASD/Account/{account_id}/Sections",
        params=params or None,
    )
    if response.status_code != 200:
        raise CasdClientError(
            f"Не удалось получить разделы accountId={account_id}: "
            f"HTTP {response.status_code} {response.text[:300]}"
        )
    sections: list[SectionRef] = []
    for item in _as_items(response.json()):
        section_id = _optional_int(item.get("Id"))
        if section_id is None:
            continue
        nested_account = item.get("Account") if isinstance(item.get("Account"), dict) else {}
        nested_account_id = _optional_int(nested_account.get("Id")) or account_id
        purpose_obj = item.get("Purpose") if isinstance(item.get("Purpose"), dict) else {}
        purpose = purpose_obj.get("Description") or purpose_obj.get("Code")
        number = item.get("Number")
        sections.append(
            SectionRef(
                id=section_id,
                account_id=nested_account_id,
                number=str(number).strip() if number else None,
                purpose=str(purpose).strip() if purpose else None,
            )
        )
    return sections


def discover_account_sections(
    client: CasdClient,
    user_id: int,
    *,
    account_id: int | None = None,
    security_type_id: int | None = None,
) -> tuple[list[AccountRef], list[tuple[AccountRef, SectionRef]]]:
    """
    Счета пользователя и разделы по каждому счёту.
    Если account_id задан — только этот счёт.
    """
    accounts = fetch_user_accounts(client, user_id)
    if account_id is not None:
        accounts = [acc for acc in accounts if acc.id == account_id]
        if not accounts:
            accounts = [AccountRef(id=account_id)]

    pairs: list[tuple[AccountRef, SectionRef]] = []
    for account in accounts:
        for section in fetch_account_sections(
            client,
            account.id,
            security_type_id=security_type_id,
        ):
            pairs.append((account, section))
    return accounts, pairs
