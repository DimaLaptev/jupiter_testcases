"""Сканирование GPB/SPR: архивы SPR_<счёт>_*.zip|7z → метрики колонки S(u) (Закл / Лист)."""

from __future__ import annotations

import re
from pathlib import Path

from depo_directory import normalize_account_key

_SPR_ARCHIVE_RE = re.compile(r"^spr_.+\.(zip|7z)$", re.IGNORECASE)


def extract_depo_account_from_spr_archive_name(filename: str) -> str | None:
    """
    Имя вида SPR_33563_00184_1_1.zip → счёт депо = второй сегмент (после первого «_»).
    """
    name = (filename or "").strip()
    if not _SPR_ARCHIVE_RE.match(name):
        return None
    stem = Path(name).stem
    if not stem.upper().startswith("SPR"):
        return None
    parts = stem.split("_")
    if len(parts) < 3:
        return None
    acc = parts[1].strip()
    return acc if acc else None


def scan_gpb_spr_su_archives(spr_dir: Path) -> dict[str, int]:
    """
    Каталог GPB/SPR: архивы SPR*.zip / SPR*.7z → число файлов по счёту депо.
    """
    spr_dir = spr_dir.resolve()
    if not spr_dir.is_dir():
        return {}

    by_acc: dict[str, int] = {}
    seen_paths: set[Path] = set()

    for pat in (
        "SPR*.zip",
        "SPR*.ZIP",
        "SPR*.7z",
        "SPR*.7Z",
        "spr*.zip",
        "spr*.7z",
    ):
        for fp in sorted(spr_dir.glob(pat)):
            rp = fp.resolve()
            if rp in seen_paths:
                continue
            seen_paths.add(rp)

            acc_raw = extract_depo_account_from_spr_archive_name(fp.name)
            if not acc_raw:
                continue
            acc_key = normalize_account_key(acc_raw)
            if not acc_key:
                continue
            by_acc[acc_key] = by_acc.get(acc_key, 0) + 1

    return by_acc
