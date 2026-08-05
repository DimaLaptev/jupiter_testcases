"""Список подписанных заказов (orders) текущего пользователя."""

from __future__ import annotations

from dataclasses import dataclass

from region_lk.client import CasdClient, CasdClientError

PAGE_SIZE = 250


@dataclass(frozen=True)
class OrderRef:
    id: int
    num: str


def fetch_signed_orders(client: CasdClient, *, page_size: int = PAGE_SIZE) -> list[OrderRef]:
    """
    GET /API/CASD/Users/Current/Orders с пагинацией (pagination).
    Фильтры: isSigned=true, isCurrentUserCreated=true.
    """
    orders: list[OrderRef] = []
    page = 0

    while True:
        response = client.request(
            "GET",
            "/API/CASD/Users/Current/Orders",
            params={
                "page": page,
                "countToPage": page_size,
                "isSigned": "true",
                "isCurrentUserCreated": "true",
            },
        )
        if response.status_code != 200:
            raise CasdClientError(
                f"Не удалось получить заказы: HTTP {response.status_code} {response.text[:300]}"
            )

        data = response.json()
        items = data.get("List") or []
        count_elements = int(data.get("CountElements") or 0)

        for item in items:
            order_id = item.get("Id")
            num = item.get("Num")
            if order_id is None:
                continue
            orders.append(
                OrderRef(
                    id=int(order_id),
                    num=str(num).strip() if num else str(order_id),
                )
            )

        if not items:
            break
        if len(items) < page_size:
            break
        if count_elements and (page + 1) * page_size >= count_elements:
            break
        page += 1

    return orders


def find_order_by_num(orders: list[OrderRef], num: str) -> OrderRef | None:
    """Поиск заказа в списке по полю Num."""
    needle = num.strip()
    for order in orders:
        if order.num == needle:
            return order
    return None
