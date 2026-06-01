"""Загрузчики — импорт для регистрации в LOADER_REGISTRY."""

from sql_upload.loaders import gpb, region, region2, rsd, rsd_dop, vtb

__all__ = ["gpb", "region", "region2", "rsd", "rsd_dop", "vtb"]
