#!/usr/bin/env python3
"""CLI: скачать вложения (attachments) по заказам текущего пользователя ЛК Region.

Поток (pipeline):
  1) POST /API/UsersCP/Tokens → AuthenticateToken (header)
  2) GET  /API/CASD/Users/Current/Orders — пагинация (фильтры CLI)
  3) GET  .../Orders/{id}/Documents — пагинация
  4) GET  /API/CASD/Orders/{id}/Documents/{fileId} → Base64 Value → файл

Переменные окружения (environment variables):
  REGION_LK_BASE_URL          по умолчанию https://lk-test.region-dk.ru
  REGION_LK_EMAIL / REGION_LK_PASSWORD
  REGION_LK_HTTP_PROXY, REGION_LK_PROXY_USER, REGION_LK_PROXY_PASSWORD
  REGION_LK_NO_PROXY=1
  REGION_LK_USE_SYSTEM_PROXY=1
  REGION_LK_SSL_VERIFY=0
  REGION_LK_TIMEOUT

Примеры:
  python scripts/casd_download_attachments.py --out-dir ./casd_downloads
  python scripts/casd_download_attachments.py --all-orders --out-dir ./casd_downloads
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _bootstrap_src() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


_bootstrap_src()

from region_lk.auth import login  # noqa: E402
from region_lk.client import CasdAuthError, CasdClient, CasdClientError  # noqa: E402
from region_lk.config import RegionLkConfig  # noqa: E402
from region_lk.documents import (  # noqa: E402
    fetch_order_documents,
    sanitize_filename,
    save_document,
)
from region_lk.orders import fetch_orders  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Скачать вложения заказов CASD (ЛК Region)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("casd_downloads"),
        help="Каталог для файлов (по умолчанию ./casd_downloads)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Базовый URL ЛК (иначе REGION_LK_BASE_URL или lk-test)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Таймаут HTTP в секундах",
    )
    parser.add_argument(
        "--all-orders",
        action="store_true",
        help="Все заказы без фильтра isSigned (по умолчанию только подписанные)",
    )
    parser.add_argument(
        "--all-users",
        action="store_true",
        help="Без фильтра isCurrentUserCreated (по умолчанию только свои заказы)",
    )
    return parser.parse_args(argv)


def run(
    out_dir: Path,
    base_url: str | None,
    timeout: float | None,
    *,
    all_orders: bool = False,
    all_users: bool = False,
) -> int:
    config = RegionLkConfig.from_env(base_url=base_url, timeout=timeout)
    out_dir.mkdir(parents=True, exist_ok=True)

    is_signed: bool | None = None if all_orders else True
    is_current_user_created: bool | None = None if all_users else True

    saved = 0
    skipped = 0
    errors = 0

    with CasdClient(config) as client:
        proxy_view = config.proxies if config.proxies is not None else "(system/trust_env)"
        print(f"Base URL: {config.base_url}")
        print(f"Email:    {config.email or '(пусто — задайте REGION_LK_EMAIL)'}")
        print(f"Password: задан, длина {len(config.password)}" if config.password else "Password: (пусто)")
        print(f"Proxies:  {proxy_view}")
        print(f"trust_env:{config.trust_env}")
        print(f"Filters:  isSigned={is_signed} isCurrentUserCreated={is_current_user_created}")
        print("Авторизация…")
        login(client)
        print("OK: AuthenticateToken получен")

        orders = fetch_orders(
            client,
            is_signed=is_signed,
            is_current_user_created=is_current_user_created,
        )
        print(f"Заказов: {len(orders)}")

        for order in orders:
            order_dir = out_dir / sanitize_filename(order.num)
            try:
                docs = fetch_order_documents(client, order.id)
            except CasdClientError as exc:
                print(f"[{order.num}] ошибка списка документов: {exc}", file=sys.stderr)
                errors += 1
                continue

            if not docs:
                print(f"[{order.num}] документов нет — skip")
                continue

            print(f"[{order.num}] документов: {len(docs)}")
            for doc in docs:
                try:
                    path, status = save_document(client, order.id, doc, order_dir)
                    if status == "skipped":
                        skipped += 1
                        print(f"  skip {path.name}")
                    else:
                        saved += 1
                        print(f"  {status} {path.name}")
                except (CasdClientError, CasdAuthError, OSError, ValueError) as exc:
                    errors += 1
                    print(
                        f"  ERROR file_id={doc.file_id}: {exc}",
                        file=sys.stderr,
                    )

    print(f"Готово: saved={saved} skipped={skipped} errors={errors}")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(
            args.out_dir,
            args.base_url,
            args.timeout,
            all_orders=args.all_orders,
            all_users=args.all_users,
        )
    except CasdAuthError as exc:
        print(f"AUTH: {exc}", file=sys.stderr)
        return 2
    except CasdClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
