"""Реестр загрузчиков (registry)."""

from __future__ import annotations

from typing import TypeVar

from sql_upload.base import SqlLoader

T = TypeVar("T", bound=SqlLoader)

LOADER_REGISTRY: dict[str, SqlLoader] = {}


def register_loader(name: str):
    def decorator(cls: type[T]) -> type[T]:
        instance = cls()
        if not hasattr(instance, "name"):
            instance.name = name  # type: ignore[attr-defined]
        LOADER_REGISTRY[name] = instance
        return cls

    return decorator


def get_loader(name: str) -> SqlLoader:
    if name not in LOADER_REGISTRY:
        known = ", ".join(sorted(LOADER_REGISTRY)) or "(пусто)"
        raise KeyError(f"Неизвестный загрузчик «{name}». Доступны: {known}")
    return LOADER_REGISTRY[name]
