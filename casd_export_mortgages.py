#!/usr/bin/env python3
"""CLI: экспорт закладных (Mortgages) раздела счёта в Excel через CASD API.

Поток (как в браузере):
  1) POST /API/UsersCP/Tokens → AuthenticateToken (+ user Id из body)
  2) GET  /API/CASD/Users/{userId}/Accounts
  3) GET  /API/CASD/Account/{accountId}/Sections — по каждому счёту
  4) POST /API/CASD/Export/Mortgages/Accounts/{accountId}/Sections/{sectionId}
  5) GET  тот же path — poll до StatusId готовности
  6) GET  /API/CASD/Export/Mortgages/Data/Accounts/{accountId}/Sections/{sectionId}
     → Value (Base64) → export-{sectionId}.xlsx
  7) DELETE тот же path статуса (опционально)

Переменные запроса вписывайте в блок «заполните вручную» ниже
(CLI-флаги, если переданы, перекрывают эти значения).

Примеры:
  python scripts/casd_export_mortgages.py
  python scripts/casd_export_mortgages.py --all --out-dir ./casd_exports
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

# --- заполните вручную ---
BASE_URL = "http://lk-test.region-dk.ru"
EMAIL = "xxx@xx.ru"
PASSWORD = "xxx"

PROXY_URL = "http://127.0.0.1:3128"  # "" или None — без прокси
PROXY_USER = ""
PROXY_PASSWORD = ""

SSL_VERIFY = True
TIMEOUT = 30.0

# True = GET все Accounts/Sections и экспорт каждой пары
EXPORT_ALL = False
LIST_ONLY = False
ACCOUNT_ID = 163  # или None
SECTION_ID = 66  # или None
USER_ID = None  # None = Id из ответа логина
SECURITY_TYPE_ID = None  # query securityTypeId для списка разделов

OUT_DIR = "./casd_exports"
POLL_INTERVAL = 2.0
WAIT_TIMEOUT = 120.0
NO_START = False
NO_CLEANUP = False
FILENAME = None  # None → export-{sectionId}.xlsx

EXPORT_BODY = {
    "addWithoutDrafts": True,
    "addCurrentUserDrafts": True,
    "addOtherUsersDrafts": True,
    "addIncludedInOrders": True,
}
# -------------------------


def _proxy_url_with_auth(proxy_url: str, user: str, password: str) -> str:
    if not user:
        return proxy_url
    parsed = urlparse(proxy_url)
    if parsed.username:
        return proxy_url
    auth = quote(user, safe="")
    if password:
        auth = f"{auth}:{quote(password, safe='')}"
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{auth}@{host}{port}{parsed.path or ''}"


def _bootstrap_src() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


_bootstrap_src()

from region_lk.auth import login  # noqa: E402
from region_lk.catalog import AccountRef, SectionRef, discover_account_sections  # noqa: E402
from region_lk.client import CasdAuthError, CasdClient, CasdClientError  # noqa: E402
from region_lk.config import RegionLkConfig  # noqa: E402
from region_lk.mortgage_export import save_mortgage_export  # noqa: E402


def _hardcoded_config(*, base_url: str | None, timeout: float | None) -> RegionLkConfig:
    proxy = (PROXY_URL or "").strip()
    if proxy:
        full = _proxy_url_with_auth(proxy, PROXY_USER, PROXY_PASSWORD)
        proxies: dict[str, str] | None = {"http": full, "https": full}
        trust_env = False
    else:
        proxies = {}
        trust_env = False
    return RegionLkConfig(
        base_url=(base_url or BASE_URL).rstrip("/"),
        email=EMAIL.strip(),
        password=PASSWORD,
        timeout=float(timeout if timeout is not None else TIMEOUT),
        ssl_verify=bool(SSL_VERIFY),
        proxies=proxies,
        trust_env=trust_env,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Экспорт закладных раздела CASD в Excel (export-{sectionId}.xlsx)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=EXPORT_ALL,
        help="Вытащить все Accounts пользователя и все Sections, затем экспортировать каждую пару",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        default=LIST_ONLY,
        help="Только вывести счета и разделы, без экспорта файлов",
    )
    parser.add_argument("--account-id", type=int, default=ACCOUNT_ID, help="ID счёта (Accounts)")
    parser.add_argument("--section-id", type=int, default=SECTION_ID, help="ID раздела (Sections)")
    parser.add_argument(
        "--user-id",
        type=int,
        default=USER_ID,
        help="ID пользователя для GET .../Users/{userId}/Accounts (иначе Id из логина)",
    )
    parser.add_argument(
        "--security-type-id",
        type=int,
        default=SECURITY_TYPE_ID,
        help="Опциональный query securityTypeId для списка разделов",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(OUT_DIR),
        help="Каталог для xlsx",
    )
    parser.add_argument("--base-url", default=None, help="Базовый URL ЛК (иначе BASE_URL в файле)")
    parser.add_argument("--timeout", type=float, default=None, help="Таймаут HTTP, сек")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=POLL_INTERVAL,
        help="Интервал опроса статуса, сек",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=WAIT_TIMEOUT,
        help="Макс. ожидание готовности экспорта, сек",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        default=NO_START,
        help="Не делать POST (только poll + скачать уже готовый экспорт)",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        default=NO_CLEANUP,
        help="Не делать DELETE после скачивания",
    )
    parser.add_argument(
        "--filename",
        default=FILENAME,
        help="Имя файла для одной пары (по умолчанию export-{sectionId}.xlsx)",
    )
    return parser.parse_args(argv)


def _resolve_targets(args: argparse.Namespace) -> None:
    if args.list_only:
        return
    if args.all:
        return
    if args.account_id is not None and args.section_id is not None:
        return
    if args.account_id is not None and args.section_id is None:
        return
    raise SystemExit(
        "Укажите --all (все счета/разделы) или --account-id и --section-id "
        "(для всех разделов одного счёта достаточно --account-id)."
    )


def _print_catalog(
    accounts: list[AccountRef],
    pairs: list[tuple[AccountRef, SectionRef]],
) -> None:
    print(f"Счетов: {len(accounts)}")
    for account in accounts:
        label = account.number or account.name or "-"
        print(f"  Account Id={account.id} Number={label}")
    print(f"Разделов: {len(pairs)}")
    for account, section in pairs:
        sec_label = section.number or "-"
        print(
            f"  Section Id={section.id} Number={sec_label} "
            f"accountId={account.id}"
        )


def _export_one(
    client: CasdClient,
    account_id: int,
    section_id: int,
    out_dir: Path,
    args: argparse.Namespace,
    *,
    nested: bool,
) -> Path:
    target_dir = out_dir / f"account_{account_id}" if nested else out_dir
    filename = args.filename if not nested else None
    return save_mortgage_export(
        client,
        account_id,
        section_id,
        target_dir,
        start=not args.no_start,
        cleanup=not args.no_cleanup,
        poll_interval=args.poll_interval,
        wait_timeout=args.wait_timeout,
        body=EXPORT_BODY,
        filename=filename,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        _resolve_targets(args)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2

    config = _hardcoded_config(base_url=args.base_url, timeout=args.timeout)

    try:
        with CasdClient(config) as client:
            proxy_view = config.proxies if config.proxies is not None else "(system/trust_env)"
            print(f"Base URL:   {config.base_url}")
            print(f"Email:      {config.email or '(пусто)'}")
            print(f"Proxies:    {proxy_view}")
            print(f"Export body:{EXPORT_BODY}")
            print("Авторизация…")
            token = login(client)
            print(f"OK: AuthenticateToken (len={len(token)})")

            user_id = args.user_id if args.user_id is not None else client.user_id
            need_catalog = args.all or args.list_only or (
                args.account_id is not None and args.section_id is None
            )
            if need_catalog and user_id is None:
                raise CasdClientError(
                    "Не удалось взять userId из логина. Передайте --user-id явно."
                )

            if args.account_id is not None and args.section_id is not None and not args.all:
                pairs = [
                    (
                        AccountRef(id=args.account_id),
                        SectionRef(id=args.section_id, account_id=args.account_id),
                    )
                ]
                if args.list_only:
                    print(f"UserId: {user_id}")
                    _print_catalog([AccountRef(id=args.account_id)], pairs)
                    return 0
                print(f"AccountId:  {args.account_id}")
                print(f"SectionId:  {args.section_id}")
                path = _export_one(
                    client,
                    args.account_id,
                    args.section_id,
                    args.out_dir,
                    args,
                    nested=False,
                )
                print(f"Saved: {path} ({path.stat().st_size} bytes)")
                return 0

            assert user_id is not None
            print(f"UserId:     {user_id}")
            accounts, pairs = discover_account_sections(
                client,
                user_id,
                account_id=args.account_id,
                security_type_id=args.security_type_id,
            )
            _print_catalog(accounts, pairs)
            if args.list_only:
                return 0
            if not pairs:
                print("Пар Account/Section нет — нечего экспортировать", file=sys.stderr)
                return 1

            saved = 0
            errors = 0
            nested = len(pairs) > 1
            for account, section in pairs:
                try:
                    path = _export_one(
                        client,
                        account.id,
                        section.id,
                        args.out_dir,
                        args,
                        nested=nested,
                    )
                    saved += 1
                    print(f"Saved: {path} ({path.stat().st_size} bytes)")
                except (CasdClientError, CasdAuthError, OSError, ValueError) as exc:
                    errors += 1
                    print(
                        f"ERROR account={account.id} section={section.id}: {exc}",
                        file=sys.stderr,
                    )
            print(f"Готово: saved={saved} errors={errors}")
            return 1 if errors else 0
    except CasdAuthError as exc:
        print(f"AUTH: {exc}", file=sys.stderr)
        return 2
    except CasdClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
