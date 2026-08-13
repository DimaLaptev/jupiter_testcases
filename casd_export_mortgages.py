#!/usr/bin/env python3
"""CLI: экспорт закладных (Mortgages) раздела счёта в Excel через CASD API.

Поток (как в браузере):
  1) POST /API/UsersCP/Tokens → AuthenticateToken
  2) POST /API/CASD/Export/Mortgages/Accounts/{accountId}/Sections/{sectionId}
     body camelCase: addWithoutDrafts, addCurrentUserDrafts, ...
  3) GET  тот же path — poll до StatusId готовности
  4) GET  /API/CASD/Export/Mortgages/Data/Accounts/{accountId}/Sections/{sectionId}
     → Value (Base64) → export-{sectionId}.xlsx
  5) DELETE тот же path статуса (опционально, как UI после скачивания)

Env — те же REGION_LK_* что у casd_download_attachments.py.

Пример:
  python scripts/casd_export_mortgages.py --account-id 163 --section-id 66 --out-dir ./casd_exports
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
from region_lk.mortgage_export import (  # noqa: E402
    DEFAULT_EXPORT_BODY,
    save_mortgage_export,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Экспорт закладных раздела CASD в Excel (export-{sectionId}.xlsx)",
    )
    parser.add_argument("--account-id", type=int, required=True, help="ID счёта (Accounts)")
    parser.add_argument("--section-id", type=int, required=True, help="ID раздела (Sections)")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("casd_exports"),
        help="Каталог для xlsx (по умолчанию ./casd_exports)",
    )
    parser.add_argument("--base-url", default=None, help="Базовый URL ЛК")
    parser.add_argument("--timeout", type=float, default=None, help="Таймаут HTTP, сек")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Интервал опроса статуса, сек",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=120.0,
        help="Макс. ожидание готовности экспорта, сек",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Не делать POST (только poll + скачать уже готовый экспорт)",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Не делать DELETE после скачивания",
    )
    parser.add_argument(
        "--filename",
        default=None,
        help="Имя файла (по умолчанию export-{sectionId}.xlsx)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = RegionLkConfig.from_env(base_url=args.base_url, timeout=args.timeout)

    try:
        with CasdClient(config) as client:
            proxy_view = config.proxies if config.proxies is not None else "(system/trust_env)"
            print(f"Base URL:   {config.base_url}")
            print(f"Email:      {config.email or '(пусто)'}")
            print(f"Proxies:    {proxy_view}")
            print(f"AccountId:  {args.account_id}")
            print(f"SectionId:  {args.section_id}")
            print(f"Export body:{DEFAULT_EXPORT_BODY}")
            print("Авторизация…")
            token = login(client)
            print(f"OK: AuthenticateToken (len={len(token)})")

            path = save_mortgage_export(
                client,
                args.account_id,
                args.section_id,
                args.out_dir,
                start=not args.no_start,
                cleanup=not args.no_cleanup,
                poll_interval=args.poll_interval,
                wait_timeout=args.wait_timeout,
                filename=args.filename,
            )
            print(f"Saved: {path} ({path.stat().st_size} bytes)")
        return 0
    except CasdAuthError as exc:
        print(f"AUTH: {exc}", file=sys.stderr)
        return 2
    except CasdClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
