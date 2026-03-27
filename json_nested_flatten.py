"""
Рекурсивное разворачивание вложенных dict/list из JSON в плоский словарь с префиксом колонок.
Используется в ноутбуках для calculate_parameter (prefix calc_) и operation payload (prefix op_).
"""

from __future__ import annotations

import json
import re
from typing import Any

_SAFE_KEY = re.compile(r"[^0-9a-zA-Z_]+")


def _sanitize_segment(key: str) -> str:
    s = str(key).strip()
    s = _SAFE_KEY.sub("_", s)
    return s.strip("_") or "key"


def flatten_nested_dict(
    obj: dict[str, Any] | None,
    *,
    prefix: str,
    sep: str = "_",
    max_depth: int = 48,
    collapse_value_leaf: bool = True,
) -> dict[str, Any]:
    """
    Рекурсивно раскладывает dict в плоские ключи ``{prefix}{sep}path``.

    - Скаляры и None записываются как есть.
    - dict с единственным ключом ``value`` при ``collapse_value_leaf=True`` не добавляет
      сегмент ``value`` в путь (как в старых flatten_calc_to_dict).
    - list/tuple -> json.dumps.
    - Вложенные dict без скаляра на листе -> обход по ключам.
    """
    out: dict[str, Any] = {}

    def walk(node: Any, segments: list[str], depth: int) -> None:
        if depth > max_depth:
            key = prefix + sep + sep.join(segments) if segments else prefix.rstrip(sep)
            out[key] = (
                json.dumps(node, ensure_ascii=False)
                if not isinstance(node, (int, float, bool, type(None)))
                else node
            )
            return

        if isinstance(node, dict):
            if not node:
                if segments:
                    key = prefix + sep + sep.join(segments)
                    out[key] = ""
                return
            if collapse_value_leaf and set(node.keys()) == {"value"}:
                walk(node["value"], segments, depth + 1)
                return
            for k, v in node.items():
                walk(v, segments + [_sanitize_segment(k)], depth + 1)
        elif isinstance(node, (list, tuple)):
            key = prefix + sep + sep.join(segments) if segments else prefix.rstrip(sep)
            out[key] = json.dumps(node, ensure_ascii=False)
        else:
            key = prefix + sep + sep.join(segments) if segments else prefix.rstrip(sep)
            out[key] = node

    walk(obj or {}, [], 0)
    return out
