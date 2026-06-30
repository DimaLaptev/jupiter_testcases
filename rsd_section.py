"""Извлечение кода раздела из ячейки РСД."""

from __future__ import annotations

import re

_SECTION_PREFIX_RE = re.compile(r"^(\S+)")


def extract_section_prefix(section_cell: str) -> str:
    """«260000 - Вне обращения» -> «260000»; первый токен до пробела."""
    s = (section_cell or "").strip()
    if not s:
        return ""
    m = _SECTION_PREFIX_RE.match(s)
    if not m:
        return s
    token = m.group(1)
    try:
        return str(int(float(token)))
    except (ValueError, TypeError):
        return token
