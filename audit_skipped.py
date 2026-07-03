#!/usr/bin/env python3
"""Отчёт: какие счета/строки пропускаются при парсинге и сборке."""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PIPELINE_ROOT.parent
sys.path.insert(0, str(PIPELINE_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from assemble.builder import build_all_rows
from config import load_config
from extract.gpb_r_msg import iter_gpb_rows, parse_gpb_r_msg
from extract.region import iter_region_rows, _parse_region_file
from extract.rsd_dedupe import _rsd_row_key, dedupe_rsd_do_rows
from extract.rsd_msg import iter_rsd_msg_rows, parse_rsd_r_msg
from extract.rsd_r05 import iter_rsd_r05_rows, parse_r05_statement_xlsx
from extract.vtb import iter_vtb_rows, _parse_vtb_sheet
from models import ALL_PORTFOLIO_SHEETS, SourceKind
from references.depo_dom import DepoDomIndex
from references.spravochnik import Sprav1Lookup, Sprav2Lookup
from sql_upload.excel_grid import read_workbook_sheets
from sql_upload.msg_grid import msg_path_to_rows, sheet_a7_empty, sheet_a8_empty
from unpack import prepare_staging

import re


def _audit_gpb(directory: Path) -> dict:
    skipped_files: list[str] = []
    skipped_rows: list[tuple[str, str, str]] = []
    accounts: Counter[str] = Counter()
    if not directory.is_dir():
        return {"files": skipped_files, "rows": skipped_rows, "accounts": accounts}

    for path in sorted(directory.glob("*.MSG")):
        if not re.match(r"R_\d+_", path.name, re.IGNORECASE):
            continue
        rows = msg_path_to_rows(path)
        if not sheet_a8_empty(rows):
            skipped_files.append(f"{path.name}: A8 не пуста (не REMAINDERS?)")
            continue
        parsed = parse_gpb_r_msg(path)
        if not parsed:
            skipped_files.append(f"{path.name}: 0 строк после парсинга")
        for row in parsed:
            accounts[row.schet_depo] += 1
        for r_idx in range(8, len(rows)):
            row = rows[r_idx]
            if not row or not any((c or "").strip() for c in row):
                continue
            parts = (row[0] or "").split(";") if len(row) == 1 and ";" in (row[0] or "") else row
            if len(parts) < 9:
                skipped_rows.append((path.name, parts[1] if len(parts) > 1 else "?", "мало полей (<9)"))
                continue
            ngri = (parts[8] or "").strip()
            if not ngri:
                skipped_rows.append((path.name, (parts[1] or "").strip(), "пустой НГРИ"))
    return {"files": skipped_files, "rows": skipped_rows, "accounts": accounts}


def _audit_rsd_msg(directory: Path) -> dict:
    skipped_files: list[str] = []
    skipped_rows: list[tuple[str, str, str]] = []
    accounts: Counter[str] = Counter()
    if not directory.is_dir():
        return {"files": skipped_files, "rows": skipped_rows, "accounts": accounts}

    for path in sorted(directory.glob("*.MSG")):
        if not re.match(r"R_\d+_", path.name, re.IGNORECASE):
            continue
        rows = msg_path_to_rows(path)
        if not sheet_a7_empty(rows):
            skipped_files.append(f"{path.name}: A7 не пуста")
            continue
        parsed = parse_rsd_r_msg(path)
        if not parsed:
            skipped_files.append(f"{path.name}: 0 строк после парсинга")
        for row in parsed:
            accounts[row.schet_depo] += 1
        for r_idx in range(7, len(rows)):
            row = rows[r_idx]
            if not row or not any((c or "").strip() for c in row):
                continue
            parts = (row[0] or "").split(";") if len(row) == 1 and ";" in (row[0] or "") else row
            if len(parts) < 6:
                skipped_rows.append((path.name, parts[1] if len(parts) > 1 else "?", "мало полей (<6)"))
                continue
            ngri = (parts[5] or "").strip()
            if not ngri:
                skipped_rows.append((path.name, (parts[1] or "").strip(), "пустой НГРИ"))
    return {"files": skipped_files, "rows": skipped_rows, "accounts": accounts}


def _audit_rsd_r05(directory: Path) -> dict:
    skipped_files: list[str] = []
    skipped_rows: list[tuple[str, str, str]] = []
    accounts: Counter[str] = Counter()
    if not directory.is_dir():
        return {"files": skipped_files, "rows": skipped_rows, "accounts": accounts}

    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".xlsx" or path.name.startswith("~"):
            continue
        parsed = parse_r05_statement_xlsx(path)
        if not parsed:
            skipped_files.append(f"{path.name}: не R-05 / нет таблицы остатков / 0 строк")
        for row in parsed:
            accounts[row.schet_depo or "?"] += 1
            if not row.schet_depo:
                skipped_rows.append((path.name, "?", f"НГРИ {row.ngri_v_depo}: счёт депо не найден в шапке"))
    return {"files": skipped_files, "rows": skipped_rows, "accounts": accounts}


def _audit_region(directory: Path, exclude: list[str]) -> dict:
    exclude_cf = {a.strip().casefold() for a in exclude}
    skipped_files: list[str] = []
    excluded_accounts: Counter[str] = Counter()
    deduped_ngri: list[tuple[str, str, str]] = []
    accounts: Counter[str] = Counter()

    if not directory.is_dir():
        return {
            "files": skipped_files,
            "excluded": excluded_accounts,
            "deduped": deduped_ngri,
            "accounts": accounts,
        }

    seen_paths: set[str] = set()
    all_parsed: list = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name.startswith("~"):
            continue
        if path.suffix.lower() in (".sig", ".pdf", ".zip", ".7z"):
            continue
        key = str(path.resolve()).casefold()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        parsed = _parse_region_file(path)
        if not parsed:
            skipped_files.append(f"{path.name}: формат не распознан / 0 строк")
        else:
            all_parsed.extend(parsed)

    seen_ngri: set[str] = set()
    for row in all_parsed:
        acc = row.schet_depo.strip()
        if exclude_cf and acc.casefold() in exclude_cf:
            excluded_accounts[acc] += 1
            continue
        ngri_key = row.ngri_v_depo.strip().casefold()
        if ngri_key in seen_ngri:
            deduped_ngri.append((acc, row.ngri_v_depo, row.source_file))
            continue
        seen_ngri.add(ngri_key)
        accounts[acc] += 1

    return {
        "files": skipped_files,
        "excluded": excluded_accounts,
        "deduped": deduped_ngri,
        "accounts": accounts,
    }


def _audit_vtb(directory: Path) -> dict:
    skipped_files: list[str] = []
    skipped_rows: list[tuple[str, str, str]] = []
    accounts: Counter[str] = Counter()
    if not directory.is_dir():
        return {"files": skipped_files, "rows": skipped_rows, "accounts": accounts}

    for path in sorted(directory.rglob("*.xlsx")) + sorted(directory.rglob("*.xls")):
        if path.name.startswith("~"):
            continue
        any_sheet = False
        for _name, sheet_rows in read_workbook_sheets(path):
            from sql_upload.excel_grid import cell_at

            parsed = _parse_vtb_sheet(sheet_rows, path.name)
            if parsed:
                any_sheet = True
                schet = parsed[0].schet_depo
                accounts[schet] += len(parsed)
            elif cell_at(sheet_rows, 11, 6) == "Залогодатель":
                last = len(sheet_rows)
                for r in range(13, last + 1):
                    ngri = cell_at(sheet_rows, r, 9).strip()
                    if ngri:
                        continue
                    sec = cell_at(sheet_rows, r, 2).strip()
                    raz = cell_at(sheet_rows, r, 4).strip()
                    if sec or raz:
                        skipped_rows.append((path.name, cell_at(sheet_rows, 6, 7), "пустой НГРИ"))
        if not any_sheet:
            skipped_files.append(f"{path.name}: не выписка ВТБ (нет «Залогодатель» в F11)")
    return {"files": skipped_files, "rows": skipped_rows, "accounts": accounts}


def _audit_rsd_dedupe(before: list, after: list) -> list[tuple]:
    after_keys = {_rsd_row_key(r) for r in after if r.source_kind.value.startswith("RSD")}
    dropped = []
    seen: set = set()
    for row in before:
        if row.source_kind not in {SourceKind.RSD_MSG, SourceKind.RSD_R05, SourceKind.RSD_XLS}:
            continue
        key = _rsd_row_key(row)
        if key in seen:
            dropped.append((row.schet_depo, row.ngri_v_depo, row.source_kind.value, row.source_file))
        else:
            seen.add(key)
    return dropped


def _audit_routing(do_rows: list, sprav1: Sprav1Lookup) -> dict:
    no_account: list[tuple] = []
    no_portfolio: list[tuple] = []
    bad_portfolio: list[tuple] = []
    ok_accounts: Counter[str] = Counter()

    for row in do_rows:
        acc = (row.schet_depo or "").strip()
        ngri = row.ngri_v_depo or ""
        src = row.source_kind.value
        if not acc:
            no_account.append((src, ngri, row.source_file))
            continue
        rec = sprav1.get(acc)
        if rec is None:
            no_portfolio.append((acc, ngri, src, "нет в Справочнике col C"))
            continue
        portfolio = rec.portfolio_section
        if not portfolio:
            no_portfolio.append((acc, ngri, src, "пустой col K «Раздел КП»"))
            continue
        if portfolio not in ALL_PORTFOLIO_SHEETS:
            bad_portfolio.append((acc, ngri, src, f"col K={portfolio!r} не из {list(ALL_PORTFOLIO_SHEETS)}"))
            continue
        ok_accounts[acc] += 1

    return {
        "no_account": no_account,
        "no_portfolio": no_portfolio,
        "bad_portfolio": bad_portfolio,
        "ok": ok_accounts,
    }


def _print_counter(title: str, counter: Counter, limit: int = 30) -> None:
    if not counter:
        return
    print(f"\n### {title} ({sum(counter.values())} строк, {len(counter)} счетов)")
    for acc, cnt in counter.most_common(limit):
        print(f"  {acc}: {cnt}")
    if len(counter) > limit:
        print(f"  ... ещё {len(counter) - limit} счетов")


def _print_list(title: str, items: list, limit: int = 20) -> None:
    if not items:
        return
    print(f"\n### {title} ({len(items)})")
    for item in items[:limit]:
        print(f"  {item}")
    if len(items) > limit:
        print(f"  ... ещё {len(items) - limit}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Аудит пропущенных счетов/строк")
    parser.add_argument("--pipeline-root", type=Path, default=PIPELINE_ROOT)
    parser.add_argument("--gpb", type=Path, default=None)
    parser.add_argument("--rsd-msg", type=Path, default=None)
    parser.add_argument("--rsd-exl", type=Path, default=None)
    parser.add_argument("--region", type=Path, default=None)
    parser.add_argument("--vtbsd", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = load_config(args.pipeline_root)
    gpb = args.gpb or cfg.gpb
    rsd_msg = args.rsd_msg or cfg.rsd_msg
    rsd_exl = args.rsd_exl or cfg.rsd_exl
    region = args.region or cfg.region
    vtbsd = args.vtbsd or cfg.vtbsd

    staging = prepare_staging([region, rsd_exl], cfg.staging)
    rsd_exl_root = args.rsd_exl or (staging / "RSD_EXL" if (staging / "RSD_EXL").is_dir() else rsd_exl)
    region_root = args.region or (staging / "REGION" if (staging / "REGION").is_dir() else region)
    vtbsd_root = args.vtbsd or (staging / "VTBSD" if (staging / "VTBSD").is_dir() else vtbsd)

    print("=== Аудит пропусков SVOD DEPO ===")
    print(f"GPB:      {gpb}")
    print(f"RSD MSG:  {rsd_msg}")
    print(f"RSD EXL:  {rsd_exl_root}")
    print(f"REGION:   {region_root}")
    print(f"VTBSD:    {vtbsd_root}")
    print(f"Исключённые Region-счета (paths.yaml): {cfg.region_exclude_accounts}")

    gpb_a = _audit_gpb(gpb)
    rsd_msg_a = _audit_rsd_msg(rsd_msg)
    rsd_r05_a = _audit_rsd_r05(rsd_exl_root)
    region_a = _audit_region(region_root, cfg.region_exclude_accounts)
    vtb_a = _audit_vtb(vtbsd_root)

    for label, audit in [
        ("GPB — файлы", gpb_a["files"]),
        ("RSD MSG — файлы", rsd_msg_a["files"]),
        ("RSD R-05 — файлы", rsd_r05_a["files"]),
        ("REGION — файлы", region_a["files"]),
        ("VTB — файлы", vtb_a["files"]),
    ]:
        _print_list(label, audit)

    _print_list("GPB — строки без НГРИ", gpb_a["rows"])
    _print_list("RSD MSG — строки без НГРИ", rsd_msg_a["rows"])
    _print_list("RSD R-05 — строки без счёта в шапке", rsd_r05_a["rows"])
    _print_list("VTB — строки без НГРИ", vtb_a["rows"])
    _print_counter("REGION — исключены по region_exclude_accounts", region_a["excluded"])
    _print_list("REGION — дубликаты по НГРИ (второе вхождение)", region_a["deduped"])

    before = []
    before.extend(iter_gpb_rows(gpb))
    before.extend(iter_rsd_msg_rows(rsd_msg))
    before.extend(iter_rsd_r05_rows(rsd_exl_root))
    before.extend(iter_region_rows(region_root, cfg.region_exclude_accounts, warn=sys.stdout))
    before.extend(iter_vtb_rows(vtbsd_root))
    after = dedupe_rsd_do_rows(before)
    rsd_dropped = _audit_rsd_dedupe(before, after)
    _print_list("RSD — удалены dedupe (schet_depo, ngri, source_kind, source_file)", rsd_dropped)

    sprav1 = Sprav1Lookup.load(cfg.sprav_workbook)
    if not cfg.sprav_workbook.is_file():
        print(f"\nВНИМАНИЕ: Справочник не найден: {cfg.sprav_workbook}")
        print("  Маршрутизация (col K) не проверена.")
    else:
        route = _audit_routing(after, sprav1)
        _print_list("Сборка — пустой счёт депо", route["no_account"])
        _print_list("Сборка — нет маршрута в Справочнике", route["no_portfolio"])
        _print_list("Сборка — неизвестный «Раздел КП»", route["bad_portfolio"])
        _print_counter("Сборка — успешно маршрутизированы", route["ok"])

        depo_ia = DepoDomIndex.load(cfg.depo_ia, ("GPB", "REGION", "VTBSD", "RSD_XLS"))
        depo_dom = DepoDomIndex.load(cfg.depo_dom, ("GPB", "RSD_MSG", "REGION", "VTBSD"))
        sprav2 = Sprav2Lookup.load(cfg.sprav_workbook)
        from io import StringIO

        buf = StringIO()
        build_all_rows(after, depo_ia, depo_dom, sprav1, sprav2, warn=buf)
        warnings = buf.getvalue().strip()
        if warnings:
            print("\n### Предупреждения build_all_rows")
            print(warnings)

    print(f"\nИтого строк после парсинга: {len(before)} -> после RSD dedupe: {len(after)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
