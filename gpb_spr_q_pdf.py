"""Сканирование GPB/SPR: PDF Q*_<счёт>_*.pdf → метрики колонки Q (Закл / Лист)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from depo_directory import normalize_account_key


@dataclass
class SprQAccountStats:
    file_count: int = 0
    page_sum: int = 0


_Q_PDF_RE = re.compile(r"^q.+\.pdf$", re.IGNORECASE)


def extract_depo_account_from_q_pdf_name(filename: str) -> str | None:
    """
    Имя вида Q102_33563_00134_….pdf → счёт депо = второй сегмент (после первого «_»).
    """
    name = (filename or "").strip()
    if not _Q_PDF_RE.match(name):
        return None
    stem = Path(name).stem
    parts = stem.split("_")
    if len(parts) < 3:
        return None
    acc = parts[1].strip()
    return acc if acc else None


def pdf_page_count(path: Path) -> int:
    """Число страниц PDF; при ошибке чтения — 0."""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ImportError(
            "Для подсчёта листов PDF установите пакет pypdf: pip install pypdf",
        ) from e
    try:
        reader = PdfReader(str(path))
        return len(reader.pages)
    except OSError:
        return 0


def scan_gpb_spr_q_pdfs(spr_dir: Path) -> dict[str, SprQAccountStats]:
    """
    Каталог GPB/SPR: все Q*.pdf, группировка по normalize_account_key(счёт из имени).
    """
    spr_dir = spr_dir.resolve()
    if not spr_dir.is_dir():
        return {}

    by_acc: dict[str, SprQAccountStats] = {}
    seen_paths: set[Path] = set()

    for pat in ("Q*.pdf", "Q*.PDF", "q*.pdf"):
        for fp in sorted(spr_dir.glob(pat)):
            rp = fp.resolve()
            if rp in seen_paths:
                continue
            seen_paths.add(rp)

            acc_raw = extract_depo_account_from_q_pdf_name(fp.name)
            if not acc_raw:
                continue
            acc_key = normalize_account_key(acc_raw)
            if not acc_key:
                continue

            pages = pdf_page_count(fp)
            if acc_key not in by_acc:
                by_acc[acc_key] = SprQAccountStats()
            by_acc[acc_key].file_count += 1
            by_acc[acc_key].page_sum += pages

    return by_acc
