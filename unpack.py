"""Рекурсивная распаковка zip/7z в staging."""

from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path


def _extract_zip_bytes(data: bytes, dest: Path, depth: int, max_depth: int = 25) -> None:
    if depth > max_depth:
        return
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            base = Path(name).name
            if not base:
                continue
            low = base.lower()
            target = dest / base
            if low.endswith((".zip", ".7z")):
                nested = zf.read(info)
                sub = dest / f"_nested_{depth}_{base}"
                sub.mkdir(exist_ok=True)
                if low.endswith(".zip"):
                    _extract_zip_bytes(nested, sub, depth + 1, max_depth)
                else:
                    _extract_7z_bytes(nested, sub, depth + 1, max_depth)
            else:
                target.write_bytes(zf.read(info))


def _extract_7z_bytes(data: bytes, dest: Path, depth: int, max_depth: int = 25) -> None:
    if depth > max_depth:
        return
    try:
        import py7zr
    except ImportError:
        return
    dest.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(io.BytesIO(data), mode="r") as ar:
        ar.extractall(path=dest)
    for p in dest.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".zip", ".7z"):
            sub = p.parent / f"_nested_{depth}_{p.stem}"
            sub.mkdir(exist_ok=True)
            raw = p.read_bytes()
            if p.suffix.lower() == ".zip":
                _extract_zip_bytes(raw, sub, depth + 1, max_depth)
            else:
                _extract_7z_bytes(raw, sub, depth + 1, max_depth)


def extract_archive(path: Path, dest: Path, depth: int = 0, max_depth: int = 25) -> None:
    low = path.suffix.lower()
    dest.mkdir(parents=True, exist_ok=True)
    if low == ".zip":
        _extract_zip_bytes(path.read_bytes(), dest, depth, max_depth)
    elif low == ".7z":
        _extract_7z_bytes(path.read_bytes(), dest, depth, max_depth)
    else:
        shutil.copy2(path, dest / path.name)


def prepare_staging(source_dirs: list[Path], staging_root: Path) -> Path:
    """Распаковать архивы из каталогов в staging; скопировать остальные файлы."""
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

    for src_dir in source_dirs:
        if not src_dir.is_dir():
            continue
        sub = staging_root / src_dir.name
        sub.mkdir(parents=True, exist_ok=True)
        for path in src_dir.rglob("*"):
            if not path.is_file():
                continue
            rel_parent = path.parent.relative_to(src_dir)
            target_dir = sub / rel_parent
            target_dir.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() in (".zip", ".7z"):
                extract_archive(path, target_dir / path.stem)
            else:
                shutil.copy2(path, target_dir / path.name)
    return staging_root


def iter_data_files(root: Path, extensions: tuple[str, ...]) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in extensions:
            out.append(p)
    return out
