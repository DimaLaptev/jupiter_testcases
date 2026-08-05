#!/usr/bin/env python3
"""CLI: скачать вложения (attachments) по всем подписанным заказам текущего пользователя ЛК Region.

Поток (pipeline):
  1) POST /API/UsersCP/Tokens → AuthenticateToken (header)
  2) GET  /API/CASD/Users/Current/Orders (isSigned, isCurrentUserCreated) — пагинация
  3) GET  .../Orders/{id}/Documents — пагинация
  4) GET  /API/CASD/Orders/{id}/Documents/{fileId} → Base64 Value → файл

Переменные окружения (environment variables):
  REGION_LK_BASE_URL          по умолчанию https://lk-test.region-dk.ru
  REGION_LK_EMAIL / REGION_LK_PASSWORD
  REGION_LK_HTTP_PROXY, REGION_LK_PROXY_USER, REGION_LK_PROXY_PASSWORD
  REGION_LK_NO_PROXY=1 (по умолчанию, если нет явного прокси)
  REGION_LK_USE_SYSTEM_PROXY=1
  REGION_LK_SSL_VERIFY=0      отключить проверку SSL (только отладка)
  REGION_LK_TIMEOUT           секунды (по умолчанию 30)

Пример:
  set REGION_LK_EMAIL=user@example.com
  set REGION_LK_PASSWORD=secret
  python scripts/casd_download_attachments.py --out-dir ./casd_downloads
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
from region_lk.orders import fetch_signed_orders  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Скачать вложения подписанных заказов CASD (ЛК Region)",
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
    return parser.parse_args(argv)


def run(out_dir: Path, base_url: str | None, timeout: float | None) -> int:
    config = RegionLkConfig.from_env(base_url=base_url, timeout=timeout)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    skipped = 0
    errors = 0

    with CasdClient(config) as client:
        print(f"Base URL: {config.base_url}")
        print("Авторизация…")
        login(client)
        print("OK: AuthenticateToken получен")

        orders = fetch_signed_orders(client)
        print(f"Подписанных заказов: {len(orders)}")

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
        return run(args.out_dir, args.base_url, args.timeout)
    except CasdAuthError as exc:
        print(f"AUTH: {exc}", file=sys.stderr)
        return 2
    except CasdClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
