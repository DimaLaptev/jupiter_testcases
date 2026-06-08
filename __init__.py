"""Регистрация всех загрузчиков в LOADER_REGISTRY (вызывать явно, без циклических import)."""

from __future__ import annotations


def register_all_loaders() -> None:
    from . import (
        gpb,
        region,
        region2,
        rsd,
        rsd_dop,
        spravochnik,
        svod_gpb,
        svod_region,
        svod_rsd,
        svod_vtb,
        vtb,
    )

    _ = (
        gpb,
        region,
        region2,
        rsd,
        rsd_dop,
        vtb,
        svod_gpb,
        svod_region,
        svod_vtb,
        svod_rsd,
        spravochnik,
    )
