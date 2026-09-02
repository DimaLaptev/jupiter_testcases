"""Справочник счетов (Accounts) и разделов (Sections) CASD."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from region_lk.client import CasdClient, CasdClientError

PAGE_SIZE = 250


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


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_account_section_row(item: dict[str, Any]) -> tuple[AccountRef, SectionRef] | None:
    """Элемент List: {Account: {...}, Section: {...}}."""
    account_obj = item.get("Account") if isinstance(item.get("Account"), dict) else {}
    section_obj = item.get("Section") if isinstance(item.get("Section"), dict) else {}
    account_id = _optional_int(account_obj.get("Id")) or _optional_int(section_obj.get("AccountId"))
    section_id = _optional_int(section_obj.get("Id"))
    if account_id is None or section_id is None:
        return None
    org = account_obj.get("Organization") if isinstance(account_obj.get("Organization"), dict) else {}
    purpose_obj = section_obj.get("Purpose") if isinstance(section_obj.get("Purpose"), dict) else {}
    account = AccountRef(
        id=account_id,
        number=_optional_str(account_obj.get("Number")),
        name=_optional_str(account_obj.get("Name") or org.get("Name")),
    )
    section = SectionRef(
        id=section_id,
        account_id=account_id,
        number=_optional_str(section_obj.get("Number")),
        purpose=_optional_str(purpose_obj.get("Description") or purpose_obj.get("Code")),
    )
    return account, section


def fetch_organization_accounts_sections(
    client: CasdClient,
    organization_id: int,
    *,
    page_size: int = PAGE_SIZE,
    add_empty_sections: bool = False,
    security_type_id: int | None = None,
) -> list[tuple[AccountRef, SectionRef]]:
    """
    GET /API/CASD/Users/Current/Organizations/{organizationId}/AccountsSections
    с пагинацией (pagination).
    """
    pairs: list[tuple[AccountRef, SectionRef]] = []
    page = 0
    while True:
        params: dict[str, Any] = {
            "page": page,
            "countToPage": page_size,
            "addEmptySections": add_empty_sections,
            "sortBy": "",
            "sortingDirection": "ASC",
        }
        if security_type_id is not None:
            params["sectionSecurityTypeId"] = security_type_id
        response = client.request(
            "GET",
            f"/API/CASD/Users/Current/Organizations/{organization_id}/AccountsSections",
            params=params,
        )
        if response.status_code != 200:
            raise CasdClientError(
                f"Не удалось получить AccountsSections organizationId={organization_id}: "
                f"HTTP {response.status_code} {response.text[:300]}"
            )
        data = response.json()
        items = _as_items(data)
        count_elements = int(data.get("CountElements") or 0) if isinstance(data, dict) else 0
        for item in items:
            parsed = parse_account_section_row(item)
            if parsed is not None:
                pairs.append(parsed)
        if not items:
            break
        if len(items) < page_size:
            break
        if count_elements and (page + 1) * page_size >= count_elements:
            break
        page += 1
    return pairs


def discover_account_sections(
    client: CasdClient,
    organization_id: int,
    *,
    account_id: int | None = None,
    security_type_id: int | None = None,
) -> tuple[list[AccountRef], list[tuple[AccountRef, SectionRef]]]:
    """
    Счета и разделы организации (Users/Current/Organizations/.../AccountsSections).
    Если account_id задан — только этот счёт.
    """
    pairs = fetch_organization_accounts_sections(
        client,
        organization_id,
        security_type_id=security_type_id,
    )
    if account_id is not None:
        pairs = [(acc, sec) for acc, sec in pairs if acc.id == account_id]
    seen: dict[int, AccountRef] = {}
    for account, _section in pairs:
        seen.setdefault(account.id, account)
    return list(seen.values()), pairs
