"""
Перемещает файлы вида IS*.xls из ./r/REGION/EDO в ./r/REGION/REP.
Запуск из корня проекта: python move_is_xls_edo_to_rep.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

SOURCE_DIR = Path("./r/REGION/EDO")
DEST_DIR = Path("./r/REGION/REP")


def main() -> None:
    if not SOURCE_DIR.is_dir():
        print(f"[!] Нет папки-источника (source): {SOURCE_DIR.resolve()}")
        sys.exit(1)

    DEST_DIR.mkdir(parents=True, exist_ok=True)

    moved = 0
    for path in sorted(SOURCE_DIR.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if not name.lower().startswith("is") or not name.lower().endswith(".xls"):
            continue
        target = DEST_DIR / name
        if target.exists():
            print(f"[!] Пропуск (уже есть): {name}")
            continue
        shutil.move(str(path), str(target))
        print(f"OK: {name}")
        moved += 1

    print(f"Готово: перемещено {moved} файлов → {DEST_DIR.resolve()}")


if __name__ == "__main__":
    main()
