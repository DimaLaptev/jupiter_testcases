"""REGION/SPR: рекурсивный разбор архивов → PDF с [счёт] в имени → колонка S(u)."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path, PurePosixPath

_REGION_PDF_ACCOUNT_RE = re.compile(r"^\[([^\]]+)\]", re.IGNORECASE)
_MAX_ARCHIVE_DEPTH = 25


def extract_account_from_region_pdf_filename(filename: str) -> str | None:
    """[VL0086]….pdf → VL0086 (только имя файла, без пути внутри архива)."""
    base = PurePosixPath((filename or "").replace("\\", "/")).name
    m = _REGION_PDF_ACCOUNT_RE.match(base)
    if not m:
        return None
    return (m.group(1) or "").strip() or None


def normalize_region_account_key(account: str) -> str:
    return (account or "").strip().casefold()


def _count_pdf_in_name(name: str, counts: dict[str, int]) -> None:
    if not name.lower().endswith(".pdf"):
        return
    acc = extract_account_from_region_pdf_filename(name)
    if not acc:
        return
    key = normalize_region_account_key(acc)
    counts[key] = counts.get(key, 0) + 1


def _walk_zip_bytes(data: bytes, counts: dict[str, int], depth: int) -> None:
    if depth > _MAX_ARCHIVE_DEPTH:
        return
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            inner_name = info.filename.replace("\\", "/")
            base = PurePosixPath(inner_name).name
            low = base.lower()
            if low.endswith(".pdf"):
                _count_pdf_in_name(base, counts)
            elif low.endswith(".zip"):
                _walk_zip_bytes(zf.read(info), counts, depth + 1)
            elif low.endswith(".7z"):
                _walk_7z_bytes(zf.read(info), counts, depth + 1)


def _walk_7z_bytes(data: bytes, counts: dict[str, int], depth: int) -> None:
    if depth > _MAX_ARCHIVE_DEPTH:
        return
    try:
        import py7zr
    except ImportError:
        return

    with py7zr.SevenZipFile(io.BytesIO(data), mode="r") as archive:
        for inner_name, bio in archive.readall().items():
            if inner_name.endswith("/"):
                continue
            base = PurePosixPath(inner_name.replace("\\", "/")).name
            low = base.lower()
            if low.endswith(".pdf"):
                _count_pdf_in_name(base, counts)
            elif low.endswith(".zip") and bio is not None:
                _walk_zip_bytes(bio.read(), counts, depth + 1)
            elif low.endswith(".7z") and bio is not None:
                _walk_7z_bytes(bio.read(), counts, depth + 1)


def _walk_archive_file(path: Path, counts: dict[str, int]) -> None:
    suffix = path.suffix.lower()
    data = path.read_bytes()
    if suffix == ".zip":
        _walk_zip_bytes(data, counts, 0)
    elif suffix == ".7z":
        _walk_7z_bytes(data, counts, 0)


def scan_region_spr_pdfs(spr_dir: Path) -> dict[str, int]:
    """
    Только файлы в корне REGION/SPR (вложенные папки не обходятся).
    Рекурсивно: zip/7z → … → pdf; счёт из […] в имени pdf.
    """
    spr_dir = spr_dir.resolve()
    if not spr_dir.is_dir():
        return {}

    counts: dict[str, int] = {}
    for fp in sorted(spr_dir.iterdir()):
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in (".zip", ".7z"):
            continue
        try:
            _walk_archive_file(fp, counts)
        except (OSError, zipfile.BadZipFile):
            continue

    return counts
